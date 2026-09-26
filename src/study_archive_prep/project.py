"""Versioned domain objects persisted by the project repository."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from datetime import date
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


def _parse_id(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID string") from exc
    if parsed != value.casefold():
        raise ValueError(f"{field} must use canonical UUID formatting")
    return parsed


def _nonempty(value: Any, field: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be a non-empty string up to {limit} characters")
    return value


@dataclass(frozen=True)
class SourceRoot:
    id: str
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _parse_id(self.id, "source root id"))
        path = _nonempty(self.path, "source root path")
        if not Path(path).is_absolute():
            raise ValueError("source root path must be absolute")
        object.__setattr__(self, "path", str(Path(path).expanduser().resolve(strict=False)))

    @classmethod
    def create(cls, path: Path | str) -> "SourceRoot":
        return cls(new_id(), str(Path(path).expanduser().resolve(strict=False)))


@dataclass(frozen=True)
class StudyFile:
    """A file within a source root; paths never escape through ``..``."""

    id: str
    source_root_id: str
    relative_path: str
    name: str
    size: int
    mtime_ns: int
    sha256: str | None = None
    study_date: str | None = None
    category: str = "unclassified"
    week_number: int | None = None
    included: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _parse_id(self.id, "file id"))
        object.__setattr__(self, "source_root_id", _parse_id(self.source_root_id, "source root id"))
        relative = _nonempty(self.relative_path, "relative path")
        path = PurePosixPath(relative)
        if "\x00" in relative or path.is_absolute() or ".." in path.parts or "\\" in relative or relative in {".", ".."}:
            raise ValueError("file path must be a safe relative POSIX path")
        if path.as_posix() != relative:
            raise ValueError("file path must use normalized POSIX separators")
        object.__setattr__(self, "relative_path", relative)
        object.__setattr__(self, "name", _nonempty(self.name, "file name", 1024))
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("file size must be a non-negative integer")
        if isinstance(self.mtime_ns, bool) or not isinstance(self.mtime_ns, int) or self.mtime_ns < 0:
            raise ValueError("file mtime must be a non-negative integer")
        if self.sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("SHA-256 must contain 64 lowercase hexadecimal characters")
        if self.study_date is not None:
            try:
                parsed = date.fromisoformat(self.study_date)
            except ValueError as exc:
                raise ValueError("study date must use YYYY-MM-DD format") from exc
            if parsed.isoformat() != self.study_date:
                raise ValueError("study date must use YYYY-MM-DD format")
        object.__setattr__(self, "category", _nonempty(self.category, "category", 80))
        if self.week_number is not None and (isinstance(self.week_number, bool) or
                                             not isinstance(self.week_number, int) or self.week_number < 1):
            raise ValueError("week number must be a positive integer")
        if not isinstance(self.included, bool):
            raise ValueError("included must be a boolean")

    @classmethod
    def create(cls, source_root_id: str, relative_path: str, name: str,
               size: int, mtime_ns: int, **values: Any) -> "StudyFile":
        return cls(new_id(), source_root_id, relative_path, name, size, mtime_ns, **values)


@dataclass(frozen=True)
class PublicationBlock:
    """Persistent week/day/file/text node for the ordered Telegram editor."""

    id: str
    kind: str
    title: str
    position: int
    parent_id: str | None = None
    study_date: str | None = None
    file_id: str | None = None
    text: str | None = None
    included: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _parse_id(self.id, "block id"))
        if self.kind not in {"week", "day", "file", "text"}:
            raise ValueError("block kind must be week, day, file, or text")
        object.__setattr__(self, "title", _nonempty(self.title, "block title", 4096))
        if isinstance(self.position, bool) or not isinstance(self.position, int) or self.position < 0:
            raise ValueError("block position must be a non-negative integer")
        if self.parent_id is not None:
            object.__setattr__(self, "parent_id", _parse_id(self.parent_id, "parent block id"))
        if self.study_date is not None:
            try:
                parsed = date.fromisoformat(self.study_date)
            except ValueError as exc:
                raise ValueError("block date must use YYYY-MM-DD format") from exc
            if parsed.isoformat() != self.study_date:
                raise ValueError("block date must use YYYY-MM-DD format")
        if self.file_id is not None:
            object.__setattr__(self, "file_id", _parse_id(self.file_id, "file id"))
        if self.text is not None and (not isinstance(self.text, str) or len(self.text) > 4096):
            raise ValueError("block text must be a string up to 4096 characters")
        if self.kind == "text" and not (self.text or "").strip():
            raise ValueError("text blocks require message text")
        if self.kind == "file" and self.file_id is None:
            raise ValueError("file blocks require a linked file id")
        if self.kind != "file" and self.file_id is not None:
            raise ValueError("only file blocks may link a file id")
        if not isinstance(self.included, bool):
            raise ValueError("included must be a boolean")

    @classmethod
    def create(cls, kind: str, title: str, position: int = 0, **values: Any) -> "PublicationBlock":
        return cls(new_id(), kind, title, position, **values)


@dataclass(frozen=True)
class ProjectState:
    id: str
    name: str
    output_path: str
    start_date: str | None
    roots: tuple[SourceRoot, ...] = ()
    files: tuple[StudyFile, ...] = ()
    blocks: tuple[PublicationBlock, ...] = ()
    revision: int = 0
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _parse_id(self.id, "project id"))
        object.__setattr__(self, "name", _nonempty(self.name, "project name", 256))
        output_path = _nonempty(self.output_path, "output path")
        if not Path(output_path).is_absolute():
            raise ValueError("output path must be absolute")
        output_path = Path(output_path).expanduser().resolve(strict=False)
        object.__setattr__(self, "output_path", str(output_path))
        if self.start_date is not None:
            try:
                parsed = date.fromisoformat(self.start_date)
            except ValueError as exc:
                raise ValueError("start date must use YYYY-MM-DD format") from exc
            if parsed.isoformat() != self.start_date:
                raise ValueError("start date must use YYYY-MM-DD format")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise ValueError("project revision must be a non-negative integer")
        if self.schema_version != 1:
            raise ValueError("unsupported project schema version")
        root_ids = [root.id for root in self.roots]
        if len(root_ids) != len(set(root_ids)):
            raise ValueError("source root IDs must be unique")
        root_paths = [str(Path(root.path).resolve(strict=False)) for root in self.roots]
        if len(root_paths) != len(set(root_paths)):
            raise ValueError("the same source folder cannot be added twice")
        for root in self.roots:
            source_path = Path(root.path).resolve(strict=False)
            if output_path == source_path or output_path in source_path.parents or source_path in output_path.parents:
                raise ValueError("project output and source folders cannot overlap")
        root_id_set = set(root_ids)
        file_ids = [item.id for item in self.files]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("file IDs must be unique")
        if any(item.source_root_id not in root_id_set for item in self.files):
            raise ValueError("every file must refer to an existing source root")
        if len({(item.source_root_id, item.relative_path) for item in self.files}) != len(self.files):
            raise ValueError("a physical relative path can occur only once per source root")
        block_ids = [item.id for item in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("publication block IDs must be unique")
        block_id_set = set(block_ids)
        file_id_set = set(file_ids)
        sibling_positions: set[tuple[str | None, int]] = set()
        for block in self.blocks:
            if block.parent_id is not None and block.parent_id not in block_id_set:
                raise ValueError("publication block parent does not exist")
            if block.file_id is not None and block.file_id not in file_id_set:
                raise ValueError("publication block file does not exist")
            if block.parent_id == block.id:
                raise ValueError("publication blocks cannot be their own parent")
            position = (block.parent_id, block.position)
            if position in sibling_positions:
                raise ValueError("sibling blocks must have distinct positions")
            sibling_positions.add(position)
            if block.kind == "week" and block.parent_id is not None:
                raise ValueError("week blocks cannot have a parent")
            if block.kind == "day" and block.study_date is None:
                raise ValueError("day blocks require an ISO study date")
            if block.kind == "day" and block.parent_id is None:
                raise ValueError("day blocks must belong to a week")
        block_map = {block.id: block for block in self.blocks}
        for block in self.blocks:
            visited: set[str] = set()
            current = block
            while current.parent_id is not None:
                if current.id in visited:
                    raise ValueError("publication block hierarchy cannot contain cycles")
                visited.add(current.id)
                current = block_map[current.parent_id]
            if block.parent_id is not None:
                parent = block_map[block.parent_id]
                if block.kind == "day" and parent.kind != "week":
                    raise ValueError("day blocks must belong to a week")
                if block.kind in {"file", "text"} and parent.kind not in {"day", "week"}:
                    raise ValueError("file and text blocks must belong to a week or day")

    @classmethod
    def create(cls, name: str, output_path: Path | str, start_date: str | None = None,
               roots: tuple[SourceRoot, ...] = ()) -> "ProjectState":
        return cls(new_id(), name, str(Path(output_path).expanduser().resolve(strict=False)),
                   start_date, roots=tuple(roots))

    def with_revision(self, revision: int) -> "ProjectState":
        return replace(self, revision=revision)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "output_path": self.output_path,
            "start_date": self.start_date,
            "revision": self.revision,
            "roots": [root.__dict__ for root in self.roots],
            "files": [item.__dict__ for item in self.files],
            "blocks": [block.__dict__ for block in self.blocks],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ProjectState":
        if not isinstance(data, dict):
            raise ValueError("saved project must be a JSON object")
        required = {"schema_version", "id", "name", "output_path", "start_date", "revision",
                    "roots", "files", "blocks"}
        if set(data) != required:
            raise ValueError("saved project fields do not match the supported schema")
        if data["schema_version"] != 1:
            raise ValueError("unsupported project schema version")
        if not all(isinstance(data[key], list) for key in ("roots", "files", "blocks")):
            raise ValueError("saved project collections must be arrays")
        try:
            roots = tuple(SourceRoot(**value) for value in data["roots"])
            files = tuple(StudyFile(**value) for value in data["files"])
            blocks = tuple(PublicationBlock(**value) for value in data["blocks"])
        except (TypeError, KeyError) as exc:
            raise ValueError("saved project contains an invalid item") from exc
        return cls(data["id"], data["name"], data["output_path"], data["start_date"],
                   roots=roots, files=files, blocks=blocks, revision=data["revision"],
                   schema_version=data["schema_version"])
