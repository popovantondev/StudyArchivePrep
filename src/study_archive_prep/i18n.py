"""Small deterministic UI catalog for Russian, German, and English."""
from __future__ import annotations

from PySide6.QtCore import QLocale

LANGUAGES = ("ru", "de", "en")
LANGUAGE_LABELS = {"ru": "Русский", "de": "Deutsch", "en": "English"}

CATALOG = {
    "window_title": {
        "ru": "Study Archive Prep",
        "de": "Study Archive Prep",
        "en": "Study Archive Prep",
    },
    "eyebrow": {
        "ru": "ПОДГОТОВКА УЧЕБНЫХ МАТЕРИАЛОВ",
        "de": "LERNMATERIALIEN VORBEREITEN",
        "en": "PREPARE STUDY MATERIALS",
    },
    "headline": {
        "ru": "Подготовим материалы\nв понятном порядке",
        "de": "Lernmaterialien\nübersichtlich vorbereiten",
        "en": "Prepare materials\nin a clear order",
    },
    "intro": {
        "ru": "Соберём файлы по неделям и дням, проверим результат и подготовим порядок для публикации в Telegram.",
        "de": "Materialien nach Wochen und Tagen ordnen, das Ergebnis prüfen und den Ablauf für Telegram vorbereiten.",
        "en": "Organize files by week and day, review the result, and prepare the Telegram posting order.",
    },
    "language": {"ru": "Язык", "de": "Sprache", "en": "Language"},
    "setup_title": {"ru": "Новый учебный проект", "de": "Neues Lernprojekt", "en": "New study project"},
    "setup_hint": {
        "ru": "Выберите папки с материалами и отдельную папку для готового результата.",
        "de": "Wählen Sie Materialordner und einen separaten Ausgabeordner.",
        "en": "Choose folders with materials and a separate folder for the prepared output.",
    },
    "recent_label": {"ru": "Недавние проекты", "de": "Zuletzt verwendete Projekte", "en": "Recent projects"},
    "recent_none": {"ru": "Пока нет сохранённых проектов", "de": "Noch keine gespeicherten Projekte", "en": "No saved projects yet"},
    "open_project": {"ru": "Открыть", "de": "Öffnen", "en": "Open"},
    "sources_label": {"ru": "Исходные папки", "de": "Quellordner", "en": "Source folders"},
    "add_source": {"ru": "Добавить папку", "de": "Ordner hinzufügen", "en": "Add folder"},
    "remove_source": {"ru": "Убрать выбранную", "de": "Ausgewählten entfernen", "en": "Remove selected"},
    "no_sources": {"ru": "Пока не выбраны", "de": "Noch keine ausgewählt", "en": "None selected yet"},
    "output_label": {"ru": "Папка результата", "de": "Ausgabeordner", "en": "Output folder"},
    "choose_output": {"ru": "Выбрать папку…", "de": "Ordner auswählen…", "en": "Choose folder…"},
    "start_date": {"ru": "Первый учебный день", "de": "Erster Kurstag", "en": "First study day"},
    "set_start_date": {"ru": "Указать", "de": "Festlegen", "en": "Set date"},
    "choose_date": {"ru": "Не выбрана", "de": "Nicht ausgewählt", "en": "Not selected"},
    "not_set": {"ru": "Не задана", "de": "Nicht festgelegt", "en": "Not set"},
    "create_project": {"ru": "Создать проект", "de": "Projekt erstellen", "en": "Create project"},
    "project_ready": {
        "ru": "Проект сохранён на этом Mac. Сканирование и подготовка файлов появятся в следующих версиях.",
        "de": "Das Projekt wurde auf diesem Mac gespeichert. Scannen und Vorbereiten der Dateien folgen in späteren Versionen.",
        "en": "The project is saved on this Mac. File scanning and preparation are coming in later versions.",
    },
    "project_loaded": {"ru": "Проект открыт с последнего сохранения.", "de": "Das zuletzt gespeicherte Projekt wurde geöffnet.", "en": "The last saved project was opened."},
    "project_storage_error": {"ru": "Не удалось открыть локальные данные проекта. Проверьте место на диске и права доступа.", "de": "Die lokalen Projektdaten konnten nicht geöffnet werden. Prüfen Sie Speicherplatz und Zugriffsrechte.", "en": "Could not open local project data. Check disk space and folder permissions."},
    "need_source": {
        "ru": "Добавьте хотя бы одну исходную папку.",
        "de": "Fügen Sie mindestens einen Quellordner hinzu.",
        "en": "Add at least one source folder.",
    },
    "need_output": {
        "ru": "Выберите отдельную папку для результата.",
        "de": "Wählen Sie einen separaten Ausgabeordner.",
        "en": "Choose a separate output folder.",
    },
    "need_date": {
        "ru": "Укажите дату первого учебного дня.",
        "de": "Geben Sie das Datum des ersten Kurstags an.",
        "en": "Set the date of the first study day.",
    },
    "source_output_overlap": {
        "ru": "Папка результата не должна находиться внутри исходной папки и наоборот.",
        "de": "Der Ausgabeordner darf weder im Quellordner liegen noch diesen enthalten.",
        "en": "The output folder must not be inside a source folder, and must not contain one.",
    },
    "select_source": {"ru": "Выберите папку с материалами", "de": "Materialordner auswählen", "en": "Choose a folder with materials"},
    "select_destination": {"ru": "Выберите папку результата", "de": "Ausgabeordner auswählen", "en": "Choose an output folder"},
    "next_steps": {"ru": "Следующие шаги", "de": "Nächste Schritte", "en": "Next steps"},
    "next_steps_body": {
        "ru": "1. Сканирование файлов и дат\n2. Проверка недель и комплектов\n3. Подготовка результата и порядка Telegram",
        "de": "1. Dateien und Termine scannen\n2. Wochen und Dateigruppen prüfen\n3. Ergebnis und Telegram-Reihenfolge vorbereiten",
        "en": "1. Scan files and dates\n2. Review weeks and file groups\n3. Prepare output and the Telegram order",
    },
}


def normalize_language(language: str) -> str:
    value = (language or "").casefold().split("-")[0].split("_")[0]
    return value if value in LANGUAGES else "en"


def system_language(locale_name: str | None = None) -> str:
    value = locale_name if locale_name is not None else QLocale.system().name()
    return normalize_language(value)


def tr(key: str, language: str) -> str:
    normalized = normalize_language(language)
    return CATALOG.get(key, {}).get(normalized, CATALOG.get(key, {}).get("en", key))
