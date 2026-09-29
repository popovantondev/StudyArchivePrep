# Study Archive Prep

**[Русский](../ru/README.md) · [Deutsch](README.md) · [English](../../README.md)**

macOS 13 oder neuer · Apple Silicon · Version 0.1.0

Study Archive Prep ordnet Lernmaterial nach Datum, hilft bei der Prüfung von Aufnahmen und Untertiteln und erstellt einen Veröffentlichungsplan für Telegram Media Sender.

![Screenshot des synthetischen Beispiels in der russischsprachigen Oberfläche; dasselbe Bild wird in allen Sprachfassungen verwendet, separate lokalisierte Screenshots sind nicht verfügbar](../images/study-archive-prep-workspace.png)

## Projektstatus

Dies ist eine frühe Entwicklungsversion. Die App scannt ausgewählte Quellordner, ordnet Dateien nach Datum und Woche, lässt die Veröffentlichungsreihenfolge prüfen und bearbeiten, kopiert Dateien und erstellt ZIP-Archive mit Wiederherstellungsjournal, extrahiert Ton ohne Neukodierung und exportiert einen versionierten Veröffentlichungsplan. Für russische lokale Titelvorschläge werden die ersten fünf oder zehn Minuten einer ausgewählten SRT-Datei analysiert; Modell und lokale Laufzeit müssen installiert sein. Die App sendet keine Telegram-Nachrichten.

## Aus den Quellen starten

Benötigt Python 3.12 unter macOS.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
study-archive-prep
```

Für eine getrennte UI-Vorschau `--data-dir /tmp/study-archive-prep-preview` angeben. Damit werden lokale Einstellungen und App-Daten umgeleitet.

## Datensicherheit und Datenschutz

Quellordner werden beim Erstellen eines Projekts oder nach einem erneuten Scan lokal untersucht. Die Ausgabe wird getrennt gespeichert; temporäre Dateien und ein privates Wiederherstellungsjournal schützen bestehende Dateien vor Überschreiben. Extrahierter Ton wird zunächst in privaten App-Daten gespeichert und danach in die vorbereitete Ausgabe kopiert. Originalaufnahmen bleiben erhalten. Dateien werden nicht ins Internet hochgeladen. Lernmaterial, Untertiteltexte, private Pfade, lokale Projekte, Modellgewichte, Kontodaten und Laufzeitprotokolle gehören nicht in Git.

Die Anwendung verwendet SQLite für Projektstatus und Operationsverlauf. Modellgewichte werden nur nach einem ausdrücklichen Klick heruntergeladen und nicht im Repository gespeichert. Siehe [Rechte und Hinweise zu Drittsoftware](../../THIRD_PARTY_NOTICES.md).

## Entwicklung

Siehe die [Entwicklungsanleitung](development.md), den [Architekturüberblick](architecture.md) und die [Release-Prüfliste](../release-check.md). Vollständige Anforderungen und Fortsetzungsstand werden getrennt gepflegt; Laufzeitdaten der lokalen Projektgedächtnis-Dateien sind von Git ausgeschlossen.

## Rechte und Erlaubnisse

Der eigene Quellcode unterliegt den Bedingungen in `RIGHTS.md`. Öffentliche Sichtbarkeit gewährt keine Erlaubnis zur Wiederverwendung. Für Drittsoftware und das Modell gelten deren eigene Lizenzen.
