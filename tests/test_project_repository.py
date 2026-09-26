import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from study_archive_prep.project import ProjectState, PublicationBlock, SourceRoot, StudyFile
from study_archive_prep.project_repository import (
    ProjectRepository,
    ProjectStorageError,
    StaleProjectError,
    default_data_directory,
)


class ProjectRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "private" / "projects.sqlite3"
        self.repository = ProjectRepository(self.database)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "output"
        self.output.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_project(self):
        source = SourceRoot.create(self.source)
        study_file = StudyFile.create(source.id, "2026-08-03/02_Субтитры/введение.ru.srt",
                                      "введение.ru.srt", 96, 1_750_000_000_000_000_000,
                                      sha256="a" * 64, study_date="2026-08-03", category="subtitles")
        week = PublicationBlock.create("week", "Неделя 1 03.08 - 08.08")
        day = PublicationBlock.create("day", "2026-08-03", parent_id=week.id,
                                      study_date="2026-08-03")
        file = PublicationBlock.create("file", "введение.ru.srt", parent_id=day.id,
                                       file_id=study_file.id)
        state = ProjectState.create("Учебный курс", self.output, "2026-08-03", roots=(source,))
        return ProjectState(state.id, state.name, state.output_path, state.start_date,
                            roots=state.roots, files=(study_file,), blocks=(week, day, file))

    def test_new_and_updated_projects_round_trip_through_a_fresh_repository(self):
        original = self.make_project()
        saved = self.repository.save(original)
        self.assertEqual(saved.revision, 1)
        reopened = ProjectRepository(self.database)
        loaded = reopened.load(original.id)
        self.assertEqual(loaded, saved)
        self.assertEqual(reopened.list_projects(), (saved,))

        updated = reopened.save(loaded, expected_revision=loaded.revision)
        self.assertEqual(updated.revision, 2)
        self.assertEqual(self.repository.load(original.id), updated)

    def test_stale_snapshot_is_rejected_without_overwriting_newer_data(self):
        created = self.repository.save(self.make_project())
        stale_copy = ProjectRepository(self.database).load(created.id)
        current_copy = ProjectRepository(self.database).load(created.id)
        newer = self.repository.save(current_copy, expected_revision=current_copy.revision)
        with self.assertRaises(StaleProjectError):
            self.repository.save(stale_copy, expected_revision=stale_copy.revision)
        self.assertEqual(self.repository.load(created.id), newer)

    def test_parent_hierarchy_must_follow_week_day_file_structure(self):
        root = SourceRoot.create(self.source)
        week = PublicationBlock.create("week", "Неделя 1")
        other_week = PublicationBlock.create("week", "Неделя 2", position=1)
        day = PublicationBlock.create("day", "2026-08-03", parent_id=week.id,
                                      study_date="2026-08-03")
        with self.assertRaisesRegex(ValueError, "must belong to a week"):
            bad_day = PublicationBlock.create("day", "2026-08-04", parent_id=day.id,
                                              study_date="2026-08-04")
            ProjectState.create("course", self.output, roots=(root,)).__class__(
                id=ProjectState.create("course", self.output).id, name="course",
                output_path=str(self.output), start_date=None, roots=(root,),
                blocks=(week, other_week, day, bad_day))

    def test_database_and_its_private_data_folder_have_owner_only_permissions(self):
        self.repository.save(self.make_project())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.database.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(self.database.stat().st_mode), 0o600)

    def test_a_database_symlink_is_rejected(self):
        real = self.root / "real.sqlite3"
        ProjectRepository(real).save(self.make_project())
        link = self.root / "link.sqlite3"
        link.symlink_to(real)
        with self.assertRaises(ProjectStorageError):
            ProjectRepository(link).list_projects()

    def test_unknown_database_version_fails_closed(self):
        self.repository.save(self.make_project())
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA user_version = 999")
        connection.close()
        with self.assertRaisesRegex(ProjectStorageError, "newer app version"):
            self.repository.list_projects()

    def test_corrupt_saved_project_is_reported_without_silent_repair(self):
        saved = self.repository.save(self.make_project())
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE projects SET state_json = ? WHERE id = ?", ('{"schema_version":999}', saved.id))
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(ProjectStorageError, "damaged or unsupported"):
            self.repository.load(saved.id)

    def test_project_schema_rejects_absolute_or_parent_traversal_file_paths(self):
        root = SourceRoot.create(self.source)
        for relative_path in ("../private.txt", "/private.txt", "day\\file.srt"):
            with self.subTest(relative_path=relative_path):
                with self.assertRaises(ValueError):
                    StudyFile.create(root.id, relative_path, "file.srt", 1, 1)

    def test_project_schema_rejects_dangling_links_and_bad_hashes(self):
        root = SourceRoot.create(self.source)
        with self.assertRaisesRegex(ValueError, "existing source root"):
            ProjectState(
                id=ProjectState.create("course", self.output, roots=(root,)).id,
                name="course", output_path=str(self.output), start_date=None,
                roots=(root,), files=(StudyFile.create("30000000-0000-4000-8000-000000000001",
                                                      "file.srt", "file.srt", 1, 1),))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            StudyFile.create(root.id, "file.srt", "file.srt", 1, 1, sha256="not-a-hash")

    def test_default_project_storage_is_under_the_application_data_folder(self):
        self.assertEqual(default_data_directory(), Path.home() / "Library" / "Application Support" / "StudyArchivePrep")


if __name__ == "__main__":
    unittest.main()
