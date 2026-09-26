import os
import tempfile
import unittest
from pathlib import Path

from study_archive_prep.scanner import classify_file, scan_sources, suggest_date


class DateSuggestionTests(unittest.TestCase):
    def test_iso_and_european_dates_are_detected_without_partial_date_conflicts(self):
        for path in (("2026-09-22", "lecture.srt"), ("22.09.2026", "lecture.srt"),
                     ("22-09-2026", "lecture.srt")):
            with self.subTest(path=path):
                self.assertEqual(suggest_date(path, 2026).study_date, "2026-09-22")
                self.assertFalse(suggest_date(path, 2026).needs_review)

    def test_yearless_date_uses_the_project_year(self):
        self.assertEqual(suggest_date(("22.09", "video.mkv"), 2026).study_date, "2026-09-22")

    def test_localized_month_name_is_supported(self):
        self.assertEqual(suggest_date(("21.September", "file.srt"), 2026).study_date,
                         "2026-09-21")
        self.assertEqual(suggest_date(("3.August", "file.srt"), 2026).study_date,
                         "2026-08-03")

    def test_week_range_is_not_mistaken_for_a_day(self):
        result = suggest_date(("Неделя 1 03.08 - 08.08", "week.zip"), 2026)
        self.assertIsNone(result.study_date)
        self.assertTrue(result.needs_review)

    def test_ambiguous_numeric_path_requires_review(self):
        result = suggest_date(("03_08.08", "video.mkv"), 2026)
        self.assertIsNone(result.study_date)
        self.assertTrue(result.needs_review)
        self.assertGreaterEqual(len(result.candidates), 1)

    def test_conflicting_components_require_review(self):
        result = suggest_date(("2026-08-03", "2026-08-04", "lecture.srt"), 2026)
        self.assertIsNone(result.study_date)
        self.assertTrue(result.needs_review)

    def test_invalid_or_absent_dates_do_not_get_fabricated(self):
        self.assertIsNone(suggest_date(("31.02", "file.txt"), 2026).study_date)
        self.assertIsNone(suggest_date(("08_26", "file.mkv"), 2026).study_date)
        self.assertIsNone(suggest_date(("file.mkv",), None).study_date)

    def test_german_and_english_week_labels_are_recognized(self):
        for label in ("Woche 4", "Week_4", "4 Woche"):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temporary:
                    source = Path(temporary)
                    target = source / label / "worksheet.pdf"
                    target.parent.mkdir()
                    target.write_bytes(b"sample")
                    self.assertEqual(scan_sources([source]).files[0].week_number, 4)


class SourceScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.source = self.base / "source"
        self.source.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def put(self, relative, content=b"sample"):
        target = self.source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def test_scan_is_read_only_and_keeps_alternative_subtitles(self):
        first = self.put("2026-08-03/recording.mkv")
        one = self.put("2026-08-03/recording.ru.srt", b"one")
        two = self.put("2026-08-03/recording.srt", b"two")
        original_stats = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in (first, one, two)}
        result = scan_sources([self.source], start_date="2026-08-03")
        self.assertEqual(len(result.files), 3)
        self.assertEqual({file.category for file in result.files if file.name.endswith(".srt")}, {"subtitle"})
        self.assertEqual({file.relative_path for file in result.files if file.category == "subtitle"},
                         {"2026-08-03/recording.ru.srt", "2026-08-03/recording.srt"})
        self.assertTrue(all(file.week_number == 1 for file in result.files))
        self.assertEqual(original_stats, {path: (path.stat().st_size, path.stat().st_mtime_ns)
                                          for path in (first, one, two)})

    def test_screenshot_folders_and_archive_names_are_classified(self):
        self.assertEqual(classify_file(("screenshots", "image.jpg"), ".jpg"), "screenshot")
        self.assertEqual(classify_file(("03_Скриншоты.zip",), ".zip"), "screenshot_archive")
        self.assertEqual(classify_file(("04_Дополнительные_материалы.zip",), ".zip"), "extra_archive")
        self.assertEqual(classify_file(("Неделя_01_Материалы_на_неделю.zip",), ".zip"), "study_archive")

    def test_transcript_txt_is_suggested_excluded_and_never_deleted(self):
        media = self.put("2026-08-03/lesson.mkv")
        transcript = self.put("2026-08-03/lesson.txt", b"verbatim transcript")
        result = scan_sources([self.source], year_hint=2026)
        record = next(item for item in result.files if item.name == transcript.name)
        self.assertEqual(record.category, "transcript_candidate")
        self.assertFalse(record.included)
        self.assertTrue(media.exists())
        self.assertTrue(transcript.exists())

    def test_date_anchor_assigns_course_week_and_flags_named_week_conflict(self):
        self.put("Неделя 2/2026-08-03/lesson.mkv")
        result = scan_sources([self.source], start_date="2026-08-03")
        self.assertIsNone(result.files[0].week_number)
        self.assertIn("week_conflict", {issue.code for issue in result.issues})

    def test_date_before_start_date_needs_manual_week_assignment(self):
        self.put("2026-08-02/lesson.mkv")
        result = scan_sources([self.source], start_date="2026-08-03")
        self.assertIsNone(result.files[0].week_number)
        self.assertIn("date_before_course", {issue.code for issue in result.issues})

    def test_system_files_are_excluded_and_symlinks_are_not_followed(self):
        self.put("2026-08-03/.DS_Store")
        self.put("2026-08-03/._hidden")
        real = self.put("2026-08-03/real.mkv")
        link = self.source / "2026-08-03" / "linked.mkv"
        try:
            link.symlink_to(real)
        except OSError:
            self.skipTest("symlinks are unavailable")
        result = scan_sources([self.source], year_hint=2026)
        self.assertEqual([item.name for item in result.files], ["real.mkv"])
        self.assertIn("2026-08-03/.DS_Store", result.excluded_paths)
        self.assertIn("symlink_excluded", {issue.code for issue in result.issues})

    def test_duplicate_roots_are_reported_without_duplicate_files(self):
        self.put("2026-08-03/lesson.mkv")
        result = scan_sources([self.source, self.source], year_hint=2026)
        self.assertEqual(len(result.files), 1)
        self.assertIn("duplicate_root", {issue.code for issue in result.issues})

    def test_file_ids_and_order_are_stable_between_scans(self):
        self.put("2026-08-03/lesson10.mkv")
        self.put("2026-08-03/lesson2.mkv")
        first = scan_sources([self.source], year_hint=2026)
        second = scan_sources([self.source], year_hint=2026)
        self.assertEqual([(file.relative_path, file.id) for file in first.files],
                         [(file.relative_path, file.id) for file in second.files])
        self.assertEqual([file.name for file in first.files], ["lesson2.mkv", "lesson10.mkv"])

    def test_multiple_named_weeks_are_reported_as_conflicting(self):
        self.put("Неделя 1/Woche 2/notes.pdf")
        result = scan_sources([self.source])
        self.assertIsNone(result.files[0].week_number)
        self.assertIn("week_conflict", {issue.code for issue in result.issues})

    def test_named_week_material_without_a_day_is_retained_as_weekly(self):
        self.put("Неделя 3/worksheet.pdf")
        result = scan_sources([self.source])
        self.assertEqual(result.files[0].week_number, 3)
        self.assertIsNone(result.files[0].study_date)
        self.assertNotIn("date_unresolved", {issue.code for issue in result.issues})

    def test_start_date_must_be_valid_iso(self):
        with self.assertRaises(ValueError):
            scan_sources([self.source], start_date="03.08.2026")


if __name__ == "__main__":
    unittest.main()
