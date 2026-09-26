"""Private, versioned, atomic SQLite persistence for project state."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
from datetime import datetime, timezone
from pathlib import Path

from .project import ProjectState

DATABASE_VERSION = 1
MAX_PROJECT_BYTES = 64 * 1024 * 1024


class ProjectStorageError(RuntimeError):
    """Saved project data could not be read or written safely."""


class StaleProjectError(ProjectStorageError):
    """Another writer has saved a newer project revision."""


def default_data_directory() -> Path:
    """Return the per-user macOS data directory without creating it."""
    return Path.home() / "Library" / "Application Support" / "StudyArchivePrep"


class ProjectRepository:
    """Store validated project snapshots with optimistic revision checks."""

    def __init__(self, database_path: Path | str | None = None):
        self.database_path = Path(database_path or default_data_directory() / "projects.sqlite3").expanduser()

    def _connect(self) -> sqlite3.Connection:
        path = self.database_path
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.parent.chmod(0o700)
            if path.is_symlink():
                raise ProjectStorageError("The project database must not be a symbolic link.")
            if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
                raise ProjectStorageError("The project database must be a regular file.")
            connection = sqlite3.connect(path, timeout=10.0, isolation_level=None)
            try:
                path.chmod(0o600)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 10000")
                connection.execute("PRAGMA journal_mode = DELETE")
                connection.execute("PRAGMA synchronous = FULL")
                self._initialize(connection)
                return connection
            except Exception:
                connection.close()
                raise
        except ProjectStorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ProjectStorageError("Could not securely open the project database.") from exc

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > DATABASE_VERSION:
            raise ProjectStorageError("This project database was made by a newer app version.")
        if version == DATABASE_VERSION:
            return
        if version != 0:
            raise ProjectStorageError("This project database has no supported migration.")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE projects ("
                "id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision >= 0), "
                "state_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX projects_updated ON projects(updated_at DESC)")
            connection.execute(f"PRAGMA user_version = {DATABASE_VERSION}")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def list_projects(self) -> tuple[ProjectState, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT state_json FROM projects ORDER BY updated_at DESC, id"
            ).fetchall()
            return tuple(self._decode(row[0]) for row in rows)
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ProjectStorageError("A saved project could not be read safely.") from exc
        finally:
            connection.close()

    def load(self, project_id: str) -> ProjectState:
        connection = self._connect()
        try:
            row = connection.execute("SELECT state_json FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise ProjectStorageError("The requested project was not found.")
            return self._decode(row[0])
        except ProjectStorageError:
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ProjectStorageError("The saved project is damaged or unsupported.") from exc
        finally:
            connection.close()

    def save(self, state: ProjectState, *, expected_revision: int | None = None) -> ProjectState:
        if not isinstance(state, ProjectState):
            raise TypeError("save expects a validated ProjectState")
        if state.schema_version != DATABASE_VERSION:
            raise ProjectStorageError("The project uses an unsupported schema version.")
        encoded = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_PROJECT_BYTES:
            raise ProjectStorageError("The project is too large to save safely.")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM projects WHERE id = ?", (state.id,)
            ).fetchone()
            if current is None:
                if expected_revision not in (None, 0) or state.revision != 0:
                    raise StaleProjectError("The project does not exist at the expected revision.")
                revision = 1
                connection.execute(
                    "INSERT INTO projects(id, revision, state_json, updated_at) VALUES (?, ?, ?, ?)",
                    (state.id, revision, self._encode_revision(state, revision), self._now()),
                )
            else:
                current_revision = int(current[0])
                requested = state.revision if expected_revision is None else expected_revision
                if requested != current_revision:
                    raise StaleProjectError("The project changed since it was loaded. Reload before saving.")
                revision = current_revision + 1
                connection.execute(
                    "UPDATE projects SET revision = ?, state_json = ?, updated_at = ? WHERE id = ?",
                    (revision, self._encode_revision(state, revision), self._now(), state.id),
                )
            connection.execute("COMMIT")
            return state.with_revision(revision)
        except StaleProjectError:
            connection.execute("ROLLBACK")
            raise
        except (sqlite3.Error, ValueError, TypeError) as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            if isinstance(exc, ProjectStorageError):
                raise
            raise ProjectStorageError("Could not safely save the project.") from exc
        finally:
            connection.close()

    @staticmethod
    def _encode_revision(state: ProjectState, revision: int) -> str:
        return json.dumps(state.with_revision(revision).to_dict(), ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(encoded: str) -> ProjectState:
        if len(encoded.encode("utf-8")) > MAX_PROJECT_BYTES:
            raise ValueError("saved project exceeds the supported size")
        state = ProjectState.from_dict(json.loads(encoded))
        if state.schema_version != DATABASE_VERSION:
            raise ValueError("saved project schema does not match its database")
        return state

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
