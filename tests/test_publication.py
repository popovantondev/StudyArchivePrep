import tempfile
import unittest
from pathlib import Path

from study_archive_prep.project import ProjectState, PublicationBlock, SourceRoot, StudyFile
from study_archive_prep.publication import PublicationPlanEditor, build_default_plan


class PublicationPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        base = Path(self.temporary_directory.name)
        self.output = base / "output"
        self.output.mkdir()
        self.source = SourceRoot.create(base / "source")
        self.project = ProjectState.create("Course", self.output, "2026-08-03", (self.source,))
        self.week_file = self.make_file("Неделя_01_Материалы_на_неделю.zip", None, 1, "study_archive")
        self.video = self.make_file("lesson.mkv", "2026-08-03", 1, "audio_video")
        self.subtitle = self.make_file("lesson.ru.srt", "2026-08-03", 1, "subtitle")
        self.screenshot = self.make_file("screen.png", "2026-08-03", 1, "screenshot")
        self.other = self.make_file("worksheet.pdf", "2026-08-03", 1, "other")
        self.second_day = self.make_file("notes.pdf", "2026-08-04", 1, "other")
        self.unassigned = self.make_file("unknown.txt", None, None, "other")
        self.project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                                    self.project.start_date, roots=(self.source,),
                                    files=(self.other, self.subtitle, self.week_file, self.video,
                                           self.screenshot, self.second_day, self.unassigned))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_file(self, name, study_date, week, category):
        return StudyFile.create(self.source.id, f"source/{name}", name, 4, 1,
                                study_date=study_date, week_number=week, category=category)

    def test_default_plan_orders_week_material_day_and_files_by_category(self):
        first = build_default_plan(self.project)
        second = build_default_plan(self.project)
        self.assertEqual(first.blocks, second.blocks)
        self.assertEqual(first.unassigned_file_ids, (self.unassigned.id,))
        week = first.blocks[0]
        self.assertEqual(week.kind, "week")
        self.assertEqual(week.title, "Неделя 1 03.08 - 04.08")
        children = sorted((block for block in first.blocks if block.parent_id == week.id),
                          key=lambda block: block.position)
        self.assertEqual([block.file_id for block in children[:1]], [self.week_file.id])
        self.assertEqual(children[1].kind, "day")
        first_day = children[1]
        files = sorted((block for block in first.blocks if block.parent_id == first_day.id),
                       key=lambda block: block.position)
        self.assertEqual([block.file_id for block in files],
                         [self.video.id, self.subtitle.id, self.screenshot.id, self.other.id])
        self.assertEqual(children[2].study_date, "2026-08-04")

    def test_default_plan_keeps_excluded_suggestions_visible_and_excluded(self):
        excluded = StudyFile.create(self.source.id, "source/talk.txt", "talk.txt", 4, 1,
                                    study_date="2026-08-03", week_number=1,
                                    category="transcript_candidate", included=False)
        project = ProjectState(self.project.id, self.project.name, self.project.output_path,
                               self.project.start_date, roots=(self.source,),
                               files=(*self.project.files, excluded))
        plan = build_default_plan(project)
        linked = next(block for block in plan.blocks if block.file_id == excluded.id)
        self.assertFalse(linked.included)


class PublicationEditorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        output = base / "output"
        output.mkdir()
        source = SourceRoot.create(base / "source")
        project = ProjectState.create("Course", output, "2026-08-03", (source,))
        week1 = PublicationBlock.create("week", "Week 1", 0)
        week2 = PublicationBlock.create("week", "Week 2", 1)
        day1 = PublicationBlock.create("day", "2026-08-03", 0,
                                       parent_id=week1.id, study_date="2026-08-03")
        day2 = PublicationBlock.create("day", "2026-08-04", 1,
                                       parent_id=week1.id, study_date="2026-08-04")
        day3 = PublicationBlock.create("day", "2026-08-10", 0,
                                       parent_id=week2.id, study_date="2026-08-10")
        media = StudyFile.create(source.id, "a.mkv", "a.mkv", 1, 1)
        file1 = PublicationBlock.create("file", media.name, 0, parent_id=day1.id, file_id=media.id)
        project = ProjectState(project.id, project.name, project.output_path, project.start_date,
                               roots=(source,), files=(media,),
                               blocks=(week1, week2, day1, day2, day3, file1))
        self.editor = PublicationPlanEditor(project)
        self.week1, self.week2 = week1, week2
        self.day1, self.day2, self.day3 = day1, day2, day3
        self.file1 = file1

    def test_move_reorders_siblings_and_undo_redo_restores_exact_snapshots(self):
        before = self.editor.project
        self.editor.move(self.day2.id, self.week1.id, 0)
        moved = self.editor.project
        self.assertEqual(moved.block(self.day2.id).position, 0)
        self.assertEqual(moved.block(self.day1.id).position, 1)
        self.assertTrue(self.editor.can_undo)
        self.assertEqual(self.editor.undo(), before)
        self.assertTrue(self.editor.can_redo)
        self.assertEqual(self.editor.redo(), moved)

    def test_moving_a_day_keeps_its_files_attached(self):
        self.editor.move(self.day1.id, self.week2.id, 1)
        state = self.editor.project
        self.assertEqual(state.block(self.day1.id).parent_id, self.week2.id)
        self.assertEqual(state.block(self.file1.id).parent_id, self.day1.id)
        self.assertEqual(state.block(self.day1.id).position, 1)

    def test_file_can_move_between_days_and_week_materials(self):
        self.editor.move(self.file1.id, self.week1.id, 0)
        self.assertEqual(self.editor.project.block(self.file1.id).parent_id, self.week1.id)
        self.editor.move(self.file1.id, self.day2.id, 0)
        self.assertEqual(self.editor.project.block(self.file1.id).parent_id, self.day2.id)

    def test_text_rename_and_inclusion_are_undoable(self):
        text = self.editor.add_text(self.week1.id, "Материалы на неделю")
        self.assertEqual(self.editor.project.block(text.id).text, "Материалы на неделю")
        self.editor.rename(text.id, "Обновлённое сообщение")
        self.editor.set_included(text.id, False)
        self.assertFalse(self.editor.project.block(text.id).included)
        self.editor.undo()
        self.assertTrue(self.editor.project.block(text.id).included)
        self.editor.undo()
        self.assertEqual(self.editor.project.block(text.id).text, "Материалы на неделю")

    def test_new_edit_after_undo_discards_redo_history(self):
        self.editor.rename(self.week1.id, "Renamed")
        self.editor.undo()
        self.editor.rename(self.week2.id, "Other")
        self.assertFalse(self.editor.can_redo)

    def test_invalid_moves_are_rejected_without_changing_the_project(self):
        before = self.editor.project
        with self.assertRaises(ValueError):
            self.editor.move(self.day1.id, self.day2.id, 0)
        with self.assertRaises(ValueError):
            self.editor.move(self.week1.id, self.week2.id, 0)
        self.assertEqual(self.editor.project, before)


if __name__ == "__main__":
    unittest.main()
