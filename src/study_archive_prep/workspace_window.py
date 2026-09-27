"""Review, edit, prepare, and export one study publication plan."""
from __future__ import annotations

import threading
import shutil
import sys
import re
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .i18n import LANGUAGES, LANGUAGE_LABELS
from .audio import extract_audio_lossless, output_suffix, probe_media
from .local_model import LlamaCliRunner, ModelError, ModelStore
from .operation_journal import OperationJournal, run_journaled_plan
from .preflight import build_preflight
from .project import ProjectState, SourceRoot, StudyFile
from .project_repository import ProjectRepository, ProjectStorageError
from .publication import PublicationPlanEditor, build_default_plan
from .publication_manifest import (PublicationManifestError,
                                   write_publication_manifest)
from .scanner import scan_sources
from .titles import linked_output_names, sanitize_russian_title, suggest_title


_WORKSPACE_TEXT = {
    "back": {"ru": "К проектам", "de": "Zu den Projekten", "en": "Projects"},
    "scan": {"ru": "Пересканировать", "de": "Erneut scannen", "en": "Rescan"},
    "undo": {"ru": "Отменить", "de": "Rückgängig", "en": "Undo"},
    "redo": {"ru": "Повторить", "de": "Wiederholen", "en": "Redo"},
    "up": {"ru": "Выше", "de": "Nach oben", "en": "Move up"},
    "down": {"ru": "Ниже", "de": "Nach unten", "en": "Move down"},
    "rename": {"ru": "Изменить название", "de": "Titel ändern", "en": "Rename"},
    "model_download": {"ru": "Скачать модель названий", "de": "Titelmodell laden", "en": "Download title model"},
    "suggest_title": {"ru": "Предложить название по SRT", "de": "Titel aus SRT vorschlagen", "en": "Suggest title from SRT"},
    "minutes": {"ru": "Минут SRT", "de": "SRT-Minuten", "en": "SRT minutes"},
    "select_srt": {"ru": "Выберите SRT-файл в списке", "de": "Wählen Sie eine SRT-Datei aus", "en": "Select an SRT file"},
    "model_missing": {"ru": "Не найдена локальная модель или движок. Сначала установите модель и приложение с движком.", "de": "Lokales Modell oder Laufzeit fehlt. Installieren Sie zuerst Modell und App-Laufzeit.", "en": "The local model or engine is missing. Install the model and app runtime first."},
    "model_ready": {"ru": "Локальная модель проверена и готова.", "de": "Das lokale Modell wurde geprüft und ist bereit.", "en": "The local model is verified and ready."},
    "title_apply": {"ru": "Название для связанных файлов. Исправьте при необходимости и подтвердите:", "de": "Titel für zugehörige Dateien. Bei Bedarf anpassen und bestätigen:", "en": "Title for linked files. Edit if needed, then confirm:"},
    "no_title": {"ru": "В выбранном фрагменте SRT недостаточно текста для предложения.", "de": "Der ausgewählte SRT-Ausschnitt enthält zu wenig Text für einen Vorschlag.", "en": "The selected SRT excerpt does not contain enough text for a suggestion."},
    "model_progress": {"ru": "Модель: {done} из {total} байт", "de": "Modell: {done} von {total} Bytes", "en": "Model: {done} of {total} bytes"},
    "extract_audio": {"ru": "Извлечь звук из видео", "de": "Ton aus Video extrahieren", "en": "Extract audio from video"},
    "audio_done": {"ru": "Звук извлечён без перекодирования. Оригинал сохранён: {name}", "de": "Ton ohne Neukodierung extrahiert. Original bleibt erhalten: {name}", "en": "Audio extracted without re-encoding. Original kept: {name}"},
    "audio_none": {"ru": "В выбранном файле нет звуковой дорожки.", "de": "Die ausgewählte Datei enthält keine Audiospur.", "en": "The selected file has no audio track."},
    "stage_overlap": {"ru": "Папка результата пересекается с временным хранилищем. Выберите другую папку результата.", "de": "Der Ausgabeordner überschneidet sich mit dem Arbeitsordner. Wählen Sie einen anderen Ausgabeordner.", "en": "The output folder overlaps the private staging folder. Choose a different output folder."},
    "add_text": {"ru": "Добавить текст", "de": "Text hinzufügen", "en": "Add text"},
    "assign": {"ru": "Распределить…", "de": "Zuordnen…", "en": "Assign…"},
    "add_week": {"ru": "Добавить неделю", "de": "Woche hinzufügen", "en": "Add week"},
    "add_day": {"ru": "Добавить дату…", "de": "Tag hinzufügen…", "en": "Add day…"},
    "move_into": {"ru": "Переместить в группу…", "de": "In Gruppe verschieben…", "en": "Move to group…"},
    "prepare": {"ru": "Подготовить файлы", "de": "Dateien vorbereiten", "en": "Prepare files"},
    "cancel": {"ru": "Отмена", "de": "Abbrechen", "en": "Cancel"},
    "export": {"ru": "Экспортировать порядок", "de": "Reihenfolge exportieren", "en": "Export order"},
    "choose_manifest": {"ru": "Куда сохранить publication-plan.json?", "de": "Wohin soll publication-plan.json gespeichert werden?", "en": "Where should publication-plan.json be saved?"},
    "scanning": {"ru": "Проверяю исходные папки…", "de": "Quellordner werden geprüft…", "en": "Scanning source folders…"},
    "scan_done": {"ru": "Найдено: {count}; исключено служебных: {excluded}; требуют распределения: {unassigned}; замечаний сканирования: {review}; больше не найдены: {removed}.", "de": "Gefunden: {count}; Systemdateien ausgeschlossen: {excluded}; noch zuzuordnen: {unassigned}; Scan-Hinweise: {review}; nicht mehr gefunden: {removed}.", "en": "Found: {count}; system files excluded: {excluded}; need assignment: {unassigned}; scan notes: {review}; no longer found: {removed}."},
    "scan_error": {"ru": "Не удалось просканировать папки: {error}", "de": "Quellordner konnten nicht gescannt werden: {error}", "en": "Could not scan source folders: {error}"},
    "no_project": {"ru": "Сначала создайте проект или откройте сохранённый.", "de": "Erstellen oder öffnen Sie zuerst ein Projekt.", "en": "Create or open a project first."},
    "select_parent": {"ru": "Выберите неделю или день, куда вставить текст.", "de": "Wählen Sie eine Woche oder einen Tag für den Text.", "en": "Select a week or day for the text."},
    "prepare_review": {"ru": "Перед подготовкой будет создано {count} файлов и архивов. Продолжить?", "de": "Es werden {count} Dateien und Archive erstellt. Fortfahren?", "en": "This will create {count} files and archives. Continue?"},
    "processing": {"ru": "Подготовка: {done} из {total} — {name}", "de": "Vorbereitung: {done} von {total} — {name}", "en": "Preparing: {done} of {total} — {name}"},
    "finished": {"ru": "Подготовка завершена. Создано или проверено элементов: {count}.", "de": "Vorbereitung abgeschlossen. Erstellt oder geprüft: {count} Elemente.", "en": "Preparation complete. Created or verified: {count} items."},
    "process_error": {"ru": "Подготовку остановлено безопасно: {error}", "de": "Vorbereitung sicher angehalten: {error}", "en": "Preparation stopped safely: {error}"},
    "manifest_done": {"ru": "Порядок публикации сохранён: {path}", "de": "Veröffentlichungsreihenfolge gespeichert: {path}", "en": "Publication order saved: {path}"},
    "manifest_error": {"ru": "Не удалось экспортировать порядок: {error}", "de": "Reihenfolge konnte nicht exportiert werden: {error}", "en": "Could not export order: {error}"},
    "unassigned_title": {"ru": "Нужно распределить", "de": "Noch zuzuordnen", "en": "Needs assignment"},
    "empty": {"ru": "Файлы не найдены. Добавьте материалы в исходные папки и пересканируйте.", "de": "Keine Dateien gefunden. Fügen Sie Material hinzu und scannen Sie erneut.", "en": "No files found. Add material to the source folders and scan again."},
    "project_save_error": {"ru": "Не удалось сохранить изменения проекта.", "de": "Projektänderungen konnten nicht gespeichert werden.", "en": "Could not save project changes."},
}


def _w(key: str, language: str, **values) -> str:
    return _WORKSPACE_TEXT.get(key, {}).get(language, _WORKSPACE_TEXT.get(key, {}).get("en", key)).format(**values)


class _TaskWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, function):
        super().__init__()
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function(self.progress.emit))
        except Exception as exc:  # surfaced in the UI; worker must not kill the process
            self.failed.emit(str(exc))


class _PublicationTreeWidget(QTreeWidget):
    def __init__(self, on_drop, parent=None):
        super().__init__(parent)
        self.on_drop = on_drop

    def dropEvent(self, event):
        super().dropEvent(event)
        self.on_drop()


class WorkspaceWidget(QWidget):
    def __init__(self, project: ProjectState, repository: ProjectRepository,
                 data_directory: Path, language: str, on_language_changed,
                 on_back):
        super().__init__()
        self.project = project
        self.repository = repository
        self.data_directory = Path(data_directory)
        self.language = language
        self.on_language_changed = on_language_changed
        self.on_back = on_back
        self.editor = PublicationPlanEditor(project)
        self._thread: QThread | None = None
        self._worker: _TaskWorker | None = None
        self._cancel = threading.Event()
        self._scanned = bool(project.files)
        self._processing_plan = None
        self._build_ui()
        if not project.files:
            self.start_scan()
        else:
            self._refresh_tree()

    def t(self, key: str, **values) -> str:
        return _w(key, self.language, **values)

    def _build_ui(self):
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.back_button = QPushButton(self.t("back")); self.back_button.clicked.connect(self.on_back)
        top.addWidget(self.back_button)
        self.project_label = QLabel(self.project.name); self.project_label.setStyleSheet("font-size:20px;font-weight:700;color:#183451")
        top.addWidget(self.project_label, 1)
        self.language_picker = QComboBox()
        for code in LANGUAGES: self.language_picker.addItem(LANGUAGE_LABELS[code], code)
        self.language_picker.setCurrentIndex(LANGUAGES.index(self.language))
        self.language_picker.currentIndexChanged.connect(self._change_language)
        top.addWidget(self.language_picker)
        root.addLayout(top)
        self.status = QLabel(self.t("scanning") if not self.project.files else "")
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.tree = _PublicationTreeWidget(self._sync_tree_order)
        self.tree.setHeaderLabels(["", self.t("export")])
        self.tree.setColumnWidth(0, 38)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAccessibleName(self.t("export"))
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.itemChanged.connect(self._item_changed)
        root.addWidget(self.tree, 1)
        actions = QVBoxLayout()
        edit_actions = QHBoxLayout()
        self.scan_button = QPushButton(self.t("scan")); self.scan_button.clicked.connect(self.start_scan)
        self.undo_button = QPushButton(self.t("undo")); self.undo_button.clicked.connect(self._undo)
        self.redo_button = QPushButton(self.t("redo")); self.redo_button.clicked.connect(self._redo)
        self.up_button = QPushButton(self.t("up")); self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QPushButton(self.t("down")); self.down_button.clicked.connect(lambda: self._move(1))
        self.rename_button = QPushButton(self.t("rename")); self.rename_button.clicked.connect(self._rename)
        self.text_button = QPushButton(self.t("add_text")); self.text_button.clicked.connect(self._add_text)
        self.assign_button = QPushButton(self.t("assign")); self.assign_button.clicked.connect(self._assign_file)
        self.move_into_button = QPushButton(self.t("move_into")); self.move_into_button.clicked.connect(self._move_into_selected)
        self.audio_button = QPushButton(self.t("extract_audio")); self.audio_button.clicked.connect(self.extract_selected_audio)
        self.add_week_button = QPushButton(self.t("add_week")); self.add_week_button.clicked.connect(self._add_week)
        self.add_day_button = QPushButton(self.t("add_day")); self.add_day_button.clicked.connect(self._add_day)
        for button in (self.scan_button,self.undo_button,self.redo_button,self.up_button,self.down_button,self.rename_button):
            edit_actions.addWidget(button)
        actions.addLayout(edit_actions)
        content_actions = QHBoxLayout()
        for button in (self.text_button, self.assign_button, self.move_into_button, self.audio_button,
                       self.add_week_button, self.add_day_button): content_actions.addWidget(button)
        actions.addLayout(content_actions)
        title_actions = QHBoxLayout()
        self.model_button = QPushButton(self.t("model_download")); self.model_button.clicked.connect(self.download_model)
        self.title_button = QPushButton(self.t("suggest_title")); self.title_button.clicked.connect(self.suggest_selected_title)
        self.minutes_picker = QComboBox(); self.minutes_picker.addItem("5", 5); self.minutes_picker.addItem("10", 10)
        self.minutes_picker.setCurrentIndex(1)
        self.minutes_picker.setAccessibleName(self.t("minutes"))
        self.minutes_label = QLabel(self.t("minutes"))
        title_actions.addWidget(self.model_button); title_actions.addWidget(self.title_button)
        title_actions.addWidget(self.minutes_label); title_actions.addWidget(self.minutes_picker); title_actions.addStretch(1)
        actions.addLayout(title_actions)
        root.addLayout(actions)
        self.progress = QProgressBar(); self.progress.setVisible(False); root.addWidget(self.progress)
        footer = QHBoxLayout()
        self.prepare_button = QPushButton(self.t("prepare")); self.prepare_button.setObjectName("primary"); self.prepare_button.clicked.connect(self.prepare)
        self.cancel_button = QPushButton(self.t("cancel"))
        self.cancel_button.clicked.connect(self._cancel.set); self.cancel_button.setVisible(False)
        self.export_button = QPushButton(self.t("export")); self.export_button.clicked.connect(self.export_manifest)
        footer.addWidget(self.prepare_button); footer.addWidget(self.cancel_button); footer.addStretch(1); footer.addWidget(self.export_button)
        root.addLayout(footer)

    def _change_language(self, _index):
        code = self.language_picker.currentData()
        if code in LANGUAGES:
            self.language = code
            self.on_language_changed(code)
            self.back_button.setText(self.t("back")); self.scan_button.setText(self.t("scan"))
            self.undo_button.setText(self.t("undo")); self.redo_button.setText(self.t("redo"))
            self.up_button.setText(self.t("up")); self.down_button.setText(self.t("down"))
            self.rename_button.setText(self.t("rename")); self.text_button.setText(self.t("add_text"))
            self.assign_button.setText(self.t("assign")); self.move_into_button.setText(self.t("move_into"))
            self.add_week_button.setText(self.t("add_week")); self.add_day_button.setText(self.t("add_day"))
            self.audio_button.setText(self.t("extract_audio"))
            self.model_button.setText(self.t("model_download")); self.title_button.setText(self.t("suggest_title"))
            self.minutes_label.setText(self.t("minutes")); self.minutes_picker.setAccessibleName(self.t("minutes"))
            self.prepare_button.setText(self.t("prepare")); self.export_button.setText(self.t("export"))
            self.cancel_button.setText(self.t("cancel"))
            self.tree.setHeaderLabels(["", self.t("export")]); self._refresh_tree()

    def start_scan(self):
        if self._thread is not None:
            return
        self.status.setText(self.t("scanning")); self.scan_button.setEnabled(False)
        roots = tuple(root.path for root in self.project.roots)
        start_date = self.project.start_date
        def work(_progress):
            year = int(start_date[:4]) if start_date else None
            return scan_sources(roots, year_hint=year, start_date=start_date)
        self._start_worker(work, self._scan_finished)

    def _scan_finished(self, result):
        self.scan_button.setEnabled(True)
        project_roots = {root.path: root.id for root in self.project.roots}
        root_ids = {scanned.id: project_roots[scanned.path]
                    for scanned in result.roots if scanned.path in project_roots}
        existing = {(item.source_root_id, item.relative_path): item for item in self.project.files}
        files = tuple(
            replace(item, id=existing[(root_ids[item.source_root_id], item.relative_path)].id,
                    source_root_id=root_ids[item.source_root_id],
                    included=existing[(root_ids[item.source_root_id], item.relative_path)].included)
            if item.source_root_id in root_ids and
               (root_ids[item.source_root_id], item.relative_path) in existing
            else replace(item, source_root_id=root_ids[item.source_root_id])
            for item in result.files if item.source_root_id in root_ids)
        scanned_keys = {(root_ids[item.source_root_id], item.relative_path)
                        for item in result.files if item.source_root_id in root_ids}
        removed_count = sum(key not in scanned_keys for key in existing)
        had_saved_layout = bool(self.project.files and self.project.blocks)
        if had_saved_layout:
            valid_ids = {item.id for item in files}
            blocks = tuple(block for block in self.project.blocks
                           if block.kind != "file" or block.file_id in valid_ids)
            self.project = replace(self.project, files=files, blocks=blocks)
            assigned = {block.file_id for block in blocks if block.kind == "file"}
            unassigned_count = sum(item.id not in assigned for item in files)
        else:
            self.project = replace(self.project, files=files, blocks=())
            default = build_default_plan(self.project)
            self.project = replace(self.project, blocks=default.blocks)
            unassigned_count = len(default.unassigned_file_ids)
        try:
            self.project = self.repository.save(self.project, expected_revision=self.project.revision)
            self.editor = PublicationPlanEditor(self.project)
            self._processing_plan = None
            self._scanned = True
            self._refresh_tree()
            self.status.setText(self.t("scan_done", count=len(result.files), excluded=len(result.excluded_paths),
                                  unassigned=unassigned_count, review=len(result.issues), removed=removed_count))
        except (ProjectStorageError, ValueError) as exc:
            self.status.setText(self.t("project_save_error") + " " + str(exc))

    def _start_worker(self, function, succeeded):
        thread = QThread(self)
        worker = _TaskWorker(function); worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(succeeded)
        worker.failed.connect(self._worker_failed)
        worker.progress.connect(self._show_progress)
        worker.succeeded.connect(thread.quit); worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda thread=thread: self._worker_finished(thread))
        self._thread, self._worker = thread, worker
        thread.start()

    def _worker_failed(self, error):
        self.status.setText(self.t("process_error", error=error))
        self.scan_button.setEnabled(True); self.prepare_button.setEnabled(True)
        self.model_button.setEnabled(True); self.title_button.setEnabled(True); self.audio_button.setEnabled(True)
        self.cancel_button.setVisible(False)

    def _worker_finished(self, finished_thread=None):
        if finished_thread is not None and self._thread is not finished_thread:
            return
        self._thread = None; self._worker = None
        self.progress.setVisible(False); self.cancel_button.setVisible(False)
        self.scan_button.setEnabled(True); self.prepare_button.setEnabled(True)
        self.model_button.setEnabled(True); self.title_button.setEnabled(True); self.audio_button.setEnabled(True)

    def stop_and_wait(self):
        """Stop cancellable processing and let an active scan/worker exit cleanly."""
        self._cancel.set()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _show_progress(self, done, total, name):
        self.progress.setVisible(True); self.progress.setRange(0, 1000)
        self.progress.setValue(min(1000, int(done * 1000 / max(total, 1))))
        if name == self.t("model_download"):
            self.status.setText(self.t("model_progress", done=f"{done:,}", total=f"{total:,}"))
        else:
            self.status.setText(self.t("processing", done=done, total=total, name=Path(name).name))

    def _refresh_tree(self):
        self.tree.blockSignals(True); self.tree.clear()
        blocks = {block.id: block for block in self.project.blocks}
        files = {item.id: item for item in self.project.files}
        nodes = {}

        def add_children(parent_id, parent_node=None):
            children = sorted((block for block in self.project.blocks
                               if block.parent_id == parent_id), key=lambda block: block.position)
            for block in children:
                label = block.title
                if block.kind == "file" and block.file_id in files:
                    label = files[block.file_id].name
                node = QTreeWidgetItem(["", label]); node.setData(0, Qt.ItemDataRole.UserRole, block.id)
                node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                node.setCheckState(0, Qt.CheckState.Checked if block.included else Qt.CheckState.Unchecked)
                if block.kind in {"week", "day"}: node.setExpanded(True)
                if parent_node is None: self.tree.addTopLevelItem(node)
                else: parent_node.addChild(node)
                nodes[block.id] = node
                add_children(block.id, node)

        add_children(None)
        assigned = {block.file_id for block in self.project.blocks if block.kind == "file"}
        leftovers = [item for item in self.project.files if item.id not in assigned]
        if leftovers:
            item = QTreeWidgetItem(["", self.t("unassigned_title") + f" ({len(leftovers)})"])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled); self.tree.addTopLevelItem(item)
            for file in leftovers:
                child = QTreeWidgetItem(["", file.name]); child.setData(0, Qt.ItemDataRole.UserRole, file.id)
                child.setToolTip(1, file.relative_path); item.addChild(child)
        if not self.project.files:
            self.tree.addTopLevelItem(QTreeWidgetItem(["", self.t("empty")]))
        self.tree.blockSignals(False)
        self.undo_button.setEnabled(self.editor.can_undo); self.redo_button.setEnabled(self.editor.can_redo)

    def _item_changed(self, item, column):
        block_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not block_id: return
        included = item.checkState(0) == Qt.CheckState.Checked
        self.editor.set_included(block_id, included)
        self._save_editor()

    def _sync_tree_order(self):
        blocks = {block.id: block for block in self.editor.project.blocks}
        ordered = []
        def collect(parent):
            for index in range(parent.childCount()):
                node = parent.child(index)
                block_id = node.data(0, Qt.ItemDataRole.UserRole)
                if block_id in blocks:
                    parent_node = node.parent()
                    parent_id = parent_node.data(0, Qt.ItemDataRole.UserRole) if parent_node else None
                    ordered.append((block_id, parent_id, index))
                    collect(node)
        for index in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(index)
            block_id = node.data(0, Qt.ItemDataRole.UserRole)
            if block_id in blocks:
                ordered.append((block_id, None, index))
                collect(node)
        positions = {}
        for block_id, parent_id, _old_position in ordered:
            if parent_id is not None and parent_id not in blocks:
                continue
            position = positions.get(parent_id, 0)
            current = blocks.get(block_id)
            if current is not None and (current.parent_id != parent_id or current.position != position):
                try:
                    self.editor.move(block_id, parent_id, position)
                    blocks = {block.id: block for block in self.editor.project.blocks}
                except (KeyError, ValueError):
                    return self._refresh_tree()
            positions[parent_id] = position + 1
        self._save_editor()

    def _save_editor(self):
        try:
            self.project = self.repository.save(self.editor.project, expected_revision=self.project.revision)
            self.editor.project = self.project
            self._processing_plan = None
            self._refresh_tree()
            return True
        except (ProjectStorageError, ValueError) as exc:
            self.status.setText(self.t("project_save_error") + " " + str(exc))
            return False

    def _selected_block(self):
        selection = self.tree.selectedItems()
        if not selection: return None
        return selection[0].data(0, Qt.ItemDataRole.UserRole)

    def _undo(self): self.editor.undo(); self._save_editor()
    def _redo(self): self.editor.redo(); self._save_editor()

    def _move(self, offset):
        block_id = self._selected_block()
        if not block_id: return
        block = next((b for b in self.project.blocks if b.id == block_id), None)
        if not block: return
        siblings = sorted((b for b in self.project.blocks if b.parent_id == block.parent_id), key=lambda b: b.position)
        index = next((i for i, b in enumerate(siblings) if b.id == block_id), -1)
        target = index + offset
        if 0 <= target < len(siblings):
            self.editor.move(block_id, block.parent_id, target)
            self._save_editor()

    def _assign_file(self):
        selected = self.tree.selectedItems()
        if not selected: return
        file_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not file_id or file_id not in {item.id for item in self.project.files}:
            return
        parents = [block for block in self.project.blocks if block.kind in {"week", "day"}]
        if not parents:
            self.status.setText(self.t("select_parent")); return
        choices = [block.title for block in parents]
        choice, accepted = QInputDialog.getItem(self, self.t("assign"), self.t("select_parent"), choices, 0, False)
        if not accepted: return
        parent = parents[choices.index(choice)]
        try:
            self.editor.add_file(file_id, parent.id)
            self._save_editor()
        except (KeyError, ValueError) as exc:
            self.status.setText(self.t("process_error", error=str(exc)))

    def _add_week(self):
        numbers = [int(match.group(1)) for block in self.project.blocks if block.kind == "week"
                   if (match := re.search(r"(?:неделя|woche|week)\s*(\d+)", block.title, re.IGNORECASE))]
        number = max(numbers, default=0) + 1
        label = {"ru": "Неделя", "de": "Woche", "en": "Week"}[self.language]
        self.editor.add_week(f"{label} {number}")
        self._save_editor()

    def _add_day(self):
        weeks = [block for block in self.project.blocks if block.kind == "week"]
        if not weeks:
            self.status.setText(self.t("select_parent")); return
        labels = [block.title for block in weeks]
        week_name, accepted = QInputDialog.getItem(self, self.t("add_day"), self.t("select_parent"), labels, 0, False)
        if not accepted: return
        study_date, accepted = QInputDialog.getText(self, self.t("add_day"), "YYYY-MM-DD")
        if not accepted or not study_date.strip(): return
        try:
            self.editor.add_day(weeks[labels.index(week_name)].id, study_date.strip())
            self._save_editor()
        except ValueError as exc:
            self.status.setText(self.t("process_error", error=str(exc)))

    def _move_into_selected(self):
        selected = self.tree.selectedItems()
        if not selected: return
        source_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
        blocks = {block.id: block for block in self.project.blocks}
        source = blocks.get(source_id)
        if source is None: return
        targets = [block for block in self.project.blocks if block.kind in {"week", "day"}
                   and block.id != source.id]
        labels = [block.title for block in targets]
        if not targets: return
        choice, accepted = QInputDialog.getItem(self, self.t("move_into"), self.t("select_parent"), labels, 0, False)
        if not accepted: return
        target = targets[labels.index(choice)]
        siblings = [block for block in self.project.blocks if block.parent_id == target.id]
        try:
            self.editor.move(source.id, target.id, len(siblings))
            self._save_editor()
        except (KeyError, ValueError) as exc:
            self.status.setText(self.t("process_error", error=str(exc)))

    def extract_selected_audio(self):
        block_id = self._selected_block()
        block = next((item for item in self.project.blocks if item.id == block_id), None)
        study_file = next((item for item in self.project.files if block and item.id == block.file_id), None)
        if study_file is None or Path(study_file.name).suffix.casefold() not in {
                ".mkv", ".mp4", ".m4v", ".mov", ".webm", ".avi"}:
            self.status.setText(self.t("select_srt")); return
        root = next((item for item in self.project.roots if item.id == study_file.source_root_id), None)
        if root is None: return
        source = Path(root.path).joinpath(*study_file.relative_path.split("/"))
        self._pending_audio = (block, study_file, source)
        self.cancel_button.setVisible(True); self.audio_button.setEnabled(False)
        self._start_worker(lambda _progress: probe_media(source), self._audio_probed)

    def _audio_probed(self, media_info):
        self.cancel_button.setVisible(False); self.audio_button.setEnabled(True)
        if not media_info.audio_streams:
            self.status.setText(self.t("audio_none")); return
        selected = media_info.audio_streams[0]
        if len(media_info.audio_streams) > 1:
            labels = [stream.label for stream in media_info.audio_streams]
            choice, accepted = QInputDialog.getItem(self, self.t("extract_audio"),
                                                     self.t("extract_audio"), labels, 0, False)
            if not accepted: return
            selected = media_info.audio_streams[labels.index(choice)]
        block, study_file, source = self._pending_audio
        stage_root_path = self.data_directory / "generated_media" / self.project.id
        if any(path.is_symlink() for path in (self.data_directory,
                                               self.data_directory / "generated_media",
                                               stage_root_path)):
            self.status.setText(self.t("stage_overlap")); return
        output_path = Path(self.project.output_path).resolve(strict=False)
        stage_resolved = stage_root_path.resolve(strict=False)
        if (stage_resolved == output_path or stage_resolved in output_path.parents
                or output_path in stage_resolved.parents):
            self.status.setText(self.t("stage_overlap")); return
        try:
            week = block
            if week.kind == "day": week = next(item for item in self.project.blocks if item.id == week.parent_id)
            match = re.search(r"(?:неделя|woche|week)\s*(\d+)", week.title, re.IGNORECASE)
            number = int(match.group(1)) if match else week.position + 1
            parts = [f"Неделя {number}"]
            if study_file.study_date:
                parts.append(study_file.study_date)
            candidate_parent = stage_root_path.joinpath(*parts)
            safe_title = Path(block.title.replace("\\", "/")).name
            stem = Path(safe_title).stem or "Audio"
            suffix = output_suffix(selected.codec)
            candidate = stem
            counter = 2
            while (candidate_parent / f"{candidate}{suffix}").exists():
                candidate = f"{stem} ({counter})"
                counter += 1
            relative = Path(*parts) / candidate
            destination_stem = stage_root_path / relative
            stage_root_path.joinpath(*parts).mkdir(parents=True, exist_ok=True)
            source_roots = tuple(item.path for item in self.project.roots)
            if any(stage_resolved == Path(path).resolve(strict=False)
                   or stage_resolved in Path(path).resolve(strict=False).parents
                   or Path(path).resolve(strict=False) in stage_resolved.parents for path in source_roots):
                self.status.setText(self.t("stage_overlap")); return
            self._pending_audio = (block, study_file, source, stage_root_path, destination_stem,
                                   selected.index, number)
        except (StopIteration, OSError, ValueError) as exc:
            self.status.setText(self.t("process_error", error=str(exc))); return
        self._cancel.clear(); self.cancel_button.setVisible(True); self.audio_button.setEnabled(False)
        self._start_worker(lambda progress: extract_audio_lossless(
            source, destination_stem, stream_index=selected.index,
            cancelled=self._cancel.is_set,
            progress=lambda fraction: progress(int((fraction or 0) * 100), 100,
                                                self.t("extract_audio"))), self._audio_extracted)

    def _audio_extracted(self, result):
        block, original, source, stage_root_path, _stem, _stream_index, week_number = self._pending_audio
        output = Path(result.output_path)
        source_root = next((item for item in self.project.roots
                            if Path(item.path).resolve(strict=False) == stage_root_path.resolve(strict=False)), None)
        roots = self.project.roots if source_root else (*self.project.roots, SourceRoot.create(stage_root_path))
        source_root = source_root or roots[-1]
        relative = output.relative_to(stage_root_path).as_posix()
        stat_result = output.stat()
        audio_file = StudyFile.create(source_root.id, relative, output.name, stat_result.st_size,
                                      stat_result.st_mtime_ns, study_date=original.study_date,
                                      category="audio_video", week_number=week_number)
        editor = PublicationPlanEditor(replace(self.project, roots=tuple(roots),
                                                files=(*self.project.files, audio_file)))
        try:
            editor.add_file(audio_file.id, block.parent_id or "", output.name,
                            position=block.position + 1)
            editor.set_included(block.id, False)
            self.editor = editor
            if not self._save_editor():
                self.editor = PublicationPlanEditor(self.project)
                return
            self.status.setText(self.t("audio_done", name=output.name))
        except (KeyError, ValueError, ProjectStorageError) as exc:
            self.status.setText(self.t("process_error", error=str(exc)))

    def _rename(self):
        block_id = self._selected_block()
        block = next((b for b in self.project.blocks if b.id == block_id), None)
        if not block: return
        if block.kind == "text":
            title, accepted = QInputDialog.getMultiLineText(self, self.t("rename"), self.t("rename"), block.text or "")
            if accepted and title.strip():
                try: self.editor.edit_text(block_id, title.strip()); self._save_editor()
                except ValueError as exc: self.status.setText(self.t("process_error", error=str(exc)))
            return
        prompt = "YYYY-MM-DD" if block.kind == "day" else self.t("rename")
        title, accepted = QInputDialog.getText(self, self.t("rename"), prompt, text=block.title)
        if accepted and title.strip():
            try:
                if block.kind == "day": self.editor.set_day_date(block_id, title.strip())
                else: self.editor.rename(block_id, title.strip())
                self._save_editor()
            except ValueError as exc:
                self.status.setText(self.t("process_error", error=str(exc)))

    def _add_text(self):
        block_id = self._selected_block()
        parent = next((b for b in self.project.blocks if b.id == block_id), None)
        if parent is None or parent.kind not in {"week", "day"}:
            QMessageBox.information(self, self.t("add_text"), self.t("select_parent")); return
        title = self.t("add_text")
        text, accepted = QInputDialog.getMultiLineText(self, title, title)
        if accepted and text.strip(): self.editor.add_text(parent.id, text.strip()); self._save_editor()

    def _runner(self):
        model = ModelStore().installed(verify=True)
        if model is None:
            raise ModelError(self.t("model_missing"))
        candidates = []
        if getattr(sys, "_MEIPASS", None):
            candidates.append(Path(sys._MEIPASS) / "resources" / "bin" / "llama-cli")
        candidates.extend((Path(sys.executable).resolve().parent / "resources" / "bin" / "llama-cli",
                           Path(__file__).resolve().parents[2] / "resources" / "bin" / "llama-cli"))
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            executable = shutil.which("llama-cli")
        if executable is None:
            raise ModelError(self.t("model_missing"))
        return LlamaCliRunner(executable, model,
                              prompt_directory=self.data_directory / "private-prompts")

    def download_model(self):
        self._cancel.clear(); self.model_button.setEnabled(False); self.cancel_button.setVisible(True)
        self._start_worker(
            lambda progress: ModelStore().download(
                cancelled=self._cancel.is_set,
                progress=lambda done, total: progress(done, total, self.t("model_download"))),
            self._model_downloaded)

    def _model_downloaded(self, _install):
        self.status.setText(self.t("model_ready"))
        self.model_button.setEnabled(True)

    def suggest_selected_title(self):
        block_id = self._selected_block()
        block = next((item for item in self.project.blocks if item.id == block_id), None)
        file = next((item for item in self.project.files if block and item.id == block.file_id), None)
        if file is None or Path(file.name).suffix.casefold() != ".srt":
            self.status.setText(self.t("select_srt")); return
        source_root = next((root for root in self.project.roots if root.id == file.source_root_id), None)
        if source_root is None:
            self.status.setText(self.t("select_srt")); return
        subtitle = Path(source_root.path).joinpath(*file.relative_path.split("/"))
        related_items = [file]
        for candidate in self.project.files:
            if (candidate.id == file.id or candidate.source_root_id != file.source_root_id
                    or Path(candidate.relative_path).parent != Path(file.relative_path).parent):
                continue
            try:
                linked_output_names([Path(file.name), Path(candidate.name)], "Учебная запись")
                related_items.append(candidate)
            except ValueError:
                continue
        related = [Path(item.name) for item in related_items]
        self._title_related_ids = {item.name: item.id for item in related_items}
        minutes = self.minutes_picker.currentData()
        self._cancel.clear(); self.title_button.setEnabled(False); self.cancel_button.setVisible(True)
        self._start_worker(lambda _progress: suggest_title(subtitle, self._runner(), minutes=minutes,
                           related_files=related), self._title_suggested)

    def _title_suggested(self, proposal):
        self.title_button.setEnabled(True)
        if proposal is None:
            self.status.setText(self.t("no_title")); return
        title, accepted = QInputDialog.getText(self, self.t("suggest_title"), self.t("title_apply"),
                                                text=proposal.title)
        clean_title = sanitize_russian_title(title)
        if not accepted or clean_title is None: return
        related_ids = getattr(self, "_title_related_ids", {})
        file_by_name = {name: next((item for item in self.project.files if item.id == file_id), None)
                        for name, file_id in related_ids.items()}
        block_by_file = {block.file_id: block for block in self.project.blocks if block.kind == "file"}
        for old_name, suggested_name in proposal.output_names:
            source = file_by_name.get(old_name)
            block = block_by_file.get(source.id) if source else None
            if block is None: continue
            final_name = suggested_name.replace(proposal.title, clean_title, 1)
            try: self.editor.rename(block.id, final_name)
            except ValueError: continue
        self._save_editor()

    def prepare(self):
        if not self._scanned:
            self.status.setText(self.t("no_project")); return
        plan = build_preflight(self.project)
        blockers = [issue for issue in plan.issues if issue.blocking]
        if blockers:
            self.status.setText(self.t("process_error", error=blockers[0].message)); return
        count = len(plan.copies) + len(plan.archives)
        preview = QMessageBox(self)
        preview.setWindowTitle(self.t("prepare"))
        preview.setText(self.t("prepare_review", count=count))
        preview.setDetailedText("\n".join(
            [*(f"Copy  {item.destination}" for item in plan.copies),
             *(f"ZIP  {archive.destination}\n" + "\n".join(f"  • {name}" for name in archive.member_names)
               for archive in plan.archives)]))
        preview.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        answer = preview.exec()
        if answer != QMessageBox.StandardButton.Yes: return
        self._cancel.clear(); self.prepare_button.setEnabled(False); self.cancel_button.setVisible(True)
        self._processing_plan = plan
        journal = OperationJournal(self.data_directory / "operations.sqlite3")
        self._start_worker(lambda progress: run_journaled_plan(self.project.id, plan, journal,
                           cancelled=self._cancel.is_set,
                           progress=lambda done,total,name: progress(done,total,name)), self._processing_finished)

    def _processing_finished(self, result):
        self.status.setText(self.t("finished", count=len(result.outputs)))

    def export_manifest(self):
        destination, _ = QFileDialog.getSaveFileName(self, self.t("choose_manifest"),
                                                      str(Path(self.project.output_path) / "publication-plan.json"),
                                                      "JSON (*.json)")
        if not destination: return
        try:
            path = self.create_manifest(destination)
            self.status.setText(self.t("manifest_done", path=path))
        except (PublicationManifestError, OSError, ValueError) as exc:
            self.status.setText(self.t("manifest_error", error=str(exc)))

    def create_manifest(self, destination=None):
        plan = self._processing_plan or build_preflight(self.project)
        plan = replace(plan, issues=tuple(issue for issue in plan.issues
                                           if issue.code != "output_exists"))
        return write_publication_manifest(self.project, self.project.revision, plan, destination)
