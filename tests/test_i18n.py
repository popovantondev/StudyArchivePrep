import unittest

from study_archive_prep.i18n import LANGUAGES, normalize_language, system_language, tr
from study_archive_prep.workspace_window import _WORKSPACE_TEXT


class InternationalizationTests(unittest.TestCase):
    def test_supported_catalog_entries_exist_for_every_language(self):
        for language in LANGUAGES:
            self.assertEqual(tr("create_project", language), {
                "ru": "Создать проект",
                "de": "Projekt erstellen",
                "en": "Create project",
            }[language])

    def test_locale_normalization_is_stable_for_common_locale_spellings(self):
        self.assertEqual(normalize_language("de-DE"), "de")
        self.assertEqual(normalize_language("ru_RU"), "ru")
        self.assertEqual(normalize_language("fr_FR"), "en")
        self.assertEqual(system_language("en_US"), "en")

    def test_unknown_translation_key_falls_back_without_crashing(self):
        self.assertEqual(tr("future_key", "ru"), "future_key")

    def test_workspace_actions_are_translated_for_all_supported_languages(self):
        for key, values in _WORKSPACE_TEXT.items():
            self.assertEqual(set(values), set(LANGUAGES), key)
            self.assertTrue(all(value.strip() for value in values.values()), key)


if __name__ == "__main__":
    unittest.main()
