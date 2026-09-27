"""Conservative SRT excerpts, local title prompts, and output-name proposals."""
from __future__ import annotations

import re
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .local_model import GenerationResult, LlamaCliRunner

_TIMESTAMP = re.compile(
    r"(?P<start>\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{2,}:\d{2}:\d{2}[,.]\d{3})"
)
_TAG = re.compile(r"<[^>]*>")
_ASSIGNMENT = re.compile(r"\{\\[^}]*\}")
_VARIANT = re.compile(r"(?i)(?:^|[._ -])(ru|de|en|рус|нем|720p|1080p|480p|\d{3,4}p)$")


@dataclass(frozen=True)
class SubtitleExcerpt:
    text: str
    included_cues: int
    cutoff_seconds: int
    truncated: bool


@dataclass(frozen=True)
class TitleProposal:
    title: str
    source_subtitle: str
    elapsed_seconds: float
    model_revision: str
    output_names: tuple[tuple[str, str], ...]


def _seconds(timestamp: str) -> float:
    hours, minutes, remainder = timestamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(remainder)


def extract_srt_excerpt(path: str | Path, minutes: int = 10,
                        *, max_characters: int = 24_000) -> SubtitleExcerpt:
    """Read cues whose start is before the time limit; never rewrite the SRT."""
    if minutes not in {5, 10}:
        raise ValueError("minutes must be 5 or 10")
    if not 100 <= max_characters <= 100_000:
        raise ValueError("max_characters must be between 100 and 100,000")
    source = Path(path)
    data = source.read_bytes()
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            raw = data.decode("utf-16")
        else:
            raw = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = data.decode("cp1252")
    limit = minutes * 60
    cues: list[str] = []
    clipped = False
    for block in re.split(r"\r?\n\s*\r?\n", raw):
        lines = block.splitlines()
        timestamp_at = next((i for i, line in enumerate(lines) if _TIMESTAMP.search(line)), None)
        if timestamp_at is None:
            continue
        match = _TIMESTAMP.search(lines[timestamp_at])
        assert match is not None
        if _seconds(match.group("start")) >= limit:
            clipped = True
            continue
        text = " ".join(lines[timestamp_at + 1:])
        text = _ASSIGNMENT.sub(" ", _TAG.sub(" ", text))
        text = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", text)).strip()
        if not text:
            continue
        remaining = max_characters - sum(len(cue) + 1 for cue in cues)
        if remaining <= 0:
            clipped = True
            break
        if len(text) > remaining:
            cues.append(text[:remaining].rsplit(" ", 1)[0])
            clipped = True
            break
        cues.append(text)
    return SubtitleExcerpt("\n".join(cues), len(cues), limit, clipped)


def build_title_prompt(excerpt: SubtitleExcerpt, *, source_language: str = "auto") -> str:
    if not excerpt.text.strip():
        raise ValueError("subtitle excerpt contains no readable text")
    if source_language not in {"auto", "de", "ru", "en"}:
        raise ValueError("unsupported source language")
    return (
        "Придумай короткое русское название учебной записи по фрагменту субтитров. "
        "Если субтитры не на русском, переведи смысл на русский. "
        "Не оставляй в названии немецкие или английские слова. "
        "Ответь только названием: 2–7 слов, без кавычек, точки, пояснений и списков. "
        "Сохрани точный смысл; не добавляй факты, которых нет в тексте. "
        f"Язык субтитров: {source_language}.\n\nСубтитры за первые "
        f"{excerpt.cutoff_seconds // 60} минут:\n{excerpt.text}"
    )


def sanitize_russian_title(value: str) -> str | None:
    """Accept a single short title, declining output that needs guessing."""
    if "\n" in value or "\r" in value:
        return None
    title = value.strip().strip("\"'“”„«»*_` ")
    title = re.sub(r"^(?:название|предложенное название)\s*:\s*", "", title,
                   flags=re.IGNORECASE).strip()
    title = title.strip("\"'“”„«»*_` ")
    title = re.sub(r"\s+", " ", title).rstrip(".!:;—–- ")
    if not title or len(title) > 100 or "\n" in title or "/" in title or "\\" in title:
        return None
    words = title.split()
    if not 2 <= len(words) <= 10 or any(ord(ch) < 32 for ch in title):
        return None
    if not re.match(r"[А-Яа-яЁё]", title):
        return None
    return title


def _key(stem: str) -> str:
    value = unicodedata.normalize("NFKC", stem).casefold()
    while match := _VARIANT.search(value):
        value = value[:match.start()]
    value = re.sub(r"[._ -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def linked_output_names(files: tuple[Path, ...] | list[Path], title: str) -> tuple[tuple[str, str], ...]:
    """Propose names for same-stem media/SRT files, preserving suffix variants."""
    clean = sanitize_russian_title(title)
    if clean is None:
        raise ValueError("title is not a safe short Russian title")
    paths = tuple(files)
    if not paths:
        return ()
    keys = {_key(path.stem) for path in paths}
    if len(keys) != 1:
        raise ValueError("files do not form an unambiguous same-stem set")
    base_key = next(iter(keys))
    result: list[tuple[str, str]] = []
    occupied: set[str] = set()
    for path in paths:
        stem = path.stem
        key = _key(stem)
        if key != base_key:
            raise ValueError("files do not form an unambiguous same-stem set")
        suffix_parts: list[str] = []
        value = stem
        while match := _VARIANT.search(value):
            suffix_parts.insert(0, match.group(1))
            value = value[:match.start()]
        suffix = " ".join(suffix_parts)
        new_stem = clean + (f" {suffix}" if suffix else "")
        name = new_stem + path.suffix
        folded = name.casefold()
        if folded in occupied:
            raise ValueError("title would create colliding output names")
        occupied.add(folded)
        result.append((path.name, name))
    return tuple(result)


def apply_output_name_proposal(output_directory: str | Path,
                               names: tuple[tuple[str, str], ...], *,
                               approved_names: tuple[tuple[str, str], ...]) -> tuple[Path, ...]:
    """Apply an exact user-approved rename to prepared output files only.

    Hard links install each destination without overwrite. Source output names are
    removed only after every destination is installed and verified. Input folders
    are never consulted or modified.
    """
    if not names or names != approved_names:
        raise ValueError("the exact proposed output names must be approved")
    directory = Path(output_directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("output directory must be a directory")
    sources: list[Path] = []
    destinations: list[Path] = []
    seen: set[str] = set()
    for old_name, new_name in names:
        if (Path(old_name).name != old_name or Path(new_name).name != new_name or
                old_name in {".", ".."} or new_name in {".", ".."} or
                "\x00" in old_name or "\x00" in new_name):
            raise ValueError("proposed names must be plain file names")
        source = directory / old_name
        destination = directory / new_name
        key = new_name.casefold()
        if key in seen:
            raise ValueError("proposed output names collide")
        seen.add(key)
        if source == destination:
            raise ValueError("proposed output name is unchanged")
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"prepared output is missing or unsafe: {old_name}")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"refusing to overwrite prepared output: {new_name}")
        sources.append(source)
        destinations.append(destination)
    installed: list[Path] = []
    try:
        for source, destination in zip(sources, destinations):
            os.link(source, destination)
            installed.append(destination)
        for source, destination in zip(sources, destinations):
            if source.stat().st_size != destination.stat().st_size:
                raise OSError("output changed while applying title")
        for source in sources:
            source.unlink()
    except Exception:
        # Preserve any destination that is no longer a hard link to its original.
        for source, destination in zip(sources, installed):
            try:
                if source.exists() and os.path.samefile(source, destination):
                    destination.unlink()
            except OSError:
                pass
        raise
    return tuple(destinations)


def suggest_title(path: str | Path, runner: LlamaCliRunner, *, minutes: int = 10,
                  source_language: str = "auto",
                  related_files: tuple[Path, ...] | list[Path] = ()) -> TitleProposal | None:
    excerpt = extract_srt_excerpt(path, minutes)
    if not excerpt.text.strip():
        return None
    generated: GenerationResult = runner.generate(build_title_prompt(excerpt,
                                                                      source_language=source_language),
                                                  max_tokens=128)
    title = sanitize_russian_title(generated.text)
    if title is None:
        return None
    names = linked_output_names(related_files, title) if related_files else ()
    return TitleProposal(title, Path(path).name, generated.elapsed_seconds,
                         generated.model_revision, names)
