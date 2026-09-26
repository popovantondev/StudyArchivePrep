"""Export a verified, ordered publication manifest for TelegramMediaSender."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .preflight import ProcessingPlan, build_preflight
from .project import ProjectState, PublicationBlock

FORMAT = "study-archive-publication-plan"
SCHEMA_VERSION = 1
_ITEM_NAMESPACE = "1e353ed8-2ec6-4f66-94f7-da5e09bb8e60"


class PublicationManifestError(ValueError):
    """The project cannot be represented as a safe publication manifest."""


def _item_id(project_id: str, stable_key: str) -> str:
    namespace = uuid.uuid5(uuid.UUID(project_id), _ITEM_NAMESPACE)
    return str(uuid.uuid5(namespace, stable_key))


def _ordered_children(blocks: dict[str, PublicationBlock], parent_id: str | None) -> list[PublicationBlock]:
    return sorted((block for block in blocks.values() if block.parent_id == parent_id),
                  key=lambda block: (block.position, block.id))


def _sha256(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise PublicationManifestError("a prepared output changed while its hash was calculated")
    return digest.hexdigest()


def build_publication_manifest(project: ProjectState, plan_revision: int,
                               processing_plan: ProcessingPlan | None = None) -> dict[str, Any]:
    """Build manifest only from completed, verified output files.

    No source paths, local journal information, subtitle contents, or secrets are
    serialized. Relative paths, byte sizes, and SHA-256 values bind each entry to
    the exact prepared result.
    """
    if isinstance(plan_revision, bool) or not isinstance(plan_revision, int) or plan_revision < 1:
        raise PublicationManifestError("plan_revision must be a positive integer")
    processing_plan = processing_plan or build_preflight(project)
    blocking = [issue for issue in processing_plan.issues if issue.blocking]
    if blocking:
        raise PublicationManifestError("the project has blocking output issues")
    root = Path(processing_plan.output_path).expanduser().resolve(strict=True)
    copies = {item.file_id: item.destination for item in processing_plan.copies}
    archive_for_file: dict[str, str] = {}
    for archive in processing_plan.archives:
        for file_id in archive.member_file_ids:
            if file_id in archive_for_file:
                raise PublicationManifestError("a source file appears in multiple output archives")
            archive_for_file[file_id] = archive.destination

    blocks = {block.id: block for block in project.blocks}
    files = {item.id: item for item in project.files}
    entries: list[dict[str, Any]] = []
    emitted_archive: set[str] = set()

    def text_entry(block: PublicationBlock, week_number: int, study_date: str | None = None) -> None:
        if not block.included:
            return
        text = block.text if block.kind == "text" else block.title
        if not isinstance(text, str) or not text.strip():
            raise PublicationManifestError("a publication text block is empty")
        entries.append({"id": block.id, "kind": "text", "week": week_number,
                        "date": study_date, "text": text})

    def file_entry(block: PublicationBlock, week_number: int,
                   study_date: str | None) -> None:
        if not block.included:
            return
        file_id = block.file_id
        if file_id not in files or not files[file_id].included:
            return
        if file_id in copies:
            relative = copies[file_id]
            item_id = block.id
        elif file_id in archive_for_file:
            relative = archive_for_file[file_id]
            if relative in emitted_archive:
                return
            emitted_archive.add(relative)
            item_id = _item_id(project.id, f"archive:{relative}")
        else:
            raise PublicationManifestError("an included file has no prepared output")
        posix = PurePosixPath(relative)
        if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
            raise PublicationManifestError("an output path is not a safe relative path")
        path = root.joinpath(*posix.parts)
        try:
            resolved = path.resolve(strict=True)
            if root not in resolved.parents:
                raise PublicationManifestError("a prepared output escapes the output folder")
            info = path.lstat()
        except OSError as exc:
            raise PublicationManifestError(f"a prepared output is missing: {relative}") from exc
        if path.is_symlink() or not path.is_file():
            raise PublicationManifestError(f"a prepared output is not a regular file: {relative}")
        entries.append({"id": item_id, "kind": "file", "week": week_number,
                        "date": study_date, "path": posix.as_posix(),
                        "name": posix.name, "size": info.st_size, "sha256": _sha256(path)})

    weeks = _ordered_children(blocks, None)
    for week in weeks:
        if week.kind != "week" or not week.included:
            continue
        match = re.search(r"(?:неделя|week|woche)\s*(\d+)", week.title, re.IGNORECASE)
        week_number = int(match.group(1)) if match else week.position + 1
        text_entry(week, week_number)
        for child in _ordered_children(blocks, week.id):
            if child.kind == "file":
                file_entry(child, week_number)
            elif child.kind == "text":
                text_entry(child, week_number)
            elif child.kind == "day" and child.included:
                text_entry(child, week_number, child.study_date)
                for day_child in _ordered_children(blocks, child.id):
                    if day_child.kind == "file":
                        file_entry(day_child, week_number, child.study_date)
                    elif day_child.kind == "text":
                        text_entry(day_child, week_number, child.study_date)

    manifest: dict[str, Any] = {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "project_id": project.id,
        "revision": plan_revision,
        "items": entries,
    }
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise PublicationManifestError("publication item IDs must be unique")
    return manifest


def serialize_publication_manifest(manifest: dict[str, Any]) -> bytes:
    """Serialize deterministic UTF-8 JSON with a final newline."""
    if (manifest.get("format") != FORMAT or manifest.get("schema_version") != SCHEMA_VERSION or
            not isinstance(manifest.get("items"), list)):
        raise PublicationManifestError("unsupported publication manifest")
    try:
        return (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicationManifestError("publication manifest is not valid JSON data") from exc


def write_publication_manifest(project: ProjectState, plan_revision: int,
                               processing_plan: ProcessingPlan | None = None,
                               destination: str | Path | None = None) -> Path:
    """Atomically write the plan without replacing any existing file."""
    processing_plan = processing_plan or build_preflight(project)
    root = Path(processing_plan.output_path).expanduser().resolve(strict=True)
    target = Path(destination) if destination is not None else root / "publication-plan.json"
    target = target.expanduser()
    if not target.is_absolute():
        target = root / target
    if target.is_symlink():
        raise PublicationManifestError("publication plan path must not be a symbolic link")
    target = target.resolve(strict=False)
    if target.parent != root:
        raise PublicationManifestError("publication plan must be saved at the output root")
    if target.exists() or target.is_symlink():
        raise FileExistsError("refusing to overwrite an existing publication plan")
    data = serialize_publication_manifest(
        build_publication_manifest(project, plan_revision, processing_plan))
    descriptor, temporary_name = tempfile.mkstemp(prefix=".publication-plan-", suffix=".tmp", dir=root)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        return target
    except FileExistsError:
        raise FileExistsError("refusing to overwrite an existing publication plan")
    except OSError as exc:
        raise PublicationManifestError("publication plan could not be written safely") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
