import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from study_archive_prep.main_window import MainWindow


class SetupWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.settings_path = self.root / "settings"
        self.settings = QSettings(str(self.settings_path / "app.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow("ru", self.settings)

    def tearDown(self):
        self.window.close()
        self.temporary_directory.cleanup()

    def test_start_screen_has_a_real_folder_setup_flow(self):
        self.assertIn("Study Archive Prep", self.window.windowTitle())
        self.assertEqual(self.window.create_button.text(), "Создать проект")
        self.assertTrue(self.window.add_button.isEnabled())
        self.assertTrue(self.window.output_button.isEnabled())

    def test_user_can_switch_the_interface_language(self):
        self.window.language_picker.setCurrentIndex(1)
        self.assertEqual(self.window.language, "de")
        self.assertEqual(self.window.create_button.text(), "Projekt erstellen")
        self.assertEqual(self.settings.value("language"), "de")

    def test_missing_required_paths_are_explained_in_the_selected_language(self):
        self.window._create_project()
        self.assertIn("исходную папку", self.window.status.text())
        self.window.source_paths = [self.root / "source"]
        self.window._create_project()
        self.assertIn("папку для результата", self.window.status.text())

    def test_source_and_destination_must_not_overlap(self):
        source = self.root / "source"
        destination = source / "output"
        self.window.source_paths = [source]
        self.window.output_path = destination
        self.window.date_enabled.setChecked(True)
        self.window._create_project()
        self.assertIn("не должна находиться внутри", self.window.status.text())

    def test_valid_folder_selection_reaches_a_clear_ready_state(self):
        source = self.root / "source"
        destination = self.root / "output"
        source.mkdir()
        destination.mkdir()
        self.window.source_paths = [source]
        self.window.output_path = destination
        self.window.date_enabled.setChecked(True)
        self.window._create_project()
        self.assertIn("Настройки проекта готовы", self.window.status.text())


if __name__ == "__main__":
    unittest.main()
