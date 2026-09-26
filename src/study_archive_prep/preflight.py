"""Read-only output preflight for copy and ZIP operations."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .project import ProjectState, StudyFile


@dataclass(frozen=True)
class PlannedCopy:
    file_id: str
    source_path: str
    destination: str
    size: int
    mtime_ns: int = 0


@dataclass(frozen=True)
class PlannedArchive:
    destination: str
    member_file_ids: tuple[str, ...]
    member_names: tuple[str, ...]
    uncompressed_size: int
    member_sources: tuple[PlannedCopy, ...] = ()


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str
    path: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class ProcessingPlan:
    output_path: str
    copies: tuple[PlannedCopy, ...]
    archives: tuple[PlannedArchive, ...]
    issues: tuple[PreflightIssue, ...]
    required_bytes: int
    available_bytes: int | None

    @property
    def can_execute(self) -> bool:
        return not any(issue.blocking for issue in self.issues)


def _safe_name(name: str) -> str:
    # Source names are preserved, but cannot introduce a path component.
    return Path(name).name.replace("/", "_").replace("\\", "_") or "unnamed"


def _unique_name(name: str, used: set[str]) -> str:
    candidate = name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while candidate.casefold() in used:
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    used.add(candidate.casefold())
    return candidate


def _week_directory(title: str, number: int) -> str:
    clean = " ".join(title.split()).strip(" .")
    return _safe_name(clean or f"Неделя {number}")


def _source_for(project: ProjectState, item: StudyFile) -> Path:
    roots = {root.id: Path(root.path) for root in project.roots}
    root = roots[item.source_root_id]
    return root.joinpath(*PurePosixPath(item.relative_path).parts)


def _free_bytes(path: Path) -> int | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def build_preflight(project: ProjectState) -> ProcessingPlan:
    """Calculate every destination and archive member without creating output."""
    output = Path(project.output_path).expanduser().resolve(strict=False)
    copies: list[PlannedCopy] = []
    archive_groups: dict[str, list[tuple[StudyFile, str]]] = {}
    issues: list[PreflightIssue] = []
    file_by_id = {item.id: item for item in project.files}
    block_by_id = {item.id: item for item in project.blocks}
    represented = {block.file_id for block in project.blocks if block.kind == "file"}
    for item in project.files:
        if item.included and item.id not in represented:
            issues.append(PreflightIssue("file_without_block", "An included file has no publication block.", item.name))
    for block in project.blocks:
        if block.kind != "file" or not block.included:
            continue
        item = file_by_id[block.file_id]
        if not item.included:
            continue
        parent = block_by_id.get(block.parent_id or "")
        if parent is None:
            issues.append(PreflightIssue("orphan_file_block", "A file block has no parent.", block.title))
            continue
        week = parent if parent.kind == "week" else block_by_id.get(parent.parent_id or "")
        if week is None or week.kind != "week":
            issues.append(PreflightIssue("invalid_week", "A file is not attached to a week.", block.title))
            continue
        week_children = [child for child in project.blocks if child.kind == "day" and child.parent_id == week.id]
        dates = sorted(child.study_date for child in week_children if child.study_date)
        week_number = _week_number_from_title(week.title, week.position + 1)
        week_name = _week_directory(week.title, week_number)
        source = _source_for(project, item)
        try:
            info = source.lstat()
            if source.is_symlink() or not source.is_file():
                raise OSError("not a regular file")
            if info.st_size != item.size or info.st_mtime_ns != item.mtime_ns:
                issues.append(PreflightIssue("source_changed", "The source changed after scanning; scan it again.", str(source)))
                continue
        except OSError:
            issues.append(PreflightIssue("source_unavailable", "The source file is unavailable.", str(source)))
            continue

        name = _safe_name(block.title)
        if parent.kind == "week":
            if item.category == "study_archive" and source.suffix.casefold() == ".zip":
                destination = f"{week_name}/{_unique_name(name, _siblings_used(copies, week_name))}"
                copies.append(PlannedCopy(item.id, str(source), destination, item.size, item.mtime_ns))
            else:
                archive_groups.setdefault(f"{week_name}/Неделя_{week_number:02d}_Материалы_на_неделю.zip", []).append((item, name))
            continue

        day = parent
        day_name = day.study_date or day.title
        base = f"{week_name}/{_safe_name(day_name)}"
        if item.category == "audio_video":
            folder = f"{base}/01_Аудио"
            relative = f"{folder}/{_unique_name(name, _siblings_used(copies, folder))}"
            copies.append(PlannedCopy(item.id, str(source), relative, item.size, item.mtime_ns))
        elif item.category == "subtitle":
            folder = f"{base}/02_Субтитры"
            relative = f"{folder}/{_unique_name(name, _siblings_used(copies, folder))}"
            copies.append(PlannedCopy(item.id, str(source), relative, item.size, item.mtime_ns))
        elif item.category in {"screenshot", "screenshot_archive"}:
            if item.category == "screenshot_archive" and source.suffix.casefold() == ".zip":
                relative = f"{base}/03_Скриншоты.zip"
                if any(copy.destination == relative for copy in copies):
                    relative = f"{base}/03_Скриншоты ({len([copy for copy in copies if copy.destination.startswith(base + '/03_Скриншоты')]) + 1}).zip"
                copies.append(PlannedCopy(item.id, str(source), relative, item.size, item.mtime_ns))
            else:
                archive_groups.setdefault(f"{base}/03_Скриншоты.zip", []).append((item, name))
        elif item.category == "extra_archive" and source.suffix.casefold() == ".zip":
            relative = f"{base}/04_Дополнительные_материалы.zip"
            if any(copy.destination.startswith(f"{base}/04_Дополнительные_материалы") for copy in copies):
                relative = f"{base}/04_Дополнительные_материалы ({len([copy for copy in copies if copy.destination.startswith(base + '/04_Дополнительные_материалы')]) + 1}).zip"
            copies.append(PlannedCopy(item.id, str(source), relative, item.size, item.mtime_ns))
        else:
            archive_groups.setdefault(f"{base}/04_Дополнительные_материалы.zip", []).append((item, name))

    archives: list[PlannedArchive] = []
    reserved = {copy.destination.casefold() for copy in copies}
    for destination, members in sorted(archive_groups.items()):
        if destination.casefold() in reserved:
            path = PurePosixPath(destination)
            destination = str(path.with_name(_unique_name(path.name, {
                PurePosixPath(copy.destination).name.casefold() for copy in copies
                if PurePosixPath(copy.destination).parent == path.parent
            })))
        reserved.add(destination.casefold())
        used: set[str] = set()
        names = tuple(_unique_name(_safe_name(name), used) for _, name in members)
        sources = tuple(PlannedCopy(item.id, str(_source_for(project, item)), member_name,
                                    item.size, item.mtime_ns)
                        for (item, _), member_name in zip(members, names))
        archives.append(PlannedArchive(destination, tuple(item.id for item, _ in members), names,
                                       sum(item.size for item, _ in members), sources))

    destinations = [copy.destination for copy in copies] + [archive.destination for archive in archives]
    destination_set: set[str] = set()
    for relative in destinations:
        folded = relative.casefold()
        if folded in destination_set:
            issues.append(PreflightIssue("destination_collision", "Multiple items target the same output path.", relative))
        destination_set.add(folded)
        target = (output / relative).resolve(strict=False)
        if output not in target.parents:
            issues.append(PreflightIssue("unsafe_destination", "A destination escapes the output folder.", relative))
        if target.exists():
            issues.append(PreflightIssue("output_exists", "The destination already exists; files are never overwritten.", relative))

    for root in project.roots:
        source_root = Path(root.path).resolve(strict=False)
        if output == source_root or output in source_root.parents or source_root in output.parents:
            issues.append(PreflightIssue("path_overlap", "Output and source folders cannot overlap.", str(source_root)))

    required = sum(copy.size for copy in copies) + sum(archive.uncompressed_size for archive in archives)
    required = int(required * 1.05) + 16 * 1024 * 1024 if copies or archives else 0
    available = _free_bytes(output)
    if available is not None and required > available:
        issues.append(PreflightIssue("insufficient_space", "The output may need more free space than is available.", str(output)))
    for file_id in sorted({item for archive in archives for item in archive.member_file_ids}):
        if file_id not in file_by_id:
            issues.append(PreflightIssue("missing_archive_member", "An archive references a missing source file.", file_id))
    return ProcessingPlan(str(output), tuple(copies), tuple(archives), tuple(issues), required, available)


def _siblings_used(copies: list[PlannedCopy], parent: str) -> set[str]:
    return {PurePosixPath(item.destination).name.casefold() for item in copies
            if item.destination.rpartition("/")[0] == parent.rstrip("/")}


def _week_number_from_title(title: str, fallback: int) -> int:
    import re
    match = re.search(r"(?:неделя|week|woche)\s*(\d+)", title, re.IGNORECASE)
    return int(match.group(1)) if match else fallback
