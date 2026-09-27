import tempfile
import unittest
from pathlib import Path

from study_archive_prep.titles import (
    SubtitleExcerpt,
    apply_output_name_proposal,
    build_title_prompt,
    extract_srt_excerpt,
    linked_output_names,
    sanitize_russian_title,
    suggest_title,
)
from study_archive_prep.local_model import GenerationResult


class SubtitleExcerptTests(unittest.TestCase):
    def test_first_five_and_ten_minutes_keep_only_eligible_cues(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.ru.srt"
            path.write_text(
                "1\n00:00:02,000 --> 00:00:04,000\n\ufeffWillkommen zur Lektion.\n\n"
                "2\n00:06:00,000 --> 00:06:02,000\nThe second section.\n\n"
                "3\n00:11:00,000 --> 00:11:02,000\nThis is outside.\n", encoding="utf-8")
            five = extract_srt_excerpt(path, 5)
            ten = extract_srt_excerpt(path, 10)
            self.assertIn("Willkommen zur Lektion", five.text)
            self.assertNotIn("second section", five.text)
            self.assertIn("second section", ten.text)
            self.assertNotIn("outside", ten.text)
            self.assertTrue(five.truncated)
            self.assertEqual(five.included_cues, 1)
            self.assertEqual(ten.included_cues, 2)

    def test_srt_html_and_formatting_markup_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:01,000\n"
                            "<i>Heute</i> {\\an8}lernen wir <b>Kräuter</b>.\n",
                            encoding="utf-8")
            excerpt = extract_srt_excerpt(path, 5)
            self.assertEqual(excerpt.text, "Heute lernen wir Kräuter.")

    def test_unsupported_window_and_empty_srt_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "empty.srt"
            path.write_text("not a subtitle", encoding="utf-8")
            self.assertEqual(extract_srt_excerpt(path).text, "")
            with self.assertRaises(ValueError):
                extract_srt_excerpt(path, 7)

    def test_excerpt_is_bounded_to_configured_character_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "long.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:01,000\n" + "Lektion " * 80,
                            encoding="utf-8")
            excerpt = extract_srt_excerpt(path, max_characters=100)
            self.assertLessEqual(len(excerpt.text), 100)
            self.assertTrue(excerpt.truncated)


class TitleProposalTests(unittest.TestCase):
    def test_prompt_contains_only_excerpt_and_title_constraints(self):
        prompt = build_title_prompt(SubtitleExcerpt("Pflanzen und ihre Wirkung", 1, 300, False),
                                    source_language="de")
        self.assertIn("короткое русское название", prompt)
        self.assertIn("переведи смысл на русский", prompt.casefold())
        self.assertIn("2–7 слов", prompt)
        self.assertIn("Pflanzen und ihre Wirkung", prompt)
        self.assertIn("Язык субтитров: de", prompt)

    def test_empty_excerpt_is_not_sent_to_model(self):
        with self.assertRaises(ValueError):
            build_title_prompt(SubtitleExcerpt("", 0, 600, False))

    def test_safe_short_russian_title_normalization(self):
        self.assertEqual(sanitize_russian_title("Предложенное название: «Мазь из листьев подорожника.»"),
                         "Мазь из листьев подорожника")
        self.assertIsNone(sanitize_russian_title("How plants heal"))
        self.assertIsNone(sanitize_russian_title("Wundsalbe из подорожника"))
        self.assertIsNone(sanitize_russian_title("Одно"))
        self.assertIsNone(sanitize_russian_title("Название\nи второй ответ"))
        self.assertIsNone(sanitize_russian_title("Мазь / опасный путь"))

    def test_related_variant_names_are_proposed_without_touching_inputs(self):
        files = (Path("Kräuter.ru.srt"), Path("Kräuter.srt"),
                 Path("Kräuter_720p.mp4"), Path("Kräuter.m4a"))
        proposed = linked_output_names(files, "Мазь из подорожника")
        self.assertEqual(proposed, (
            ("Kräuter.ru.srt", "Мазь из подорожника ru.srt"),
            ("Kräuter.srt", "Мазь из подорожника.srt"),
            ("Kräuter_720p.mp4", "Мазь из подорожника 720p.mp4"),
            ("Kräuter.m4a", "Мазь из подорожника.m4a"),
        ))
        self.assertEqual(tuple(path.name for path in files),
                         ("Kräuter.ru.srt", "Kräuter.srt", "Kräuter_720p.mp4", "Kräuter.m4a"))

    def test_ambiguous_file_sets_are_not_renamed(self):
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            linked_output_names((Path("Lecture-A.srt"), Path("Lecture-B.mp4")), "Название лекции")

    def test_user_approved_rename_only_changes_prepared_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            source = Path(temporary) / "source"
            output.mkdir()
            source.mkdir()
            (output / "lesson.ru.srt").write_text("prepared SRT", encoding="utf-8")
            (output / "lesson.mp4").write_bytes(b"prepared video")
            (source / "lesson.ru.srt").write_text("original SRT", encoding="utf-8")
            names = (("lesson.ru.srt", "Название лекции ru.srt"),
                     ("lesson.mp4", "Название лекции.mp4"))
            installed = apply_output_name_proposal(output, names, approved_names=names)
            self.assertEqual([path.name for path in installed],
                             ["Название лекции ru.srt", "Название лекции.mp4"])
            self.assertEqual((source / "lesson.ru.srt").read_text(encoding="utf-8"), "original SRT")
            self.assertFalse((output / "lesson.ru.srt").exists())
            self.assertEqual(installed[0].read_text(encoding="utf-8"), "prepared SRT")

    def test_rename_requires_exact_approval_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "old.srt").write_text("prepared", encoding="utf-8")
            (output / "new.srt").write_text("keep", encoding="utf-8")
            names = (("old.srt", "new.srt"),)
            with self.assertRaisesRegex(ValueError, "exact"):
                apply_output_name_proposal(output, names, approved_names=())
            with self.assertRaises(FileExistsError):
                apply_output_name_proposal(output, names, approved_names=names)
            self.assertEqual((output / "old.srt").read_text(encoding="utf-8"), "prepared")
            self.assertEqual((output / "new.srt").read_text(encoding="utf-8"), "keep")

    def test_suggestion_returns_proposals_only_and_keeps_srt_untouched(self):
        class FakeRunner:
            def generate(self, prompt, **_kwargs):
                self.prompt = prompt
                return GenerationResult("Мазь из листьев подорожника", 0.2, "pinned-revision")

        with tempfile.TemporaryDirectory() as temporary:
            srt = Path(temporary) / "lesson.ru.srt"
            original = "1\n00:00:00,000 --> 00:00:02,000\nSpitzwegerich und Salbe.\n"
            srt.write_text(original, encoding="utf-8")
            runner = FakeRunner()
            proposal = suggest_title(srt, runner, minutes=5,
                                     related_files=[srt, srt.with_name("lesson.mp4")])
            self.assertEqual(proposal.title, "Мазь из листьев подорожника")
            self.assertEqual(proposal.model_revision, "pinned-revision")
            self.assertEqual(srt.read_text(encoding="utf-8"), original)
            self.assertEqual(proposal.output_names[0][1], "Мазь из листьев подорожника ru.srt")
            self.assertEqual(proposal.output_names[1][1], "Мазь из листьев подорожника.mp4")


if __name__ == "__main__":
    unittest.main()
