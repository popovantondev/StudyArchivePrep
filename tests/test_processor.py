import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from study_archive_prep.project import ProjectState, SourceRoot, StudyFile
from study_archive_prep.publication import build_default_plan
from study_archive_prep.preflight import ProcessingPlan, build_preflight
from study_archive_prep.processor import OperationCancelled, ProcessingError, execute_processing_plan


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source_dir = self.base / "source"
        self.source_dir.mkdir()
        self.output = self.base / "result"
        self.root = SourceRoot.create(self.source_dir)
        self.project = ProjectState.create("Example", self.output, "2026-08-03", (self.root,))

    def tearDown(self):
        self.temporary.cleanup()

    def add_file(self, name, category, day="2026-08-03"):
        path = self.source_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ("synthetic content:" + name).encode()
        path.write_bytes(content)
        info = path.stat()
        record = StudyFile.create(self.root.id, name, path.name, info.st_size, info.st_mtime_ns,
                                  study_date=day, week_number=1, category=category)
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,),
                                    files=(*self.project.files, record))
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,), files=self.project.files,
                                    blocks=build_default_plan(self.project).blocks)
        return path, record, content

    def test_copy_is_verified_and_zip_contains_only_the_previewed_members(self):
        audio, audio_file, audio_content = self.add_file("lesson.m4a", "audio_video")
        screenshot, screenshot_file, screenshot_content = self.add_file("screenshots/01.png", "screenshot")
        plan = build_preflight(self.project)
        progress = []
        result = execute_processing_plan(plan, progress=lambda done, total, path: progress.append((done, total, path)))
        self.assertEqual(len(result.outputs), 2)
        copied = next(item for item in result.outputs if item.kind == "copy")
        archive = next(item for item in result.outputs if item.kind == "archive")
        self.assertEqual(Path(copied.path).read_bytes(), audio_content)
        self.assertEqual(copied.sha256, hashlib.sha256(audio_content).hexdigest())
        with zipfile.ZipFile(archive.path) as zipped:
            self.assertEqual(zipped.namelist(), ["01.png"])
            self.assertEqual(zipped.read("01.png"), screenshot_content)
        self.assertEqual(len(progress), 2)
        self.assertTrue(audio.exists())
        self.assertTrue(screenshot.exists())
        self.assertEqual(archive.source_file_ids, (screenshot_file.id,))

    def test_second_run_refuses_to_overwrite_any_completed_output(self):
        self.add_file("lesson.m4a", "audio_video")
        plan = build_preflight(self.project)
        execute_processing_plan(plan)
        self.assertFalse(build_preflight(self.project).can_execute)
        with self.assertRaises(ProcessingError):
            execute_processing_plan(plan)

    def test_cancel_during_copy_removes_temporary_file_and_keeps_source(self):
        source, _, content = self.add_file("large.m4a", "audio_video")
        plan = build_preflight(self.project)
        calls = 0

        def cancel_after_first_chunk():
            nonlocal calls
            calls += 1
            return calls >= 2

        with self.assertRaises(OperationCancelled) as caught:
            execute_processing_plan(plan, cancelled=cancel_after_first_chunk)
        self.assertEqual(caught.exception.completed, ())
        self.assertTrue(source.exists())
        self.assertEqual(list(self.output.rglob("*.tmp")), [])
        self.assertEqual(len(list(self.output.rglob(".study-archive-prep-*.tmp"))), 0)
        self.assertEqual(len(content), source.stat().st_size)

    def test_source_change_after_preflight_stops_before_install(self):
        source, _, _ = self.add_file("lesson.m4a", "audio_video")
        plan = build_preflight(self.project)
        source.write_bytes(b"changed")
        with self.assertRaises(ProcessingError):
            execute_processing_plan(plan)
        self.assertEqual(list(self.output.rglob("lesson.m4a")), [])

    def test_cancel_after_one_completed_file_reports_partial_outputs(self):
        first, first_file, _ = self.add_file("a.m4a", "audio_video")
        second, _, _ = self.add_file("b.m4a", "audio_video")
        plan = build_preflight(self.project)
        calls = 0

        def cancel_after_one():
            nonlocal calls
            calls += 1
            return calls >= 5

        with self.assertRaises(OperationCancelled) as caught:
            execute_processing_plan(plan, cancelled=cancel_after_one)
        self.assertEqual(len(caught.exception.completed), 1)
        self.assertEqual(caught.exception.completed[0].source_file_ids, (first_file.id,))
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_forged_path_traversal_plan_is_rejected(self):
        self.add_file("lesson.m4a", "audio_video")
        plan = build_preflight(self.project)
        forged = ProcessingPlan(plan.output_path,
                                (type(plan.copies[0])(plan.copies[0].file_id,
                                                      plan.copies[0].source_path,
                                                      "../escape.m4a", plan.copies[0].size,
                                                      plan.copies[0].mtime_ns),),
                                (), (), plan.required_bytes, plan.available_bytes)
        with self.assertRaises(ProcessingError):
            execute_processing_plan(forged)
        self.assertFalse((self.base / "escape.m4a").exists())

    def test_archive_verification_failure_never_installs_partial_archive(self):
        self.add_file("screenshots/01.png", "screenshot")
        plan = build_preflight(self.project)
        archive = plan.archives[0]
        forged_archive = type(archive)(archive.destination, archive.member_file_ids,
                                       archive.member_names, archive.uncompressed_size + 1,
                                       archive.member_sources)
        forged = ProcessingPlan(plan.output_path, plan.copies, (forged_archive,), (),
                                plan.required_bytes, plan.available_bytes)
        with self.assertRaises(ProcessingError):
            execute_processing_plan(forged)
        self.assertEqual(list(self.output.rglob("*.zip")), [])
        self.assertEqual(list(self.output.rglob(".study-archive-prep-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
