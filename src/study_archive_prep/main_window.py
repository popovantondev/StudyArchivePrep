"""Project setup window used as the first screen of Study Archive Prep."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QSettings
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)

from .i18n import LANGUAGES, LANGUAGE_LABELS, tr
from .project import ProjectState, SourceRoot
from .project_repository import ProjectRepository, ProjectStorageError


STYLE = """
QMainWindow, QWidget#page { background: #eef2f9; color: #183451; }
QFrame#card { background: #ffffff; border: 1px solid #dce5f1; border-radius: 18px; }
QLabel#eyebrow { color: #3374c4; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#headline { color: #183451; font-size: 29px; font-weight: 700; }
QLabel#body, QLabel#muted { color: #687f9b; font-size: 13px; }
QLabel#section { color: #1b3655; font-size: 15px; font-weight: 650; }
QPushButton { color: #1d4775; background: #edf4fd; border: 1px solid #d5e3f5; border-radius: 10px; padding: 9px 13px; font-weight: 600; }
QPushButton:hover { background: #e4eefb; border-color: #b7cdeb; }
QPushButton:pressed { background: #dce9f8; }
QPushButton#primary { color: white; background: #2e70bb; border: 0; padding: 11px 18px; }
QPushButton#primary:hover { background: #245f9f; }
QPushButton:disabled { color: #91a0b4; background: #f2f4f8; border-color: #e4e8ef; }
QComboBox, QDateEdit { color: #183451; background: #fff; border: 1px solid #d7e2ef; border-radius: 9px; padding: 7px 10px; }
QComboBox QAbstractItemView { background: #fff; selection-background-color: #e7f0fb; }
QListWidget { color: #183451; background: #fbfcfe; border: 1px solid #e3e9f1; border-radius: 11px; padding: 5px; }
QListWidget::item { padding: 8px 7px; border-radius: 6px; }
QListWidget::item:selected { color: #183451; background: #e5effb; }
"""


class MainWindow(QMainWindow):
    def __init__(self, language: str, settings: QSettings,
                 repository: ProjectRepository | None = None):
        super().__init__()
        self.settings = settings
        self.repository = repository or ProjectRepository()
        self.data_directory = self.repository.database_path.parent
        self.language = language if language in LANGUAGES else "en"
        self._current_project: ProjectState | None = None
        self.source_paths: list[Path] = []
        self.output_path: Path | None = None
        self.setWindowTitle(tr("window_title", self.language))
        self.resize(1060, 760)
        self.setMinimumSize(820, 640)
        self.setStyleSheet(STYLE)
        self.about_action = QAction(self)
        self.about_action.triggered.connect(self._show_about)
        self.menuBar().addAction(self.about_action)
        self._build_ui()
        self._setup_page = self.centralWidget()
        self._pages = QStackedWidget()
        self._pages.addWidget(self._setup_page)
        self.setCentralWidget(self._pages)
        self._workspace = None
        self._restore_window()

    def _text(self, key: str) -> str:
        return tr(key, self.language)

    def _build_ui(self) -> None:
        page = QWidget()
        page.setObjectName("page")
        root = QVBoxLayout(page)
        root.setContentsMargins(34, 24, 34, 28)
        root.setSpacing(17)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addStretch(1)
        language_label = QLabel(self._text("language"))
        language_label.setObjectName("muted")
        top.addWidget(language_label)
        self.language_picker = QComboBox()
        for code in LANGUAGES:
            self.language_picker.addItem(LANGUAGE_LABELS[code], code)
        self.language_picker.setCurrentIndex(LANGUAGES.index(self.language))
        self.language_picker.currentIndexChanged.connect(self._language_changed)
        self.language_picker.setAccessibleName(self._text("language"))
        top.addWidget(self.language_picker)
        root.addLayout(top)

        intro = QFrame()
        intro.setObjectName("card")
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(25, 22, 25, 21)
        intro_layout.setSpacing(9)
        self.eyebrow = QLabel()
        self.eyebrow.setObjectName("eyebrow")
        intro_layout.addWidget(self.eyebrow)
        self.headline = QLabel()
        self.headline.setObjectName("headline")
        headline_font = QFont(self.headline.font())
        headline_font.setWeight(QFont.Weight.Bold)
        self.headline.setFont(headline_font)
        intro_layout.addWidget(self.headline)
        self.intro = QLabel()
        self.intro.setObjectName("body")
        self.intro.setWordWrap(True)
        self.intro.setMaximumWidth(760)
        intro_layout.addWidget(self.intro)
        root.addWidget(intro)

        content = QHBoxLayout()
        content.setSpacing(16)
        setup = QFrame()
        setup.setObjectName("card")
        setup_layout = QVBoxLayout(setup)
        setup_layout.setContentsMargins(22, 20, 22, 22)
        setup_layout.setSpacing(12)
        self.setup_title = QLabel()
        self.setup_title.setObjectName("section")
        setup_layout.addWidget(self.setup_title)
        self.setup_hint = QLabel()
        self.setup_hint.setObjectName("muted")
        self.setup_hint.setWordWrap(True)
        setup_layout.addWidget(self.setup_hint)

        recent_header = QHBoxLayout()
        self.recent_label = QLabel()
        self.recent_label.setObjectName("section")
        recent_header.addWidget(self.recent_label)
        recent_header.addStretch(1)
        self.recent_picker = QComboBox()
        self.recent_picker.setMinimumWidth(180)
        recent_header.addWidget(self.recent_picker)
        self.open_button = QPushButton()
        self.open_button.clicked.connect(self._open_selected_project)
        recent_header.addWidget(self.open_button)
        setup_layout.addLayout(recent_header)

        sources_header = QHBoxLayout()
        self.sources_label = QLabel()
        self.sources_label.setObjectName("section")
        sources_header.addWidget(self.sources_label)
        sources_header.addStretch(1)
        self.add_button = QPushButton()
        self.add_button.clicked.connect(self._add_source)
        sources_header.addWidget(self.add_button)
        setup_layout.addLayout(sources_header)

        self.sources_list = QListWidget()
        self.sources_list.setMinimumHeight(128)
        self.sources_list.setAccessibleName(self._text("sources_label"))
        setup_layout.addWidget(self.sources_list, 1)
        self.remove_button = QPushButton()
        self.remove_button.clicked.connect(self._remove_source)
        setup_layout.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignLeft)

        output_header = QHBoxLayout()
        self.output_label = QLabel()
        self.output_label.setObjectName("section")
        output_header.addWidget(self.output_label)
        output_header.addStretch(1)
        self.output_button = QPushButton()
        self.output_button.clicked.connect(self._choose_output)
        output_header.addWidget(self.output_button)
        setup_layout.addLayout(output_header)
        self.output_value = QLabel()
        self.output_value.setObjectName("muted")
        self.output_value.setWordWrap(True)
        self.output_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        setup_layout.addWidget(self.output_value)

        date_row = QHBoxLayout()
        self.date_label = QLabel()
        self.date_label.setObjectName("section")
        date_row.addWidget(self.date_label)
        self.start_date = QDateEdit(QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setMinimumDate(QDate(2000, 1, 1))
        self.start_date.setMaximumDate(QDate(2100, 12, 31))
        self.start_date.setEnabled(False)
        self.start_date.setAccessibleName(self._text("start_date"))
        self.date_enabled = QCheckBox()
        self.date_enabled.toggled.connect(self.start_date.setEnabled)
        self.date_enabled.setAccessibleName(self._text("start_date"))
        date_row.addWidget(self.date_enabled)
        date_row.addWidget(self.start_date)
        date_row.addStretch(1)
        setup_layout.addLayout(date_row)

        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(40)
        setup_layout.addWidget(self.status)
        self.create_button = QPushButton()
        self.create_button.setObjectName("primary")
        self.create_button.clicked.connect(self._create_project)
        self.create_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        setup_layout.addWidget(self.create_button, 0, Qt.AlignmentFlag.AlignRight)
        content.addWidget(setup, 3)

        steps = QFrame()
        steps.setObjectName("card")
        steps.setMaximumWidth(286)
        steps_layout = QVBoxLayout(steps)
        steps_layout.setContentsMargins(19, 20, 19, 20)
        steps_layout.setSpacing(13)
        self.steps_title = QLabel()
        self.steps_title.setObjectName("section")
        steps_layout.addWidget(self.steps_title)
        self.steps_body = QLabel()
        self.steps_body.setObjectName("muted")
        self.steps_body.setWordWrap(True)
        self.steps_body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        steps_layout.addWidget(self.steps_body)
        steps_layout.addStretch(1)
        content.addWidget(steps, 1)
        root.addLayout(content, 1)

        self.setCentralWidget(page)
        self._retranslate()

    def _retranslate(self) -> None:
        self.setWindowTitle(self._text("window_title"))
        self.eyebrow.setText(self._text("eyebrow"))
        self.headline.setText(self._text("headline"))
        self.intro.setText(self._text("intro"))
        self.setup_title.setText(self._text("setup_title"))
        self.setup_hint.setText(self._text("setup_hint"))
        self.recent_label.setText(self._text("recent_label"))
        self.open_button.setText(self._text("open_project"))
        self.sources_label.setText(self._text("sources_label"))
        self.add_button.setText(self._text("add_source"))
        self.remove_button.setText(self._text("remove_source"))
        self.output_label.setText(self._text("output_label"))
        self.output_button.setText(self._text("choose_output"))
        self.date_label.setText(self._text("start_date"))
        self.date_enabled.setText(self._text("set_start_date"))
        self.create_button.setText(self._text("create_project"))
        self.steps_title.setText(self._text("next_steps"))
        self.steps_body.setText(self._text("next_steps_body"))
        self.about_action.setText({"ru": "О программе", "de": "Über", "en": "About"}[self.language])
        self._refresh_paths()
        self._refresh_recent_projects()

    def _show_about(self) -> None:
        from . import __version__

        frozen_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        notices = frozen_root / "resources" / "licenses" / "THIRD_PARTY_NOTICES.md"
        text = {
            "ru": (f"Study Archive Prep {__version__}\n\nЛокальная обработка материалов.\n"
                   f"Уведомления о лицензиях и исходный код компонентов находятся в папке приложения: {notices.parent}."),
            "de": (f"Study Archive Prep {__version__}\n\nLokale Verarbeitung von Lernmaterialien.\n"
                   f"Lizenzhinweise und Quellcode der Komponenten: {notices.parent}."),
            "en": (f"Study Archive Prep {__version__}\n\nStudy materials are processed locally.\n"
                   f"Third-party notices and component source archives are in the app resources: {notices.parent}."),
        }[self.language]
        QMessageBox.about(self, self.about_action.text(), text)

    def _language_changed(self, _index: int) -> None:
        language = self.language_picker.currentData()
        if language not in LANGUAGES:
            return
        self.language = language
        self.settings.setValue("language", language)
        self._retranslate()

    def _refresh_paths(self) -> None:
        if not self.source_paths:
            self.sources_list.clear()
            self.sources_list.addItem(self._text("no_sources"))
            self.sources_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        else:
            self.sources_list.clear()
            for path in self.source_paths:
                self.sources_list.addItem(str(path))
        self.output_value.setText(str(self.output_path) if self.output_path else self._text("not_set"))

    def _add_source(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._text("select_source"))
        if not selected:
            return
        path = Path(selected).expanduser().resolve()
        if path not in self.source_paths:
            self.source_paths.append(path)
            self.source_paths.sort(key=lambda item: str(item).casefold())
        self._refresh_paths()

    def _remove_source(self) -> None:
        row = self.sources_list.currentRow()
        if 0 <= row < len(self.source_paths):
            self.source_paths.pop(row)
            self._refresh_paths()

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._text("select_destination"))
        if selected:
            self.output_path = Path(selected).expanduser().resolve()
            self._refresh_paths()

    def _create_project(self) -> None:
        self.status.setStyleSheet("color: #687f9b;")
        if not self.source_paths:
            self._set_status(self._text("need_source"), error=True)
            return
        if self.output_path is None:
            self._set_status(self._text("need_output"), error=True)
            return
        if not self.date_enabled.isChecked():
            self._set_status(self._text("need_date"), error=True)
            return
        for source in self.source_paths:
            if source == self.output_path or source in self.output_path.parents or self.output_path in source.parents:
                self._set_status(self._text("source_output_overlap"), error=True)
                return
        try:
            roots = tuple(SourceRoot.create(path) for path in self.source_paths)
            project = ProjectState.create(
                self.source_paths[0].name, self.output_path, self.start_date.date().toString("yyyy-MM-dd"), roots
            )
            saved = self.repository.save(project)
        except (ProjectStorageError, OSError, ValueError):
            self._set_status(self._text("project_storage_error"), error=True)
            return
        self._current_project = saved
        self._refresh_recent_projects(select_id=saved.id)
        self._set_status(self._text("project_ready"), error=False)
        self._open_workspace(saved)

    def _refresh_recent_projects(self, select_id: str | None = None) -> None:
        try:
            projects = self.repository.list_projects()
        except ProjectStorageError:
            self.recent_picker.clear()
            self.recent_picker.addItem(self._text("project_storage_error"), None)
            self.open_button.setEnabled(False)
            return
        self.recent_picker.clear()
        if not projects:
            self.recent_picker.addItem(self._text("recent_none"), None)
            self.open_button.setEnabled(False)
            return
        for project in projects:
            self.recent_picker.addItem(project.name, project.id)
        self.open_button.setEnabled(True)
        if select_id is not None:
            index = self.recent_picker.findData(select_id)
            if index >= 0:
                self.recent_picker.setCurrentIndex(index)

    def _open_selected_project(self) -> None:
        project_id = self.recent_picker.currentData()
        if not project_id:
            return
        try:
            project = self.repository.load(project_id)
        except ProjectStorageError:
            self._set_status(self._text("project_storage_error"), error=True)
            return
        self._current_project = project
        self.source_paths = [Path(root.path) for root in project.roots]
        self.output_path = Path(project.output_path)
        self.date_enabled.setChecked(project.start_date is not None)
        if project.start_date:
            parsed_date = QDate.fromString(project.start_date, "yyyy-MM-dd")
            if parsed_date.isValid():
                self.start_date.setDate(parsed_date)
        self._refresh_paths()
        self._set_status(self._text("project_loaded"), error=False)
        self._open_workspace(project)

    def _open_workspace(self, project: ProjectState) -> None:
        from .workspace_window import WorkspaceWidget

        if self._workspace is not None:
            self._workspace.stop_and_wait()
            self._pages.removeWidget(self._workspace)
            self._workspace.setParent(None)
            self._workspace.deleteLater()
        self._workspace = WorkspaceWidget(
            project, self.repository, self.data_directory, self.language,
            on_language_changed=self._workspace_language_changed,
            on_back=self._back_to_setup,
        )
        self._pages.addWidget(self._workspace)
        self._pages.setCurrentWidget(self._workspace)

    def _workspace_language_changed(self, language: str) -> None:
        self.language = language
        self.settings.setValue("language", language)
        self.language_picker.setCurrentIndex(LANGUAGES.index(language))

    def _back_to_setup(self) -> None:
        self._pages.setCurrentWidget(self._setup_page)

    def _set_status(self, value: str, error: bool) -> None:
        self.status.setText(value)
        self.status.setStyleSheet("color: #a23b45;" if error else "color: #2c7757;")

    def _restore_window(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:
        if self._workspace is not None:
            self._workspace.stop_and_wait()
        self.settings.setValue("window_geometry", self.saveGeometry())
        super().closeEvent(event)
