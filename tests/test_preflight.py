import tempfile
import unittest
from pathlib import Path

from study_archive_prep.project import ProjectState, SourceRoot, StudyFile
from study_archive_prep.publication import build_default_plan
from study_archive_prep.preflight import build_preflight


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source_dir = self.base / "source"
        self.source_dir.mkdir()
        self.output = self.base / "prepared"
        self.root = SourceRoot.create(self.source_dir)
        self.project = ProjectState.create("Course", self.output, "2026-08-03", (self.root,))

    def tearDown(self):
        self.temporary.cleanup()

    def add_file(self, relative, category, day="2026-08-03", week=1):
        target = self.source_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"content-" + relative.encode("utf-8"))
        info = target.stat()
        record = StudyFile.create(self.root.id, relative, target.name, info.st_size, info.st_mtime_ns,
                                  study_date=day, week_number=week, category=category)
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,),
                                    files=(*self.project.files, record))
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,), files=self.project.files,
                                    blocks=build_default_plan(self.project).blocks)
        return target, record

    def test_complete_destination_preview_matches_expected_weekday_categories(self):
        _, audio = self.add_file("lesson.m4a", "audio_video")
        _, subtitle = self.add_file("lesson.ru.srt", "subtitle")
        _, shot = self.add_file("screenshots/01.png", "screenshot")
        _, extra = self.add_file("worksheet.pdf", "other")
        before = tuple(self.output.rglob("*")) if self.output.exists() else ()
        plan = build_preflight(self.project)
        after = tuple(self.output.rglob("*")) if self.output.exists() else ()
        self.assertTrue(plan.can_execute)
        self.assertEqual(before, after)
        self.assertEqual({copy.file_id for copy in plan.copies}, {audio.id, subtitle.id})
        self.assertEqual([archive.destination for archive in plan.archives], [
            "Неделя 1 03.08 - 03.08/2026-08-03/03_Скриншоты.zip",
            "Неделя 1 03.08 - 03.08/2026-08-03/04_Дополнительные_материалы.zip",
        ])
        self.assertEqual(plan.archives[0].member_file_ids, (shot.id,))
        self.assertEqual(plan.archives[1].member_file_ids, (extra.id,))
        self.assertGreater(plan.required_bytes, sum(file.size for file in self.project.files))

    def test_week_material_is_planned_as_week_archive_and_existing_week_zip_is_copied(self):
        _, notes = self.add_file("week/worksheet.pdf", "other", day=None)
        archive_path, archive = self.add_file("week/Неделя_01_Материалы_на_неделю.zip",
                                              "study_archive", day=None)
        plan = build_preflight(self.project)
        self.assertTrue(plan.can_execute)
        self.assertEqual(len(plan.archives), 1)
        self.assertEqual(plan.archives[0].member_file_ids, (notes.id,))
        self.assertEqual(plan.archives[0].destination,
                         "Неделя 1/Неделя_01_Материалы_на_неделю (2).zip")
        copied = next(item for item in plan.copies if item.file_id == archive.id)
        self.assertEqual(copied.destination, "Неделя 1/Неделя_01_Материалы_на_неделю.zip")
        self.assertTrue(archive_path.exists())

    def test_source_changed_after_scan_blocks_operation(self):
        target, _ = self.add_file("lesson.m4a", "audio_video")
        target.write_bytes(b"changed bytes")
        plan = build_preflight(self.project)
        self.assertFalse(plan.can_execute)
        self.assertIn("source_changed", {issue.code for issue in plan.issues})

    def test_missing_source_file_blocks_operation(self):
        target, _ = self.add_file("lesson.m4a", "audio_video")
        target.unlink()
        plan = build_preflight(self.project)
        self.assertFalse(plan.can_execute)
        self.assertIn("source_unavailable", {issue.code for issue in plan.issues})

    def test_existing_output_is_never_overwritten(self):
        self.add_file("lesson.m4a", "audio_video")
        target = self.output / "Неделя 1 03.08 - 03.08" / "2026-08-03" / "01_Аудио" / "lesson.m4a"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous output")
        plan = build_preflight(self.project)
        self.assertFalse(plan.can_execute)
        self.assertIn("output_exists", {issue.code for issue in plan.issues})
        self.assertEqual(target.read_bytes(), b"previous output")

    def test_duplicate_output_names_receive_deterministic_suffixes(self):
        _, first = self.add_file("one/lesson.m4a", "audio_video")
        _, second = self.add_file("two/lesson.m4a", "audio_video")
        plan = build_preflight(self.project)
        names = {item.destination for item in plan.copies}
        self.assertIn("Неделя 1 03.08 - 03.08/2026-08-03/01_Аудио/lesson.m4a", names)
        self.assertIn("Неделя 1 03.08 - 03.08/2026-08-03/01_Аудио/lesson (2).m4a", names)
        self.assertEqual(len(names), 2)
        self.assertEqual({item.file_id for item in plan.copies}, {first.id, second.id})

    def test_included_file_without_a_block_is_an_explicit_blocking_issue(self):
        self.add_file("lesson.m4a", "audio_video")
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=self.project.roots,
                                    files=self.project.files, blocks=())
        plan = build_preflight(self.project)
        self.assertFalse(plan.can_execute)
        self.assertIn("file_without_block", {issue.code for issue in plan.issues})


if __name__ == "__main__":
    unittest.main()
