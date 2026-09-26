# Architektur

Die Anwendung trennt die Qt-Oberfläche von testbaren Python-Modulen für Projektstatus, Scans, Dateiverarbeitung, Titelvorschläge, Speicherung und Export der Veröffentlichungsreihenfolge. Lange Scans und Medienoperationen laufen getrennt vom UI-Thread.

Das angenommene Verhalten steht in `docs/PLAN.md`. Die Aufgaben werden einzeln aus der lokalen `.work-memory/TASKS.md`-Warteschlange bearbeitet. Projekte und Protokolle bleiben in lokalen Anwendungsdaten; automatische Tests verwenden synthetische Beispiele.

Die Anwendung sendet selbst keine Dateien an Telegram. Der separate Telegram Media Sender liest die lokale versionierte Datei `publication-plan.json`.
