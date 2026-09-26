"""Default ordered publication blocks and safe in-memory editing operations."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from dataclasses import replace
from datetime import date
from typing import Iterable

from .project import ProjectState, PublicationBlock, StudyFile


_BLOCK_NAMESPACE_SUFFIX = "a7ef6d6a-ec35-4fd0-a447-e1ac6bc719af"
_CATEGORY_ORDER = {
    "study_archive": 0,
    "audio_video": 10,
    "subtitle": 20,
    "screenshot": 30,
    "screenshot_archive": 31,
    "extra_archive": 40,
    "archive": 45,
    "transcript_candidate": 80,
    "other": 50,
}


@dataclass(frozen=True)
class DefaultPlan:
    blocks: tuple[PublicationBlock, ...]
    unassigned_file_ids: tuple[str, ...]


def _stable_id(project_id: str, key: str) -> str:
    namespace = uuid.uuid5(uuid.UUID(project_id), _BLOCK_NAMESPACE_SUFFIX)
    return str(uuid.uuid5(namespace, key))


def _file_sort_key(item: StudyFile) -> tuple:
    rank = -10 if item.category == "study_archive" and item.study_date is None else _CATEGORY_ORDER.get(item.category, 50)
    return (rank, item.name.casefold(), item.name,
            item.source_root_id, item.relative_path)


def _week_title(number: int, days: list[str]) -> str:
    if not days:
        return f"Неделя {number}"
    first = date.fromisoformat(days[0])
    last = date.fromisoformat(days[-1])
    return f"Неделя {number} {first:%d.%m} - {last:%d.%m}"


def build_default_plan(project: ProjectState) -> DefaultPlan:
    """Build stable-ID week/day/file nodes in the agreed publication order.

    Files lacking an assigned week are reported separately and never silently
    placed in an invented group. Excluded suggestions remain visible in-tree.
    """
    assigned: dict[int, list[StudyFile]] = {}
    unassigned: list[str] = []
    for item in project.files:
        if item.week_number is None:
            unassigned.append(item.id)
        else:
            assigned.setdefault(item.week_number, []).append(item)

    blocks: list[PublicationBlock] = []
    for week_position, week_number in enumerate(sorted(assigned)):
        week_files = assigned[week_number]
        day_dates = sorted({item.study_date for item in week_files if item.study_date is not None})
        week = PublicationBlock(
            _stable_id(project.id, f"week:{week_number}"), "week",
            _week_title(week_number, day_dates), week_position,
        )
        blocks.append(week)

        weekly_files = sorted((item for item in week_files if item.study_date is None), key=_file_sort_key)
        for position, item in enumerate(weekly_files):
            blocks.append(PublicationBlock(
                _stable_id(project.id, f"file:{item.id}"), "file", item.name, position,
                parent_id=week.id, file_id=item.id, included=item.included,
            ))

        for day_position, study_date in enumerate(day_dates, start=len(weekly_files)):
            day = PublicationBlock(
                _stable_id(project.id, f"day:{study_date}"), "day", study_date,
                day_position, parent_id=week.id, study_date=study_date,
            )
            blocks.append(day)
            day_files = sorted((item for item in week_files if item.study_date == study_date),
                               key=_file_sort_key)
            for file_position, item in enumerate(day_files):
                blocks.append(PublicationBlock(
                    _stable_id(project.id, f"file:{item.id}"), "file", item.name, file_position,
                    parent_id=day.id, file_id=item.id, included=item.included,
                ))
    return DefaultPlan(tuple(blocks), tuple(sorted(unassigned)))


class PublicationPlanEditor:
    """Immutable-snapshot edits with bounded undo/redo history."""

    def __init__(self, project: ProjectState, history_limit: int = 100):
        if history_limit < 1:
            raise ValueError("history limit must be positive")
        self.project = project
        self.history_limit = history_limit
        self._undo: list[ProjectState] = []
        self._redo: list[ProjectState] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _commit(self, blocks: Iterable[PublicationBlock]) -> None:
        updated = replace(self.project, blocks=tuple(blocks))
        if updated == self.project:
            return
        self._undo.append(self.project)
        if len(self._undo) > self.history_limit:
            del self._undo[0]
        self._redo.clear()
        self.project = updated

    def _block_map(self) -> dict[str, PublicationBlock]:
        return {item.id: item for item in self.project.blocks}

    def move(self, block_id: str, parent_id: str | None, position: int) -> None:
        """Move one block. Moving a day preserves all its child file blocks."""
        blocks = self._block_map()
        if block_id not in blocks:
            raise KeyError("publication block was not found")
        moving = blocks[block_id]
        if isinstance(position, bool) or position < 0:
            raise ValueError("position must be a non-negative integer")
        if moving.kind == "week" and parent_id is not None:
            raise ValueError("week blocks must remain at the top level")
        if moving.kind == "day":
            parent = blocks.get(parent_id or "")
            if parent is None or parent.kind != "week":
                raise ValueError("day blocks must be moved into a week")
        elif moving.kind in {"file", "text"}:
            parent = blocks.get(parent_id or "")
            if parent is None or parent.kind not in {"week", "day"}:
                raise ValueError("file and text blocks must be moved into a week or day")
        if parent_id == block_id:
            raise ValueError("a block cannot contain itself")
        if moving.kind in {"week", "day"}:
            cursor = blocks.get(parent_id or "")
            while cursor is not None:
                if cursor.id == block_id:
                    raise ValueError("a block cannot be moved into its descendant")
                cursor = blocks.get(cursor.parent_id or "")

        original_parent = moving.parent_id
        target = sorted((item for item in blocks.values()
                         if item.parent_id == parent_id and item.id != block_id),
                        key=lambda item: item.position)
        target.insert(min(position, len(target)), replace(moving, parent_id=parent_id))
        rebuilt = [item for item in self.project.blocks if item.id != block_id]
        replacements: dict[str, PublicationBlock] = {}
        if original_parent != parent_id:
            source = sorted((item for item in rebuilt if item.parent_id == original_parent),
                            key=lambda item: item.position)
            replacements.update({item.id: replace(item, position=index)
                                 for index, item in enumerate(source)})
        replacements.update({item.id: replace(item, parent_id=parent_id, position=index)
                             for index, item in enumerate(target)})
        rebuilt = [replacements.get(item.id, item) for item in rebuilt]
        rebuilt.append(replace(moving, parent_id=parent_id,
                               position=next(i for i, item in enumerate(target)
                                             if item.id == moving.id)))
        self._commit(rebuilt)

    def rename(self, block_id: str, title: str) -> None:
        blocks = self._block_map()
        if block_id not in blocks:
            raise KeyError("publication block was not found")
        updated = [replace(item, title=title) if item.id == block_id else item
                   for item in self.project.blocks]
        self._commit(updated)

    def set_included(self, block_id: str, included: bool) -> None:
        blocks = self._block_map()
        if block_id not in blocks:
            raise KeyError("publication block was not found")
        updated = [replace(item, included=included) if item.id == block_id else item
                   for item in self.project.blocks]
        self._commit(updated)

    def add_text(self, parent_id: str, text: str, position: int | None = None) -> PublicationBlock:
        blocks = self._block_map()
        parent = blocks.get(parent_id)
        if parent is None or parent.kind not in {"week", "day"}:
            raise ValueError("text messages must belong to a week or day")
        siblings = sorted((item for item in blocks.values() if item.parent_id == parent_id),
                          key=lambda item: item.position)
        index = len(siblings) if position is None else position
        if isinstance(index, bool) or index < 0:
            raise ValueError("position must be a non-negative integer")
        index = min(index, len(siblings))
        moved = [item for item in siblings]
        moved.insert(index, PublicationBlock.create("text", text, index,
                                                    parent_id=parent_id, text=text))
        ids = {item.id for item in moved}
        untouched = [item for item in self.project.blocks if item.id not in ids]
        ordered = [replace(item, position=i) for i, item in enumerate(moved)]
        new_block = moved[index]
        self._commit((*untouched, *ordered))
        return new_block

    def undo(self) -> ProjectState:
        if not self._undo:
            return self.project
        self._redo.append(self.project)
        self.project = self._undo.pop()
        return self.project

    def redo(self) -> ProjectState:
        if not self._redo:
            return self.project
        self._undo.append(self.project)
        self.project = self._redo.pop()
        return self.project
