import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from study_archive_prep.preflight import build_preflight
from study_archive_prep.project import ProjectState, PublicationBlock, SourceRoot, StudyFile
from study_archive_prep.publication_manifest import (
    FORMAT,
    PublicationManifestError,
    build_publication_manifest,
    serialize_publication_manifest,
    write_publication_manifest,
)


class PublicationManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.source_path = self.base / "source-private-name"
        self.source_path.mkdir()
        self.output = self.base / "output"
        self.root = SourceRoot.create(self.source_path)
        self.project = ProjectState.create("Synthetic course", self.output, "2026-08-03", (self.root,))
        self.media = self.add_source("lecture.mkv", "audio_video")
        self.srt1 = self.add_source("lecture.ru.srt", "subtitle")
        self.srt2 = self.add_source("lecture.srt", "subtitle")
        self.screen = self.add_source("screenshots/page1.png", "screenshot")
        self.extra = self.add_source("worksheet.pdf", "other")
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.root,),
                                    files=(self.media, self.srt1, self.srt2, self.screen, self.extra))
        week = PublicationBlock.create("week", "Неделя 1 03.08 - 03.08", 0)
        day = PublicationBlock.create("day", "2026-08-03", 0, parent_id=week.id,
                                      study_date="2026-08-03")
        media_block = PublicationBlock.create("file", self.media.name, 0,
                                              parent_id=day.id, file_id=self.media.id)
        ru_block = PublicationBlock.create("file", self.srt1.name, 1,
                                           parent_id=day.id, file_id=self.srt1.id)
        srt_block = PublicationBlock.create("file", self.srt2.name, 2,
                                            parent_id=day.id, file_id=self.srt2.id)
        screenshot_block = PublicationBlock.create("file", self.screen.name, 3,
                                                   parent_id=day.id, file_id=self.screen.id)
        extra_block = PublicationBlock.create("file", self.extra.name, 4,
                                              parent_id=day.id, file_id=self.extra.id)
        note = PublicationBlock.create("text", "Дополнительная заметка", 5,
                                       parent_id=day.id, text="Дополнительная заметка")
        self.blocks = (week, day, media_block, ru_block, srt_block,
                       screenshot_block, extra_block, note)
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=self.project.roots,
                                    files=self.project.files, blocks=self.blocks)
        self.processing_plan = build_preflight(self.project)
        self._create_prepared_outputs()

    def tearDown(self):
        self.temporary.cleanup()

    def add_source(self, relative, category):
        path = self.source_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("fixture:" + relative).encode())
        stat = path.stat()
        return StudyFile.create(self.root.id, relative, path.name, stat.st_size, stat.st_mtime_ns,
                                study_date="2026-08-03", week_number=1, category=category)

    def _create_prepared_outputs(self):
        for copy in self.processing_plan.copies:
            source = Path(copy.source_path)
            target = self.output / copy.destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        for archive in self.processing_plan.archives:
            target = self.output / archive.destination
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as stream:
                for member in archive.member_sources:
                    stream.write(member.source_path, member.destination)

    def test_manifest_order_and_digest_bind_to_prepared_outputs(self):
        result = build_publication_manifest(self.project, 7, self.processing_plan)
        items = result["items"]
        self.assertEqual([item["kind"] for item in items],
                         ["text", "text", "file", "file", "file", "file", "file", "text"])
        self.assertEqual(items[0]["text"], "Неделя 1 03.08 - 03.08")
        self.assertEqual(items[1]["text"], "2026-08-03")
        files = [item for item in items if item["kind"] == "file"]
        self.assertEqual([item["name"] for item in files], [
            "lecture.mkv", "lecture.ru.srt", "lecture.srt",
            "03_Скриншоты.zip", "04_Дополнительные_материалы.zip",
        ])
        for item in files:
            data = (self.output / item["path"]).read_bytes()
            self.assertEqual(item["size"], len(data))
            self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(item["week"], 1)
            self.assertEqual(item["date"], "2026-08-03")
        self.assertEqual(items[-1]["text"], "Дополнительная заметка")

    def test_manifest_omits_absolute_roots_subtitle_text_and_local_metadata(self):
        manifest = build_publication_manifest(self.project, 1, self.processing_plan)
        encoded = serialize_publication_manifest(manifest).decode("utf-8")
        self.assertNotIn(str(self.source_path), encoded)
        self.assertNotIn("fixture:lecture", encoded)
        self.assertNotIn("mtime", encoded)
        self.assertNotIn("token", encoded.casefold())
        self.assertEqual(manifest["format"], FORMAT)
        self.assertEqual(manifest["project_id"], self.project.id)
        self.assertEqual(manifest["revision"], 1)
        self.assertEqual(json.loads(encoded)["items"], manifest["items"])

    def test_serialization_is_deterministic_and_utf8(self):
        manifest = build_publication_manifest(self.project, 3, self.processing_plan)
        self.assertEqual(serialize_publication_manifest(manifest),
                         serialize_publication_manifest(manifest))
        self.assertIn("Неделя".encode(), serialize_publication_manifest(manifest))

    def test_missing_or_unsafe_output_fails_closed(self):
        target = self.output / self.processing_plan.copies[0].destination
        target.unlink()
        with self.assertRaisesRegex(PublicationManifestError, "missing"):
            build_publication_manifest(self.project, 1, self.processing_plan)

    def test_plan_revision_must_be_positive_and_integer(self):
        for revision in (0, -1, True, "1"):
            with self.subTest(revision=revision), self.assertRaises(PublicationManifestError):
                build_publication_manifest(self.project, revision, self.processing_plan)

    def test_write_is_atomic_and_never_overwrites_an_existing_plan(self):
        written = write_publication_manifest(self.project, 4, self.processing_plan)
        self.assertEqual(written, self.output.resolve() / "publication-plan.json")
        decoded = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(decoded["revision"], 4)
        with self.assertRaises(FileExistsError):
            write_publication_manifest(self.project, 5, self.processing_plan)
        self.assertEqual(json.loads(written.read_text(encoding="utf-8"))["revision"], 4)


if __name__ == "__main__":
    unittest.main()
