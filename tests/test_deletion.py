import hashlib
import tempfile
import unittest
from pathlib import Path

from study_archive_prep.audio import AudioExtractionResult
from study_archive_prep.deletion import (DeletionError, OriginalDeletionReceipt,
                                         delete_verified_originals)
from study_archive_prep.operation_journal import OperationJournal
from study_archive_prep.project import ProjectState


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "recording.mkv"
        self.source.write_bytes(b"original media bytes")
        self.audio = self.base / "recording.m4a"
        self.audio.write_bytes(b"verified extracted audio")
        self.journal = OperationJournal(self.base / "private" / "operations.sqlite3")
        project = ProjectState.create("Course", self.base / "output")
        info = self.source.stat()
        self.receipt = OriginalDeletionReceipt(
            project.id, "10000000-0000-4000-8000-000000000001", str(self.source),
            info.st_size, info.st_mtime_ns, hashlib.sha256(self.source.read_bytes()).hexdigest(),
            str(self.audio), self.audio.stat().st_size,
            hashlib.sha256(self.audio.read_bytes()).hexdigest(), True)

    def tearDown(self):
        self.temp.cleanup()

    def approved(self):
        return [self.source]

    def test_deletion_requires_exact_approved_paths(self):
        with self.assertRaises(DeletionError):
            delete_verified_originals([self.receipt], [], self.journal)
        self.assertTrue(self.source.exists())

    def test_deletion_requires_other_container_exports_to_be_complete(self):
        incomplete = OriginalDeletionReceipt(**{
            **self.receipt.__dict__, "container_exports_complete": False})
        with self.assertRaises(DeletionError):
            delete_verified_originals([incomplete], self.approved(), self.journal)
        self.assertTrue(self.source.exists())

    def test_verified_audio_and_unchanged_original_are_logged_before_deletion(self):
        result = delete_verified_originals([self.receipt], self.approved(), self.journal)
        self.assertEqual(result.deleted_paths, (str(self.source.resolve()),))
        self.assertEqual(result.already_deleted_paths, ())
        self.assertFalse(self.source.exists())
        record_id = self.journal.record_deletion_receipt(self.receipt)
        self.assertEqual(self.journal.deletion_status(record_id), "deleted")
        self.assertTrue(self.audio.exists())

    def test_changed_original_is_left_untouched(self):
        self.source.write_bytes(b"different media bytes")
        with self.assertRaises(DeletionError):
            delete_verified_originals([self.receipt], self.approved(), self.journal)
        self.assertTrue(self.source.exists())

    def test_changed_audio_output_blocks_deletion(self):
        self.audio.write_bytes(b"changed audio")
        with self.assertRaises(DeletionError):
            delete_verified_originals([self.receipt], self.approved(), self.journal)
        self.assertTrue(self.source.exists())

    def test_interruption_after_unlink_is_reconciled_from_persisted_intent(self):
        record_id = self.journal.record_deletion_receipt(self.receipt)
        self.journal.update_deletion(record_id, "deleting")
        self.source.unlink()
        result = delete_verified_originals([self.receipt], self.approved(), self.journal)
        self.assertEqual(result.deleted_paths, ())
        self.assertEqual(result.already_deleted_paths, (str(self.source.resolve()),))
        self.assertEqual(self.journal.deletion_status(record_id), "deleted")

    def test_recreated_file_at_deleted_path_is_never_deleted_again(self):
        record_id = self.journal.record_deletion_receipt(self.receipt)
        self.journal.update_deletion(record_id, "deleted")
        self.source.write_bytes(b"a new file")
        with self.assertRaises(DeletionError):
            delete_verified_originals([self.receipt], self.approved(), self.journal)
        self.assertTrue(self.source.exists())

    def test_extraction_receipt_requires_captured_source_hash(self):
        extraction = AudioExtractionResult(str(self.audio), 0, "aac", 2.0,
                                           self.audio.stat().st_size,
                                           hashlib.sha256(self.audio.read_bytes()).hexdigest(),
                                           self.source.stat().st_size, self.source.stat().st_mtime_ns,
                                           None)
        with self.assertRaises(DeletionError):
            OriginalDeletionReceipt.from_extraction(self.receipt.project_id, self.receipt.source_file_id,
                                                    self.source, extraction,
                                                    container_exports_complete=True)


if __name__ == "__main__":
    unittest.main()
