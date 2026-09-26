"""Atomic, sequential material copying and ZIP creation."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .preflight import ProcessingPlan, PlannedArchive, PlannedCopy


class ProcessingError(RuntimeError):
    """An operation failed safely; completed outputs remain valid."""


class OperationCancelled(ProcessingError):
    """The user cancelled the current operation."""

    def __init__(self, message: str, completed: list[CompletedOutput] | tuple[CompletedOutput, ...] = ()):
        super().__init__(message)
        self.completed = tuple(completed)


@dataclass(frozen=True)
class CompletedOutput:
    kind: str
    path: str
    size: int
    sha256: str
    source_file_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProcessingResult:
    outputs: tuple[CompletedOutput, ...]
    cancelled: bool = False


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _check_cancel(cancelled: Callable[[], bool] | None,
                  completed: list[CompletedOutput]) -> None:
    if cancelled is not None and cancelled():
        raise OperationCancelled("Operation cancelled.", completed)


def _ensure_directory(path: Path) -> None:
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ProcessingError(f"Output directory is not a safe folder: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ProcessingError(f"Output directory changed while preparing: {path}")


def _verify_source(path: Path, expected_size: int, expected_mtime_ns: int) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProcessingError(f"Source is unavailable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ProcessingError(f"Source is not a regular file: {path}")
    if info.st_size != expected_size or info.st_mtime_ns != expected_mtime_ns:
        raise ProcessingError(f"Source changed after the plan was built: {path}")
    return info


def _safe_destination(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise ProcessingError("An output path is not a safe relative path.")
    destination = root.joinpath(*posix.parts)
    resolved = destination.resolve(strict=False)
    if resolved == root or root not in resolved.parents:
        raise ProcessingError("An output path escapes the selected destination folder.")
    return destination


def _temporary_file(parent: Path) -> tuple[int, Path]:
    try:
        fd, name = tempfile.mkstemp(prefix=".study-archive-prep-", suffix=".tmp", dir=parent)
        return fd, Path(name)
    except OSError as exc:
        raise ProcessingError(f"Could not create a temporary file in {parent}.") from exc


def _install_without_overwrite(temp_path: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ProcessingError(f"Refusing to overwrite an existing output: {destination}")
    try:
        os.link(temp_path, destination)
        temp_path.unlink()
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise ProcessingError(f"An output appeared during processing; it was not overwritten: {destination}") from exc
    except OSError as exc:
        raise ProcessingError(f"Could not safely install output: {destination}") from exc


def _copy_one(root: Path, item: PlannedCopy, cancel: Callable[[], bool] | None,
              completed: list[CompletedOutput], operation_hook=None) -> CompletedOutput:
    source = Path(item.source_path)
    destination = _safe_destination(root, item.destination)
    _ensure_directory(destination.parent)
    before = _verify_source(source, item.size, item.mtime_ns)
    fd, temp_path = _temporary_file(destination.parent)
    if operation_hook is not None:
        operation_hook("temporary", item.destination, str(temp_path), None)
    source_digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_stream:
            while True:
                _check_cancel(cancel, completed)
                chunk = input_stream.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                source_digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = _verify_source(source, before.st_size, before.st_mtime_ns)
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ProcessingError(f"Source changed while copying: {source}")
        if temp_path.stat().st_size != before.st_size or _digest_file(temp_path) != source_digest.hexdigest():
            raise ProcessingError(f"The copy could not be verified: {destination}")
        _check_cancel(cancel, completed)
        _install_without_overwrite(temp_path, destination)
        return CompletedOutput("copy", str(destination), destination.stat().st_size,
                               source_digest.hexdigest(), (item.file_id,))
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _archive_one(root: Path, archive: PlannedArchive,
                 cancel: Callable[[], bool] | None,
                 completed: list[CompletedOutput], operation_hook=None) -> CompletedOutput:
    destination = _safe_destination(root, archive.destination)
    _ensure_directory(destination.parent)
    fd, temp_path = _temporary_file(destination.parent)
    os.close(fd)
    if operation_hook is not None:
        operation_hook("temporary", archive.destination, str(temp_path), None)
    expected_names = list(archive.member_names)
    if (len(expected_names) != len(archive.member_file_ids)
            or len(archive.member_sources) != len(archive.member_file_ids)):
        raise ProcessingError(f"Archive plan has mismatched member lists: {archive.destination}")
    source_digests: list[str] = []
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as zipped:
            for file_id, member_name, item in zip(archive.member_file_ids, expected_names,
                                                  archive.member_sources):
                _check_cancel(cancel, completed)
                if item.file_id != file_id:
                    raise ProcessingError(f"Archive source is missing from the plan: {file_id}")
                source = Path(item.source_path)
                before = _verify_source(source, item.size, item.mtime_ns)
                name_path = PurePosixPath(member_name)
                if name_path.is_absolute() or ".." in name_path.parts or len(name_path.parts) != 1:
                    raise ProcessingError(f"Archive member name is unsafe: {member_name}")
                digest = hashlib.sha256()
                info = zipfile.ZipInfo(member_name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                with source.open("rb") as input_stream, zipped.open(info, "w") as output:
                    while True:
                        _check_cancel(cancel, completed)
                        chunk = input_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                after = _verify_source(source, before.st_size, before.st_mtime_ns)
                if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                    raise ProcessingError(f"Source changed while archiving: {source}")
                source_digests.append(digest.hexdigest())
        _check_cancel(cancel, completed)
        with zipfile.ZipFile(temp_path, "r") as zipped:
            if zipped.testzip() is not None or zipped.namelist() != expected_names:
                raise ProcessingError(f"The archive could not be verified: {destination}")
            if sum(info.file_size for info in zipped.infolist()) != archive.uncompressed_size:
                raise ProcessingError(f"The archive size does not match its preview: {destination}")
            for info, expected_digest in zip(zipped.infolist(), source_digests):
                digest = hashlib.sha256()
                with zipped.open(info, "r") as member:
                    while chunk := member.read(1024 * 1024):
                        digest.update(chunk)
                if digest.hexdigest() != expected_digest:
                    raise ProcessingError(f"An archive member differs from its source: {info.filename}")
        archive_digest = _digest_file(temp_path)
        _install_without_overwrite(temp_path, destination)
        return CompletedOutput("archive", str(destination), destination.stat().st_size,
                               archive_digest, archive.member_file_ids)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def execute_processing_plan(plan: ProcessingPlan,
                            cancelled: Callable[[], bool] | None = None,
                            progress: Callable[[int, int, str], None] | None = None,
                            operation_hook=None) -> ProcessingResult:
    """Execute one preflight snapshot sequentially; never overwrite outputs."""
    if not plan.can_execute:
        blocking = next(issue for issue in plan.issues if issue.blocking)
        raise ProcessingError(f"Preflight has a blocking issue: {blocking.message}")
    root = Path(plan.output_path).expanduser().resolve(strict=False)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ProcessingError("The selected output path is not a safe directory.")
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    available = shutil.disk_usage(probe).free
    if plan.required_bytes > available:
        raise ProcessingError("There is not enough free space to safely execute the plan.")
    _ensure_directory(root)

    total = len(plan.copies) + len(plan.archives)
    done = 0
    completed: list[CompletedOutput] = []
    try:
        for item in plan.copies:
            _check_cancel(cancelled, completed)
            if operation_hook is not None:
                operation_hook("started", item.destination, None, None)
            result = _copy_one(root, item, cancelled, completed, operation_hook)
            completed.append(result)
            if operation_hook is not None:
                operation_hook("completed", item.destination, None, result)
            done += 1
            if progress is not None:
                progress(done, total, result.path)
        for archive in plan.archives:
            _check_cancel(cancelled, completed)
            if operation_hook is not None:
                operation_hook("started", archive.destination, None, None)
            result = _archive_one(root, archive, cancelled, completed, operation_hook)
            completed.append(result)
            if operation_hook is not None:
                operation_hook("completed", archive.destination, None, result)
            done += 1
            if progress is not None:
                progress(done, total, result.path)
    except OperationCancelled as exc:
        raise OperationCancelled(str(exc), completed) from exc
    return ProcessingResult(tuple(completed))
