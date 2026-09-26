"""Read-only, deterministic scanning and conservative date suggestions."""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .project import SourceRoot, StudyFile

_WEEK_PATTERNS = (
    re.compile(r"^(?:неделя|woche|week)[\s_-]*(\d+)\b", re.IGNORECASE),
    re.compile(r"^(\d+)[\s_-]*(?:неделя|woche|week)\b", re.IGNORECASE),
)
_YEAR_FIRST = re.compile(r"(?<!\d)(20\d{2})([-_. ])(0?[1-9]|1[0-2])\2(0?[1-9]|[12]\d|3[01])(?!\d)")
_DAY_FIRST_FULL = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])([-_. ])(0?[1-9]|1[0-2])\2(20\d{2})(?!\d)")
_DAY_MONTH = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])[-_. ](0?[1-9]|1[0-2])(?![-_. ]?\d)")
_DAY_MONTH_NAME = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])\s*[-_. ]*([a-zа-яäöü]+)(?![a-zа-яäöü])", re.IGNORECASE)
_TRANSCRIPT_CUE = re.compile(r"(?m)^\s*\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3}\s*-->\s*")
_ROOT_ID_NAMESPACE = uuid.UUID("a7a8d583-ff30-4b8c-80b4-636c175568cc")
_SYSTEM_NAMES = {".ds_store", "__macosx"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".tif", ".tiff"}
_MEDIA_SUFFIXES = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi",
    ".m4a", ".mp3", ".aac", ".ogg", ".opus", ".wav", ".flac",
}
_MONTHS = {
    "jan": 1, "january": 1, "januar": 1, "янв": 1, "январь": 1,
    "feb": 2, "february": 2, "februar": 2, "фев": 2, "февраль": 2,
    "mar": 3, "march": 3, "märz": 3, "maerz": 3, "мар": 3, "март": 3,
    "apr": 4, "april": 4, "апр": 4, "апрель": 4,
    "may": 5, "mai": 5, "май": 5,
    "jun": 6, "june": 6, "juni": 6, "июн": 6, "июнь": 6,
    "jul": 7, "july": 7, "juli": 7, "июл": 7, "июль": 7,
    "aug": 8, "august": 8, "авг": 8, "август": 8,
    "sep": 9, "sept": 9, "september": 9, "сент": 9, "сентябрь": 9,
    "oct": 10, "october": 10, "okt": 10, "oktober": 10, "окт": 10, "октябрь": 10,
    "nov": 11, "november": 11, "нояб": 11, "ноябрь": 11,
    "dec": 12, "december": 12, "dez": 12, "dezember": 12, "дек": 12, "декабрь": 12,
}


@dataclass(frozen=True)
class DateCandidate:
    study_date: str
    source: str
    confidence: str
    component: str


@dataclass(frozen=True)
class DateSuggestion:
    study_date: str | None
    candidates: tuple[DateCandidate, ...]
    needs_review: bool
    reason: str = ""


@dataclass(frozen=True)
class ScanIssue:
    code: str
    path: str
    message: str
    blocking: bool = False
    file_id: str | None = None


@dataclass(frozen=True)
class ScanResult:
    roots: tuple[SourceRoot, ...]
    files: tuple[StudyFile, ...]
    issues: tuple[ScanIssue, ...]
    excluded_paths: tuple[str, ...]


def _natural_key(value: str) -> tuple:
    normalized = unicodedata.normalize("NFC", value).casefold()
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", normalized))


def _week_numbers(components: tuple[str, ...]) -> list[int]:
    found: list[int] = []
    for component in components:
        for pattern in _WEEK_PATTERNS:
            match = pattern.search(component.strip())
            if match:
                found.append(int(match.group(1)))
                break
    return sorted(set(found))


def _matches_in_component(component: str, year_hint: int | None) -> list[DateCandidate]:
    # Week label ranges describe a group, not a specific file date. The contained
    # dated directory or filename provides the exact date for its files.
    if re.search(r"(?:неделя|woche|week)\s*\d+.*\d{1,2}[._]\d{1,2}\s*[-–]\s*\d{1,2}[._]\d{1,2}",
                 component, re.IGNORECASE):
        return []
    matches: list[DateCandidate] = []

    def add(day: int, month: int, year: int, source: str, confidence: str) -> None:
        try:
            value = date(year, month, day).isoformat()
        except ValueError:
            return
        matches.append(DateCandidate(value, source, confidence, component))

    full_date_found = False
    for match in _YEAR_FIRST.finditer(component):
        add(int(match.group(4)), int(match.group(3)), int(match.group(1)), "year-first numeric", "high")
        full_date_found = True
    for match in _DAY_FIRST_FULL.finditer(component):
        raw_year = int(match.group(4))
        year = raw_year
        add(int(match.group(1)), int(match.group(3)), year, "day-first numeric with year", "high")
        full_date_found = True
    if year_hint is not None and not full_date_found:
        for match in _DAY_MONTH.finditer(component):
            add(int(match.group(1)), int(match.group(2)), year_hint, "day-first numeric using project year", "medium")
        for match in _DAY_MONTH_NAME.finditer(component):
            token = unicodedata.normalize("NFC", match.group(2).casefold())
            month = _MONTHS.get(token)
            if month is None:
                token = token.rstrip(".")
                month = _MONTHS.get(token)
            if month is not None:
                add(int(match.group(1)), month, year_hint, "day with localized month name", "medium")
    # Identical parses in one component are one suggestion, even when a name
    # repeats the same date in two notations.
    return list({candidate.study_date: candidate for candidate in matches}.values())


def suggest_date(path_parts: tuple[str, ...], year_hint: int | None) -> DateSuggestion:
    candidates: list[DateCandidate] = []
    ambiguous_component = False
    for component in path_parts:
        candidates.extend(_matches_in_component(component, year_hint))
        if re.search(r"(?<!\d)\d{1,2}[._]\d{1,2}[._]\d{1,2}(?!\d)", component):
            ambiguous_component = True
    distinct = {candidate.study_date for candidate in candidates}
    if ambiguous_component:
        return DateSuggestion(None, tuple(candidates), True,
                              "This numeric name has an ambiguous date-like pattern.")
    if not candidates:
        return DateSuggestion(None, (), True, "No unambiguous study date was found.")
    if len(distinct) > 1:
        return DateSuggestion(None, tuple(candidates), True,
                              "Different path components suggest conflicting dates.")
    value = next(iter(distinct))
    best = min((candidate for candidate in candidates if candidate.study_date == value),
               key=lambda candidate: (candidate.confidence != "high", len(candidate.component)))
    return DateSuggestion(value, tuple(candidates), False, best.source)


def classify_file(relative_parts: tuple[str, ...], suffix: str, is_transcript_text: bool = False) -> str:
    normalized = [unicodedata.normalize("NFC", part).casefold() for part in relative_parts]
    for component in normalized[:-1]:
        if component in {"scr", "screenshots", "screenshot", "screencaps", "скриншоты", "скрины"}:
            return "screenshot"
    if is_transcript_text:
        return "transcript_candidate"
    if suffix in _MEDIA_SUFFIXES:
        return "audio_video"
    if suffix == ".srt":
        return "subtitle"
    if suffix in _IMAGE_SUFFIXES:
        return "screenshot"
    if suffix == ".zip":
        name = normalized[-1] if normalized else ""
        if "скрин" in name or "screenshot" in name:
            return "screenshot_archive"
        if "дополнитель" in name or "zusatz" in name or "extra" in name:
            return "extra_archive"
        if "материал" in name or "materials" in name:
            return "study_archive"
        return "archive"
    return "other"


def _looks_like_text_transcript(path: Path, same_day_stems: set[str]) -> bool:
    if path.suffix.casefold() != ".txt":
        return False
    if re.fullmatch(r"session(?:[_ -].*)?\.txt", path.name, re.IGNORECASE):
        return True
    if path.stem.casefold() in same_day_stems:
        return True
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            text = stream.read(1_000_000)
    except OSError:
        return False
    return len(_TRANSCRIPT_CUE.findall(text[:1_000_000])) >= 2


def scan_sources(source_paths: tuple[str | Path, ...] | list[str | Path],
                 year_hint: int | None = None, start_date: str | date | None = None) -> ScanResult:
    """Read source trees without modifying them or unpacking existing archives."""
    if year_hint is not None and (isinstance(year_hint, bool) or not 2000 <= year_hint <= 2100):
        raise ValueError("year hint must be between 2000 and 2100")
    if start_date is not None:
        try:
            anchor = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        except ValueError as exc:
            raise ValueError("start date must use YYYY-MM-DD format") from exc
        if not isinstance(anchor, date):
            raise ValueError("start date must use YYYY-MM-DD format")
        if year_hint is not None and year_hint != anchor.year:
            raise ValueError("year hint must match the start date year")
        year_hint = anchor.year
    else:
        anchor = None
    issues: list[ScanIssue] = []
    excluded: list[str] = []
    roots: list[SourceRoot] = []
    seen_roots: set[str] = set()
    files: list[StudyFile] = []
    seen_paths: set[str] = set()

    for raw_root in source_paths:
        path = Path(raw_root).expanduser()
        if path.is_symlink():
            issues.append(ScanIssue("root_symlink", str(path), "A source folder cannot be a symbolic link.", True))
            continue
        canonical = path.resolve(strict=False)
        if str(canonical) in seen_roots:
            issues.append(ScanIssue("duplicate_root", canonical.name,
                                    "This source folder is already in the project."))
            continue
        seen_roots.add(str(canonical))
        root = SourceRoot(str(uuid.uuid5(_ROOT_ID_NAMESPACE, str(canonical))), str(canonical))
        roots.append(root)
        if not canonical.exists() or not canonical.is_dir():
            issues.append(ScanIssue("source_unavailable", canonical.name,
                                    "The source folder is missing or unavailable.", True))
            continue

        stack = [canonical]
        found: list[Path] = []
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir(), key=lambda item: _natural_key(item.name), reverse=True)
            except OSError:
                relative = current.relative_to(canonical).as_posix() if current != canonical else "."
                issues.append(ScanIssue("folder_unreadable", relative,
                                        "This folder cannot be read. Check its permissions or connection.", True))
                continue
            for entry in entries:
                relative = entry.relative_to(canonical).as_posix()
                if entry.name.casefold() in _SYSTEM_NAMES or entry.name.startswith("._"):
                    excluded.append(relative)
                    continue
                if entry.name.startswith("."):
                    excluded.append(relative)
                    issues.append(ScanIssue("hidden_item", relative,
                                            "Hidden item excluded from the publication plan."))
                    continue
                if entry.is_symlink():
                    issues.append(ScanIssue("symlink_excluded", relative,
                                            "Symbolic links are excluded from source scanning."))
                    continue
                try:
                    if entry.is_dir():
                        if entry.name == "__MACOSX":
                            excluded.append(relative)
                        else:
                            stack.append(entry)
                    elif entry.is_file():
                        if entry.name.casefold() == "00_дата.txt":
                            excluded.append(relative)
                        else:
                            found.append(entry)
                except OSError:
                    issues.append(ScanIssue("path_unreadable", relative,
                                            "This file or folder cannot be inspected.", True))

        found.sort(key=lambda item: _natural_key(item.relative_to(canonical).as_posix()))
        media_stems: dict[tuple[str, str], set[str]] = {}
        for entry in found:
            suffix = entry.suffix.casefold()
            parts = entry.relative_to(canonical).parts
            parent = str(Path(*parts[:-1])) if len(parts) > 1 else "."
            if suffix in _MEDIA_SUFFIXES:
                media_stems.setdefault((parent, entry.stem.casefold()), set()).add(suffix)

        for entry in found:
            relative = entry.relative_to(canonical).as_posix()
            try:
                suffix = entry.suffix.casefold()
                metadata = entry.stat(follow_symlinks=False)
                if not entry.is_file() or entry.is_symlink():
                    raise OSError("not a regular file")
                parent = str(Path(*entry.relative_to(canonical).parts[:-1])) if len(entry.relative_to(canonical).parts) > 1 else "."
                is_transcript = _looks_like_text_transcript(
                    entry, {stem for directory, stem in media_stems if directory == parent}
                )
                suggestion = suggest_date(entry.relative_to(canonical).parts, year_hint)
                path_parts = entry.relative_to(canonical).parts
                named_weeks = _week_numbers(path_parts)
                named_week = named_weeks[0] if len(named_weeks) == 1 else None
                if len(named_weeks) > 1:
                    issues.append(ScanIssue("week_conflict", relative,
                                            "Different folder names suggest conflicting weeks."))
                week = named_week
                if suggestion.study_date is not None and anchor is not None:
                    actual = date.fromisoformat(suggestion.study_date)
                    if actual < anchor:
                        issues.append(ScanIssue("date_before_course", relative,
                                                "This date is before the course start date."))
                        week = None
                    else:
                        calendar_week = (actual - anchor).days // 7 + 1
                        if named_weeks and named_week != calendar_week:
                            issues.append(ScanIssue("week_conflict", relative,
                                                    "The named week conflicts with the course calendar."))
                            week = None
                        else:
                            week = calendar_week
                if suggestion.needs_review:
                    issues.append(ScanIssue("date_review", relative, suggestion.reason, False))
                if suggestion.study_date is None and week is None:
                    issues.append(ScanIssue("date_unresolved", relative,
                                            "Assign this file to a day or explicitly to weekly materials."))
                if suggestion.study_date is not None and year_hint is not None:
                    actual = date.fromisoformat(suggestion.study_date)
                    if actual < date(year_hint, 1, 1) or actual > date(year_hint, 12, 31):
                        issues.append(ScanIssue("date_year_mismatch", relative,
                                                "The suggested year does not match the selected course year."))
                try:
                    identity = f"{root.id}:{relative}"
                    if identity in seen_paths:
                        issues.append(ScanIssue("duplicate_source_file", relative,
                                                "The same source file was selected more than once."))
                        continue
                    seen_paths.add(identity)
                    category = classify_file(entry.relative_to(canonical).parts, suffix, is_transcript)
                    stable_file_id = str(uuid.uuid5(uuid.UUID(root.id), relative))
                    files.append(StudyFile(
                        stable_file_id, root.id, relative, entry.name, metadata.st_size, metadata.st_mtime_ns,
                        study_date=suggestion.study_date, category=category, week_number=week,
                        included=not is_transcript,
                    ))
                except ValueError:
                    issues.append(ScanIssue("invalid_path", relative,
                                            "The file path cannot be represented safely.", True))
            except OSError:
                issues.append(ScanIssue("file_unreadable", relative,
                                        "This file changed or became unavailable during scanning.", True))

    files.sort(key=lambda item: (item.study_date or "9999-99-99", item.week_number or 999,
                                 _natural_key(item.name), item.source_root_id, item.relative_path))
    return ScanResult(tuple(roots), tuple(files), tuple(issues), tuple(sorted(set(excluded))))
