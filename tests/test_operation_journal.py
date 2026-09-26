import os
import stat
import tempfile
import unittest
from pathlib import Path

from study_archive_prep.operation_journal import JournalError, OperationJournal, run_journaled_plan
from study_archive_prep.preflight import build_preflight
from study_archive_prep.processor import execute_processing_plan
from study_archive_prep.project import ProjectState, SourceRoot, StudyFile
from study_archive_prep.publication import build_default_plan


class OperationJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source_dir = self.base / "source"
        self.source_dir.mkdir()
        self.output = self.base / "prepared"
        self.root = SourceRoot.create(self.source_dir)
        self.project = ProjectState.create("Private course", self.output, "2026-08-03", (self.root,))
        self.journal_path = self.base / "private" / "operations.sqlite3"
        self.journal = OperationJournal(self.journal_path)

    def tearDown(self):
        self.temporary.cleanup()

    def add_file(self, name):
        path = self.source_dir / name
        path.write_bytes(("payload-" + name).encode())
        info = path.stat()
        record = StudyFile.create(self.root.id, name, name, info.st_size, info.st_mtime_ns,
                                  study_date="2026-08-03", week_number=1, category="audio_video")
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,),
                                    files=(*self.project.files, record))
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,), files=self.project.files,
                                    blocks=build_default_plan(self.project).blocks)
        return path, record

    def test_processing_receipt_is_durable_and_second_run_verifies_then_skips(self):
        self.add_file("lesson.m4a")
        plan = build_preflight(self.project)
        first = run_journaled_plan(self.project.id, plan, self.journal)
        self.assertEqual(len(first.outputs), 1)
        self.assertEqual(len(first.skipped_completed), 0)
        records = self.journal.entries(first.plan_id)
        self.assertEqual(records[0].status, "completed")
        self.assertEqual(len(records[0].output_sha256), 64)
        reopened = OperationJournal(self.journal_path)
        second = run_journaled_plan(self.project.id, build_preflight(self.project), reopened)
        self.assertEqual(second.plan_id, first.plan_id)
        self.assertEqual(second.outputs, ())
        self.assertEqual(second.skipped_completed, (records[0].destination,))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.journal_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.journal_path.parent.stat().st_mode), 0o700)

    def test_cancel_after_one_operation_resumes_without_repeating_completed_output(self):
        self.add_file("a.m4a")
        self.add_file("b.m4a")
        plan = build_preflight(self.project)
        calls = 0

        def cancel_after_first():
            nonlocal calls
            calls += 1
            return calls >= 5

        with self.assertRaises(Exception):
            run_journaled_plan(self.project.id, plan, self.journal, cancelled=cancel_after_first)
        plan_id = self.journal.prepare(self.project.id, plan)
        before = self.journal.entries(plan_id)
        self.assertEqual([entry.status for entry in before].count("completed"), 1)
        self.assertEqual([entry.status for entry in before].count("interrupted"), 1)
        resumed = run_journaled_plan(self.project.id, build_preflight(self.project), self.journal)
        self.assertEqual(len(resumed.skipped_completed), 1)
        self.assertEqual(len(resumed.outputs), 1)
        self.assertTrue(all(entry.status == "completed" for entry in self.journal.entries(plan_id)))

    def test_crash_after_install_before_journal_ack_is_reconciled_by_hash(self):
        source, item = self.add_file("lesson.m4a")
        plan = build_preflight(self.project)
        plan_id = self.journal.prepare(self.project.id, plan)
        entry = self.journal.entries(plan_id)[0]
        single = type(plan)(plan.output_path, plan.copies, (), (), item.size,
                            plan.available_bytes)
        execute_processing_plan(single)
        self.journal.update(entry.id, "in_progress")
        resumed = run_journaled_plan(self.project.id, build_preflight(self.project), self.journal)
        self.assertEqual(resumed.skipped_completed, (entry.destination,))
        self.assertEqual(self.journal.entries(plan_id)[0].status, "completed")
        self.assertTrue(source.exists())

    def test_incomplete_recorded_temp_file_is_removed_before_retry(self):
        self.add_file("lesson.m4a")
        plan = build_preflight(self.project)
        plan_id = self.journal.prepare(self.project.id, plan)
        entry = self.journal.entries(plan_id)[0]
        temp = self.output / Path(entry.destination).parent / ".study-archive-prep-crash.tmp"
        temp.parent.mkdir(parents=True)
        temp.write_bytes(b"incomplete")
        self.journal.update(entry.id, "interrupted", temp_path=str(temp))
        result = run_journaled_plan(self.project.id, build_preflight(self.project), self.journal)
        self.assertFalse(temp.exists())
        self.assertEqual(len(result.outputs), 1)

    def test_completed_output_mutation_blocks_resume_and_is_left_untouched(self):
        self.add_file("lesson.m4a")
        first = run_journaled_plan(self.project.id, build_preflight(self.project), self.journal)
        entry = self.journal.entries(first.plan_id)[0]
        output = self.output / entry.destination
        output.write_bytes(b"changed after completion")
        with self.assertRaises(JournalError):
            run_journaled_plan(self.project.id, build_preflight(self.project), self.journal)
        self.assertEqual(output.read_bytes(), b"changed after completion")
        self.assertEqual(self.journal.entries(first.plan_id)[0].status, "needs_attention")

    def test_untracked_existing_output_is_never_claimed_or_overwritten(self):
        _, item = self.add_file("lesson.m4a")
        plan = build_preflight(self.project)
        output = self.output / plan.copies[0].destination
        output.parent.mkdir(parents=True)
        output.write_bytes(b"user file")
        with self.assertRaises(JournalError):
            run_journaled_plan(self.project.id, build_preflight(self.project), self.journal)
        self.assertEqual(output.read_bytes(), b"user file")
        entry = self.journal.entries(self.journal.prepare(self.project.id, plan))[0]
        self.assertEqual(entry.status, "needs_attention")

    def test_journal_refuses_unknown_future_schema(self):
        self.add_file("lesson.m4a")
        self.journal.prepare(self.project.id, build_preflight(self.project))
        import sqlite3
        connection = sqlite3.connect(self.journal_path)
        connection.execute("PRAGMA user_version=777")
        connection.close()
        with self.assertRaisesRegex(JournalError, "newer app version"):
            self.journal.entries("not-used")


if __name__ == "__main__":
    unittest.main()
