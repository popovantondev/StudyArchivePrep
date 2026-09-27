import tempfile
import time
import unittest
import json
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from study_archive_prep.project import ProjectState, PublicationBlock, SourceRoot, StudyFile
from study_archive_prep.project_repository import ProjectRepository
from study_archive_prep.operation_journal import OperationJournal, run_journaled_plan
from study_archive_prep.audio import AudioExtractionResult, AudioStream, MediaInfo
from study_archive_prep.preflight import build_preflight
from study_archive_prep.publication import PublicationPlanEditor, build_default_plan
from study_archive_prep.workspace_window import WorkspaceWidget


class WorkspaceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.source.mkdir(); self.output.mkdir()
        self.data = self.root / "private app data"
        self.repository = ProjectRepository(self.data / "projects.sqlite3")

    def tearDown(self):
        if hasattr(self, "widget"):
            self.widget.stop_and_wait()
            self.widget.close()
        self.temporary_directory.cleanup()

    def test_scan_is_read_only_and_saves_source_identity_and_default_tree(self):
        dated = self.source / "2026-08-03"
        dated.mkdir()
        (dated / "Vorlesung.m4a").write_bytes(b"synthetic audio")
        (dated / "Notizen.txt").write_text("synthetic notes", encoding="utf-8")
        root = SourceRoot.create(self.source)
        state = ProjectState.create("Example", self.output, "2026-08-03", (root,))
        state = self.repository.save(state)
        self.widget = WorkspaceWidget(state, self.repository, self.data, "ru", lambda _v: None, lambda: None)
        self._wait_for_scan()
        self.assertEqual(len(self.widget.project.files), 2)
        self.assertTrue(all(item.source_root_id == root.id for item in self.widget.project.files))
        self.assertTrue(self.widget.project.blocks)
        self.assertEqual((dated / "Vorlesung.m4a").read_bytes(), b"synthetic audio")
        reopened = self.repository.load(state.id)
        self.assertEqual(len(reopened.files), 2)

    def test_inclusion_and_rename_edits_are_saved_to_the_project(self):
        media = self.source / "2026-08-03.m4a"
        media.write_bytes(b"synthetic")
        root = SourceRoot.create(self.source)
        file = StudyFile.create(root.id, media.name, media.name, media.stat().st_size,
                                media.stat().st_mtime_ns, study_date="2026-08-03",
                                week_number=1, category="audio_video")
        state = ProjectState.create("Example", self.output, "2026-08-03", (root,))
        state = self.repository.save(replace(state, files=(file,)))
        state = replace(state, blocks=build_default_plan(state).blocks)
        state = self.repository.save(state)
        self.widget = WorkspaceWidget(state, self.repository, self.data, "de", lambda _v: None, lambda: None)
        block = next(item for item in state.blocks if item.kind == "file")
        self.widget.editor.set_included(block.id, False)
        self.widget._save_editor()
        self.widget.editor.rename(block.id, "Geänderte Aufnahme.m4a")
        self.widget._save_editor()
        saved = self.repository.load(state.id)
        self.assertEqual(saved.block(block.id).title, "Geänderte Aufnahme.m4a")
        self.assertFalse(saved.block(block.id).included)
        self.assertEqual(self.widget.language, "de")
        self.assertEqual(self.widget.prepare_button.text(), "Dateien vorbereiten")

    def test_ambiguous_files_remain_visible_outside_publication_blocks(self):
        (self.source / "unbekannt.pdf").write_bytes(b"x")
        root = SourceRoot.create(self.source)
        state = ProjectState.create("Example", self.output, None, (root,))
        state = self.repository.save(state)
        self.widget = WorkspaceWidget(state, self.repository, self.data, "en", lambda _v: None, lambda: None)
        self._wait_for_scan()
        self.assertEqual(len(self.widget.project.files), 1)
        self.assertFalse(any(block.kind == "file" for block in self.widget.project.blocks))
        self.assertIn("Needs assignment", self.widget.tree.topLevelItem(0).text(1))

    def test_background_preparation_and_manifest_export_form_a_complete_local_flow(self):
        media = self.source / "2026-08-03.m4a"
        media.write_bytes(b"synthetic audio payload")
        root = SourceRoot.create(self.source)
        file = StudyFile.create(root.id, media.name, media.name, media.stat().st_size,
                                media.stat().st_mtime_ns, study_date="2026-08-03",
                                week_number=1, category="audio_video")
        state = ProjectState.create("Example", self.output, "2026-08-03", (root,))
        state = self.repository.save(replace(state, files=(file,)))
        state = self.repository.save(replace(state, blocks=build_default_plan(state).blocks))
        self.widget = WorkspaceWidget(state, self.repository, self.data, "en", lambda _v: None, lambda: None)
        plan = build_preflight(state)
        self.widget._processing_plan = plan
        journal = OperationJournal(self.data / "operations.sqlite3")
        self.widget._start_worker(lambda progress: run_journaled_plan(
            state.id, plan, journal, progress=lambda done,total,name: progress(done,total,name)),
            self.widget._processing_finished)
        deadline = time.monotonic() + 5
        while self.widget._thread is not None and time.monotonic() < deadline:
            self.application.processEvents(); time.sleep(0.01)
        self.application.processEvents()
        self.assertIsNone(self.widget._thread)
        manifest_path = self.widget.create_manifest()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["items"][-1]["kind"], "file")
        self.assertEqual(manifest["items"][-1]["name"], media.name)
        self.assertNotIn(str(self.source), manifest_path.read_text(encoding="utf-8"))
        self.assertIn("Preparation complete", self.widget.status.text())

    def test_video_audio_extraction_adds_verified_audio_and_keeps_the_original(self):
        media = self.source / "2026-08-03.mkv"
        media.write_bytes(b"synthetic container")
        root = SourceRoot.create(self.source)
        file = StudyFile.create(root.id, media.name, media.name, media.stat().st_size,
                                media.stat().st_mtime_ns, study_date="2026-08-03",
                                week_number=1, category="audio_video")
        state = ProjectState.create("Example", self.output, "2026-08-03", (root,))
        state = self.repository.save(replace(state, files=(file,)))
        state = self.repository.save(replace(state, blocks=build_default_plan(state).blocks))
        self.widget = WorkspaceWidget(state, self.repository, self.data, "en", lambda _v: None, lambda: None)
        block = next(item for item in state.blocks if item.kind == "file")
        tree_item = next(item for item in self._tree_items(self.widget.tree)
                         if item.data(0, Qt.ItemDataRole.UserRole) == block.id)
        self.widget.tree.setCurrentItem(tree_item)

        stream = AudioStream(0, "aac", 2, 48000, "de", "Lecture", 2.0)
        media_info = MediaInfo(str(media), 2.0, (stream,))
        def fake_extract(source, output_stem, stream_index=None, **kwargs):
            result_path = Path(output_stem).with_suffix(".m4a")
            result_path.write_bytes(b"lossless stream copy")
            info = result_path.stat()
            return AudioExtractionResult(str(result_path), stream_index, "aac", 2.0,
                                         info.st_size, "a" * 64, media.stat().st_size,
                                         media.stat().st_mtime_ns, None)

        with patch("study_archive_prep.workspace_window.probe_media", return_value=media_info), \
             patch("study_archive_prep.workspace_window.extract_audio_lossless", side_effect=fake_extract):
            self.widget.extract_selected_audio()
            deadline = time.monotonic() + 5
            while self.widget._thread is not None and time.monotonic() < deadline:
                self.application.processEvents(); time.sleep(0.01)
            self.application.processEvents()

        self.assertIsNone(self.widget._thread)
        saved = self.repository.load(state.id)
        original_after = next(item for item in saved.files if item.id == file.id)
        self.assertFalse(original_after.included)
        generated = next(item for item in saved.files if item.id != file.id)
        self.assertTrue(generated.included)
        self.assertEqual(Path(saved.roots[-1].path).joinpath(generated.relative_path).read_bytes(),
                         b"lossless stream copy")
        self.assertTrue(media.exists())
        self.assertIn("Original kept", self.widget.status.text())

    def test_tree_reordering_is_saved_to_the_publication_editor(self):
        first = self.source / "2026-08-03.mp4"
        second = self.source / "2026-08-03.srt"
        first.write_bytes(b"video"); second.write_bytes(b"subtitle")
        root = SourceRoot.create(self.source)
        files = tuple(StudyFile.create(root.id, path.name, path.name, path.stat().st_size,
                                       path.stat().st_mtime_ns, study_date="2026-08-03",
                                       week_number=1, category=category)
                      for path, category in ((first, "audio_video"), (second, "subtitle")))
        state = ProjectState.create("Example", self.output, "2026-08-03", (root,))
        state = self.repository.save(replace(state, files=files))
        state = self.repository.save(replace(state, blocks=build_default_plan(state).blocks))
        self.widget = WorkspaceWidget(state, self.repository, self.data, "en", lambda _v: None, lambda: None)
        day = next(item for item in self._tree_items(self.widget.tree)
                   if item.data(0, Qt.ItemDataRole.UserRole) == next(block.id for block in state.blocks if block.kind == "day"))
        moved = day.takeChild(1)
        day.insertChild(0, moved)
        self.widget._sync_tree_order()
        saved = self.repository.load(state.id)
        positions = {block.file_id: block.position for block in saved.blocks if block.kind == "file"}
        self.assertLess(positions[files[1].id], positions[files[0].id])

    @staticmethod
    def _tree_items(tree):
        items = []
        def visit(parent):
            for index in range(parent.childCount()):
                child = parent.child(index); items.append(child); visit(child)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index); items.append(item); visit(item)
        return items

    def _wait_for_scan(self):
        deadline = time.monotonic() + 5
        while self.widget._thread is not None and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.application.processEvents()
        self.assertIsNone(self.widget._thread)
        self.assertTrue(self.widget._scanned)


if __name__ == "__main__":
    unittest.main()
