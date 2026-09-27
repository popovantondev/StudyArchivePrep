# Entwicklung

## Voraussetzungen

- macOS 13 oder neuer auf Apple Silicon
- Python 3.12
- Xcode Command Line Tools für die native App-Verpackung

## Einrichtung und Prüfungen

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Unit-Tests müssen deterministisch, offline und unabhängig von echten Lernordnern, Telegram-Konten und Modelldiensten sein. Kleine synthetische Daten und temporäre Ordner verwenden. Archivinhalt und Unverändertheit der Quelle prüfen.

Der lokale Ordner `.work-memory` enthält Aufgabenstatus, Fortsetzungsnotizen und Prüfnachweise. Git ignoriert ihn. Maschinenspezifische Inhalte nicht in öffentliche Dokumentation kopieren.

## Release

Aus einem geprüften, sauberen Git-Commit bauen. Für jede Version einen neuen Ausgabeordner verwenden und frühere Releases nicht ersetzen. Das fertige App-Archiv mit einem neuen Datenordner prüfen. Vor der Veröffentlichung Repository, Archiv, Screenshots, Drittanbieter-Lizenzen und Prüfsumme kontrollieren.

Für die nativen Komponenten CMake und Xcode Command Line Tools installieren und `scripts/build_macos_native_tools.sh` ausführen. Das Skript pinnt Quellversionen und prüft die SHA-256-Prüfsumme von FFmpeg. Python-Build-Abhängigkeiten mit `python -m pip install -e '.[build]'` installieren und anschließend `scripts/build_macos_app.sh` starten. Das Ergebnis liegt unter `release-build/app-dist/StudyArchivePrep.app`. `scripts/package_macos_release.sh` erstellt das ZIP und seine SHA-256-Datei, ohne einen vorhandenen Release zu überschreiben. Die lokale Ad-hoc-Signatur ist keine Developer-ID-Signatur und keine notarialisierte Freigabe.
