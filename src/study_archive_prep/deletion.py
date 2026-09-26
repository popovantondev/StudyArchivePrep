"""Explicit, journaled deletion of verified source recordings."""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .audio import AudioExtractionResult
from .operation_journal import JournalError, OperationJournal


class DeletionError(RuntimeError):
    """A selected original could not be safely deleted."""


@dataclass(frozen=True)
class OriginalDeletionReceipt:
    project_id: str
    source_file_id: str
    source_path: str
    source_size: int
    source_mtime_ns: int
    source_sha256: str
    audio_path: str
    audio_size: int
    audio_sha256: str
    container_exports_complete: bool

    @classmethod
    def from_extraction(cls, project_id: str, source_file_id: str,
                        source_path: str | Path, result: AudioExtractionResult,
                        *, container_exports_complete: bool) -> "OriginalDeletionReceipt":
        if result.source_sha256 is None:
            raise DeletionError("Audio extraction did not record a source fingerprint for deletion.")
        return cls(project_id, source_file_id, str(Path(source_path).resolve(strict=False)),
                   result.source_size, result.source_mtime_ns, result.source_sha256,
                   result.output_path, result.size, result.output_sha256,
                   container_exports_complete)


@dataclass(frozen=True)
class DeletionResult:
    deleted_paths: tuple[str, ...]
    already_deleted_paths: tuple[str, ...]


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_audio(receipt: OriginalDeletionReceipt) -> None:
    audio = Path(receipt.audio_path)
    try:
        info = audio.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise DeletionError("The checked audio result is not a regular file.")
        if info.st_size != receipt.audio_size or _hash(audio) != receipt.audio_sha256:
            raise DeletionError("The checked audio result changed after extraction.")
    except OSError as exc:
        raise DeletionError("The checked audio result is unavailable.") from exc


def _delete_verified_originals(receipts: tuple[OriginalDeletionReceipt, ...] | list[OriginalDeletionReceipt],
                               approved_source_paths: tuple[str | Path, ...] | list[str | Path],
                               journal: OperationJournal) -> DeletionResult:
    """Delete only the exact, explicitly approved originals with durable audio receipts."""
    normalized = tuple(Path(receipt.source_path).resolve(strict=False) for receipt in receipts)
    approved = tuple(Path(path).expanduser().resolve(strict=False) for path in approved_source_paths)
    if not receipts or len(normalized) != len(set(normalized)) or set(normalized) != set(approved) or len(approved) != len(set(approved)):
        raise DeletionError("The approved source list must exactly match the selected recordings.")
    deleted: list[str] = []
    already: list[str] = []
    for receipt, canonical_source in zip(receipts, normalized):
        if not receipt.container_exports_complete:
            raise DeletionError("Other selected data from the recording container has not been saved.")
        if receipt.source_sha256 is None or len(receipt.source_sha256) != 64:
            raise DeletionError("A source checksum is required before deletion.")
        _verified_audio(receipt)
        existing_id = journal.record_deletion_receipt(receipt)
        status = journal.deletion_status(existing_id)
        source = Path(receipt.source_path)
        try:
            info = source.lstat()
        except FileNotFoundError:
            if status in {"deleting", "deleted"}:
                journal.update_deletion(existing_id, "deleted")
                already.append(str(canonical_source))
                continue
            journal.update_deletion(existing_id, "needs_attention", "Source vanished before a confirmed delete operation.")
            raise DeletionError("The original is missing without a confirmed delete record.")
        except OSError as exc:
            journal.update_deletion(existing_id, "needs_attention", "Original cannot be checked.")
            raise DeletionError("The original cannot be checked safely.") from exc
        if status == "deleted":
            journal.update_deletion(existing_id, "needs_attention", "A file appeared again at a path previously deleted.")
            raise DeletionError("A file now exists at a previously deleted path; it was left untouched.")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            journal.update_deletion(existing_id, "needs_attention", "Original is not a regular file.")
            raise DeletionError("The original is not a regular file; it was left untouched.")
        if (info.st_size, info.st_mtime_ns) != (receipt.source_size, receipt.source_mtime_ns):
            journal.update_deletion(existing_id, "needs_attention", "Original metadata changed after extraction.")
            raise DeletionError("The original changed after extraction; it was left untouched.")
        try:
            if _hash(source) != receipt.source_sha256:
                journal.update_deletion(existing_id, "needs_attention", "Original checksum changed after extraction.")
                raise DeletionError("The original contents changed after extraction; it was left untouched.")
        except OSError as exc:
            journal.update_deletion(existing_id, "needs_attention", "Original could not be fingerprinted.")
            raise DeletionError("The original could not be fingerprinted; it was left untouched.") from exc
        # Persist intent before unlink so an interruption can be reconciled.
        _verified_audio(receipt)
        journal.update_deletion(existing_id, "deleting")
        try:
            current = source.lstat()
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                    info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                journal.update_deletion(existing_id, "needs_attention", "Original was replaced before deletion.")
                raise DeletionError("The original was replaced while preparing deletion; it was left untouched.")
            source.unlink()
        except DeletionError:
            raise
        except OSError as exc:
            journal.update_deletion(existing_id, "needs_attention", "Original could not be deleted.")
            raise DeletionError("The verified original could not be deleted.") from exc
        journal.update_deletion(existing_id, "deleted")
        deleted.append(str(canonical_source))
    return DeletionResult(tuple(deleted), tuple(already))


def delete_verified_originals(receipts: tuple[OriginalDeletionReceipt, ...] | list[OriginalDeletionReceipt],
                              approved_source_paths: tuple[str | Path, ...] | list[str | Path],
                              journal: OperationJournal) -> DeletionResult:
    """Serialize deletion against any other prep or deletion operation."""
    with journal.exclusive():
        return _delete_verified_originals(receipts, approved_source_paths, journal)
