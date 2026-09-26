"""Desktop entry point."""
from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from . import __version__
from .i18n import system_language
from .main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare study materials for Telegram.")
    parser.add_argument("--version", action="version", version=f"Study Archive Prep {__version__}")
    parser.add_argument("--data-dir", help="Use an isolated local settings and project-data directory.")
    args = parser.parse_args()

    QCoreApplication.setOrganizationName("StudyArchivePrep")
    QCoreApplication.setApplicationName("StudyArchivePrep")
    if args.data_dir:
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.UserScope, args.data_dir)

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Study Archive Prep")
    settings = QSettings()
    language = settings.value("language", system_language(), type=str)
    window = MainWindow(language, settings)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
