# Study Archive Prep

**[Русский](../ru/README.md) · [Deutsch](README.md) · [English](../../README.md)**

macOS 13 oder neuer · Apple Silicon · Version 0.1.0

Study Archive Prep ordnet Lernmaterial nach Datum, hilft bei der Prüfung von Aufnahmen und Untertiteln und erstellt einen Veröffentlichungsplan für Telegram Media Sender.

## Projektstatus

Dies ist eine frühe Entwicklungsversion. Der erste Bildschirm erfasst Quellordner und einen getrennten Ausgabeordner. Scannen, Verarbeitung, Export des Veröffentlichungsplans und lokale Titelvorschläge werden noch entwickelt. Diese Version sendet keine Telegram-Nachrichten.

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

Der Nutzer wählt die Quellordner. Diese Version scannt oder sendet noch keine Dateien an Telegram. Lernmaterial, Untertiteltexte, private Pfade, lokale Projekte, Modellgewichte, Kontodaten und Laufzeitprotokolle gehören nicht in Git.

Die Anwendung verwendet SQLite und wird lokale Sprachmodelle für Titelvorschläge verwenden. Modellgewichte werden nur auf ausdrücklichen Wunsch heruntergeladen und nicht im Repository gespeichert. Siehe [Rechte und Hinweise zu Drittsoftware](../../THIRD_PARTY_NOTICES.md).

## Entwicklung

Siehe die [Entwicklungsanleitung](development.md), den [Architekturüberblick](architecture.md) und die [Release-Prüfliste](../release-check.md). Vollständige Anforderungen und Fortsetzungsstand werden getrennt gepflegt; Laufzeitdaten der lokalen Projektgedächtnis-Dateien sind von Git ausgeschlossen.

## Rechte und Erlaubnisse

Der eigene Quellcode unterliegt den Bedingungen in `RIGHTS.md`. Öffentliche Sichtbarkeit gewährt keine Erlaubnis zur Wiederverwendung. Für Drittsoftware und das Modell gelten deren eigene Lizenzen.
