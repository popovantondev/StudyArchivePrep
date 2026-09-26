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

## Release

Aus einem geprüften, sauberen Git-Commit bauen. Für jede Version einen neuen Ausgabeordner verwenden und frühere Releases nicht ersetzen. Das fertige App-Archiv mit einem neuen Datenordner prüfen. Vor der Veröffentlichung Repository, Archiv, Screenshots, Drittanbieter-Lizenzen und Prüfsumme kontrollieren.
