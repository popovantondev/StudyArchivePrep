"""Private durable operation journal and crash-safe plan resumption."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator

from .preflight import PlannedArchive, PlannedCopy, ProcessingPlan
from .processor import (CompletedOutput, OperationCancelled, ProcessingError,
                        ProcessingResult, execute_processing_plan)

DATABASE_VERSION = 1
_JOURNAL_NAMESPACE = uuid.UUID("cb1b7e7b-31b4-4d06-9e15-2e4a6b585376")


class JournalError(RuntimeError):
    """A saved operation record is damaged or cannot be updated safely."""


@dataclass(frozen=True)
class OperationEntry:
    id: str
    plan_id: str
    kind: str
    destination: str
    sources: tuple[PlannedCopy, ...]
    member_names: tuple[str, ...]
    temp_path: str | None
    status: str
    output_size: int | None
    output_sha256: str | None
    error: str | None


@dataclass(frozen=True)
class JournaledResult:
    plan_id: str
    outputs: tuple[CompletedOutput, ...]
    skipped_completed: tuple[str, ...]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_signature(value: PlannedCopy) -> dict:
    return {"file_id": value.file_id, "source_path": value.source_path,
            "size": value.size, "mtime_ns": value.mtime_ns, "member_name": value.destination}


class OperationJournal:
    """Owner-only SQLite journal with optimistic fail-closed schema checks."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).expanduser()
        self.lock_path = self.database_path.with_suffix(self.database_path.suffix + ".lock")

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database_path.parent.chmod(0o700)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _connect(self) -> sqlite3.Connection:
        path = self.database_path
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.parent.chmod(0o700)
            if path.is_symlink():
                raise JournalError("The operation journal must not be a symbolic link.")
            if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
                raise JournalError("The operation journal must be a regular file.")
            connection = sqlite3.connect(path, timeout=10.0, isolation_level=None)
            path.chmod(0o600)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > DATABASE_VERSION:
                raise JournalError("The operation journal was created by a newer app version.")
            if version == 0:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE plans (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, digest TEXT NOT NULL, output_path TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
                connection.execute("CREATE TABLE operations (id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id), kind TEXT NOT NULL, destination TEXT NOT NULL, sources_json TEXT NOT NULL, member_names_json TEXT NOT NULL, temp_path TEXT, status TEXT NOT NULL, output_size INTEGER, output_sha256 TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(plan_id, destination))")
                connection.execute("CREATE TABLE IF NOT EXISTS deletions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_file_id TEXT NOT NULL, source_path TEXT NOT NULL, source_size INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL, source_sha256 TEXT NOT NULL, audio_path TEXT NOT NULL, audio_size INTEGER NOT NULL, audio_sha256 TEXT NOT NULL, container_exports_complete INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
                connection.execute("PRAGMA user_version = 1")
                connection.execute("COMMIT")
            elif version != DATABASE_VERSION:
                raise JournalError("The operation journal has no supported migration.")
            else:
                connection.execute("CREATE TABLE IF NOT EXISTS deletions (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_file_id TEXT NOT NULL, source_path TEXT NOT NULL, source_size INTEGER NOT NULL, source_mtime_ns INTEGER NOT NULL, source_sha256 TEXT NOT NULL, audio_path TEXT NOT NULL, audio_size INTEGER NOT NULL, audio_sha256 TEXT NOT NULL, container_exports_complete INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            return connection
        except JournalError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise JournalError("Could not safely open the private operation journal.") from exc

    @staticmethod
    def _plan_data(plan: ProcessingPlan) -> dict:
        return {
            "output_path": str(Path(plan.output_path).resolve(strict=False)),
            "copies": [{"kind": "copy", "destination": item.destination,
                        "sources": [_source_signature(item)]} for item in plan.copies],
            "archives": [{"kind": "archive", "destination": item.destination,
                          "member_names": list(item.member_names),
                          "sources": [_source_signature(member) for member in item.member_sources]}
                         for item in plan.archives],
        }

    def prepare(self, project_id: str, plan: ProcessingPlan) -> str:
        try:
            namespace = uuid.UUID(project_id)
        except (ValueError, AttributeError) as exc:
            raise JournalError("A valid project ID is required for operation history.") from exc
        payload = self._plan_data(plan)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        plan_id = str(uuid.uuid5(namespace, digest))
        now = _timestamp()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT digest FROM plans WHERE id = ?", (plan_id,)).fetchone()
            if old is None:
                connection.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
                                   (plan_id, project_id, digest, payload["output_path"], now, now))
            elif old[0] != digest:
                raise JournalError("The saved plan ID points to different operation data.")
            for item in payload["copies"] + payload["archives"]:
                entry_id = str(uuid.uuid5(uuid.UUID(plan_id), f"{item['kind']}:{item['destination']}"))
                sources_json = json.dumps(item["sources"], ensure_ascii=False,
                                          sort_keys=True, separators=(",", ":"))
                names_json = json.dumps(item.get("member_names", []), ensure_ascii=False)
                connection.execute(
                    "INSERT OR IGNORE INTO operations(id, plan_id, kind, destination, sources_json, member_names_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (entry_id, plan_id, item["kind"], item["destination"], sources_json,
                     names_json, now, now))
            connection.execute("UPDATE plans SET updated_at = ? WHERE id = ?", (now, plan_id))
            connection.execute("COMMIT")
            return plan_id
        except JournalError:
            connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise JournalError("Could not save the operation plan.") from exc
        finally:
            connection.close()

    def entries(self, plan_id: str) -> tuple[OperationEntry, ...]:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM operations WHERE plan_id = ? ORDER BY created_at, destination",
                                      (plan_id,)).fetchall()
            return tuple(OperationEntry(
                row["id"], row["plan_id"], row["kind"], row["destination"],
                tuple(PlannedCopy(value["file_id"], value["source_path"],
                                  value["member_name"], value["size"], value["mtime_ns"])
                      for value in json.loads(row["sources_json"])),
                tuple(json.loads(row["member_names_json"])), row["temp_path"], row["status"],
                row["output_size"], row["output_sha256"], row["error"],
            ) for row in rows)
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise JournalError("An operation record is damaged.") from exc
        finally:
            connection.close()

    def update(self, entry_id: str, status: str, *, temp_path: str | None = None,
               output: CompletedOutput | None = None, error: str | None = None) -> None:
        if status not in {"pending", "in_progress", "completed", "failed", "interrupted", "needs_attention"}:
            raise ValueError("unsupported operation status")
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE operations SET status = ?, temp_path = ?, output_size = ?, output_sha256 = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, temp_path,
                 output.size if output else None,
                 output.sha256 if output else None,
                 error[:2000] if error else None, _timestamp(), entry_id))
            if cursor.rowcount != 1:
                raise JournalError("The operation record was not found.")
        except sqlite3.Error as exc:
            raise JournalError("Could not update the operation journal.") from exc
        finally:
            connection.close()

    def record_deletion_receipt(self, receipt) -> str:
        project_id = receipt.project_id
        try:
            namespace = uuid.UUID(project_id)
        except (ValueError, AttributeError) as exc:
            raise JournalError("A valid project ID is required for deletion history.") from exc
        key = f"{receipt.source_path}\0{receipt.source_sha256}\0{receipt.audio_path}\0{receipt.audio_sha256}"
        record_id = str(uuid.uuid5(namespace, key))
        now = _timestamp()
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR IGNORE INTO deletions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', NULL, ?, ?)",
                (record_id, project_id, receipt.source_file_id, receipt.source_path,
                 receipt.source_size, receipt.source_mtime_ns, receipt.source_sha256,
                 receipt.audio_path, receipt.audio_size, receipt.audio_sha256,
                 int(receipt.container_exports_complete), now, now))
            return record_id
        except sqlite3.Error as exc:
            raise JournalError("Could not save the verified deletion receipt.") from exc
        finally:
            connection.close()

    def deletion_status(self, record_id: str) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT status FROM deletions WHERE id = ?", (record_id,)).fetchone()
            return row[0] if row else None
        finally:
            connection.close()

    def update_deletion(self, record_id: str, status: str, error: str | None = None) -> None:
        if status not in {"ready", "deleting", "deleted", "needs_attention"}:
            raise ValueError("unsupported deletion status")
        connection = self._connect()
        try:
            cursor = connection.execute("UPDATE deletions SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                                        (status, error[:2000] if error else None, _timestamp(), record_id))
            if cursor.rowcount != 1:
                raise JournalError("The deletion receipt was not found.")
        except sqlite3.Error as exc:
            raise JournalError("Could not update the deletion journal.") from exc
        finally:
            connection.close()


def _verify_source(source: PlannedCopy) -> tuple[int, str]:
    path = Path(source.source_path)
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file() or (info.st_size, info.st_mtime_ns) != (source.size, source.mtime_ns):
            raise JournalError(f"The source changed; it needs a new scan: {path.name}")
        return info.st_size, _sha256(path)
    except OSError as exc:
        raise JournalError(f"The source is unavailable: {path.name}") from exc


def _output_path(plan: ProcessingPlan, destination: str) -> Path:
    root = Path(plan.output_path).resolve(strict=False)
    relative = PurePosixPath(destination)
    if relative.is_absolute() or ".." in relative.parts:
        raise JournalError("The saved operation path is unsafe.")
    path = root.joinpath(*relative.parts)
    resolved = path.resolve(strict=False)
    if resolved == root or root not in resolved.parents:
        raise JournalError("The output path escapes the prepared folder.")
    return path


def _recover_or_verify(entry: OperationEntry, plan: ProcessingPlan, journal: OperationJournal) -> bool:
    output = _output_path(plan, entry.destination)
    if not output.exists():
        if entry.temp_path:
            temporary = Path(entry.temp_path)
            root = Path(plan.output_path).resolve(strict=False)
            resolved = temporary.resolve(strict=False)
            if (temporary.name.startswith(".study-archive-prep-") and
                    (resolved == root or root in resolved.parents)):
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    journal.update(entry.id, "needs_attention", temp_path=entry.temp_path,
                                   error="An incomplete temporary output could not be removed.")
                    raise JournalError("An incomplete temporary output needs manual review.") from exc
        journal.update(entry.id, "pending")
        return False
    if not output.is_file() or output.is_symlink():
        journal.update(entry.id, "needs_attention", error="Output is not a regular file.")
        raise JournalError("A journaled output is not a regular file; review it manually.")
    if entry.kind == "copy":
        if len(entry.sources) != 1:
            raise JournalError("A copy journal entry has invalid source data.")
        expected_size, expected_digest = _verify_source(entry.sources[0])
        valid = output.stat().st_size == expected_size and _sha256(output) == expected_digest
        file_ids = (entry.sources[0].file_id,)
    else:
        if len(entry.sources) != len(entry.member_names):
            raise JournalError("An archive journal entry has invalid member data.")
        file_ids = tuple(source.file_id for source in entry.sources)
        valid = False
        try:
            with zipfile.ZipFile(output) as zipped:
                infos = zipped.infolist()
                if zipped.testzip() is None and zipped.namelist() == list(entry.member_names):
                    valid = True
                    for info, source in zip(infos, entry.sources):
                        expected_size, expected_digest = _verify_source(source)
                        if info.file_size != expected_size:
                            valid = False
                            break
                        digest = hashlib.sha256()
                        with zipped.open(info) as member:
                            while chunk := member.read(1024 * 1024):
                                digest.update(chunk)
                        if digest.hexdigest() != expected_digest:
                            valid = False
                            break
        except (OSError, zipfile.BadZipFile, RuntimeError):
            valid = False
    if not valid:
        journal.update(entry.id, "needs_attention", error="Output does not match the saved operation snapshot.")
        raise JournalError("An existing output does not match its saved operation; it was left untouched.")
    receipt = CompletedOutput(entry.kind, str(output), output.stat().st_size, _sha256(output), file_ids)
    if entry.status != "completed":
        journal.update(entry.id, "completed", output=receipt)
    elif entry.output_size != receipt.size or entry.output_sha256 != receipt.sha256:
        journal.update(entry.id, "needs_attention", error="The completed output changed after verification.")
        raise JournalError("A completed output changed after processing; it was left untouched.")
    return True


def _run_journaled_plan(project_id: str, plan: ProcessingPlan, journal: OperationJournal,
                        cancelled: Callable[[], bool] | None = None,
                        progress: Callable[[int, int, str], None] | None = None) -> JournaledResult:
    """Resume one immutable plan, verifying every completed file before skipping it."""
    plan_id = journal.prepare(project_id, plan)
    entries = journal.entries(plan_id)
    by_destination = {entry.destination: entry for entry in entries}
    planned_destinations = {item.destination for item in (*plan.copies, *plan.archives)}
    if set(by_destination) != planned_destinations:
        raise JournalError("The journal does not match the current immutable plan.")
    non_output_blockers = [issue for issue in plan.issues
                           if issue.blocking and issue.code != "output_exists"]
    if non_output_blockers:
        raise ProcessingError(f"Preflight has a blocking issue: {non_output_blockers[0].message}")
    outputs: list[CompletedOutput] = []
    skipped: list[str] = []
    total = len(planned_destinations)
    done = 0
    root = Path(plan.output_path).resolve(strict=False)
    for item in (*plan.copies, *plan.archives):
        entry = by_destination[item.destination]
        target = _output_path(plan, item.destination)
        if entry.status in {"completed", "in_progress", "interrupted"} or entry.status == "failed" and target.exists():
            if _recover_or_verify(entry, plan, journal):
                skipped.append(item.destination)
                done += 1
                if progress is not None:
                    progress(done, total, item.destination)
                continue
        elif entry.status == "needs_attention":
            raise JournalError(f"This output needs manual review: {item.destination}")
        elif target.exists():
            journal.update(entry.id, "needs_attention", error="An output exists without a completed matching journal entry.")
            raise JournalError(f"An untracked output already exists: {item.destination}")

        journal.update(entry.id, "pending")
        current_temp: str | None = None

        def hook(event: str, destination: str, temp_path: str | None,
                 result: CompletedOutput | None) -> None:
            nonlocal current_temp
            if event == "started":
                journal.update(entry.id, "in_progress")
            elif event == "temporary":
                current_temp = temp_path
                journal.update(entry.id, "in_progress", temp_path=temp_path)
            elif event == "completed" and result is not None:
                journal.update(entry.id, "completed", output=result)

        single = ProcessingPlan(
            str(root), (item,) if isinstance(item, PlannedCopy) else (),
            (item,) if isinstance(item, PlannedArchive) else (), (),
            item.size if isinstance(item, PlannedCopy) else item.uncompressed_size,
            plan.available_bytes,
        )
        try:
            result = execute_processing_plan(single, cancelled=cancelled, operation_hook=hook)
        except OperationCancelled as exc:
            journal.update(entry.id, "interrupted", temp_path=current_temp, error=str(exc))
            raise
        except (ProcessingError, OSError, JournalError) as exc:
            journal.update(entry.id, "failed", temp_path=current_temp, error=str(exc))
            raise
        if len(result.outputs) != 1:
            journal.update(entry.id, "needs_attention", error="The operation returned an unexpected output count.")
            raise JournalError("The operation could not be confirmed.")
        outputs.extend(result.outputs)
        done += 1
        if progress is not None:
            progress(done, total, item.destination)
    return JournaledResult(plan_id, tuple(outputs), tuple(skipped))


def run_journaled_plan(project_id: str, plan: ProcessingPlan, journal: OperationJournal,
                       cancelled: Callable[[], bool] | None = None,
                       progress: Callable[[int, int, str], None] | None = None) -> JournaledResult:
    """Serialize processing per journal file to avoid competing writers."""
    with journal.exclusive():
        return _run_journaled_plan(project_id, plan, journal, cancelled, progress)
