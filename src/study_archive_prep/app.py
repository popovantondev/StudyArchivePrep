"""Desktop entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from . import __version__
from .i18n import system_language
from .main_window import MainWindow
from .project_repository import ProjectRepository, default_data_directory


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare study materials for Telegram.")
    parser.add_argument("--version", action="version", version=f"Study Archive Prep {__version__}")
    parser.add_argument("--data-dir", help="Use an isolated local settings and project-data directory.")
    args = parser.parse_args()

    data_directory = Path(args.data_dir).expanduser() if args.data_dir else default_data_directory()
    QCoreApplication.setOrganizationName("StudyArchivePrep")
    QCoreApplication.setApplicationName("StudyArchivePrep")

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Study Archive Prep")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.UserScope, str(data_directory))
    settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                         "StudyArchivePrep", "StudyArchivePrep")
    language = settings.value("language", system_language(), type=str)
    repository = ProjectRepository(data_directory / "projects.sqlite3")
    window = MainWindow(language, settings, repository)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
