# Architektur

Die Anwendung trennt die Qt-Oberfläche von testbaren Python-Modulen für Projektstatus, Scans, Dateiverarbeitung, Titelvorschläge, Speicherung und Export der Veröffentlichungsreihenfolge. Lange Scans und Medienoperationen laufen getrennt vom UI-Thread.

Das angenommene Verhalten steht in `docs/PLAN.md`. Die Aufgaben werden einzeln aus der lokalen `.work-memory/TASKS.md`-Warteschlange bearbeitet. Projekte und Protokolle bleiben in lokalen Anwendungsdaten; automatische Tests verwenden synthetische Beispiele.

Die Anwendung sendet selbst keine Dateien an Telegram. Der separate Telegram Media Sender liest die lokale versionierte Datei `publication-plan.json`.

FFprobe ermittelt die Audiospuren. FFmpeg übernimmt die gewählte Spur mit Stream Copy (`-c:a copy`) ohne Neukodierung. Die Anwendung installiert die Audiodatei erst, nachdem Spur, Codec, Dauer und vollständiges Lesen geprüft wurden. Der Release muss ein geprüftes FFmpeg/FFprobe-Paar und die zugehörigen Hinweise enthalten.

Kopier- und Archivoperationen haben ein privates SQLite-Protokoll, Prüfsummen pro Schritt, Wiederherstellung nach einem Neustart und eine Sperre für einzelne Schreibvorgänge. Das Löschen von Originalen ist eine separate, ausgeschaltete Option: Es erfordert eine exakt bestätigte Pfadliste, eine erneut geprüfte Audiodatei, unveränderte Quelldaten und die Bestätigung, dass weitere ausgewählte Containerdaten gespeichert wurden.

Titelvorschläge verwenden die festgelegte Datei Qwen3-4B Q4_K_M (2.497.280.256 Bytes; SHA-256 steht in `local_model.py`) und eine festgelegte Version des llama.cpp-CLI. Internet ist nur für den ersten Modelldownload nötig. Der Download kann mit HTTP Range fortgesetzt werden und wird erst nach Größen- und Prüfsummenprüfung installiert. Die Inferenz läuft als lokaler Prozess; der Text gelangt über eine private temporäre Promptdatei hinein.

Die SRT-Analyse liest nur die ersten fünf oder zehn Minuten und entfernt Anzeige-Markup, ohne die Quelldatei zu ändern. Das lokale Modell schlägt einen kurzen russischen Titel vor. Dateinamen werden nur bei einer eindeutigen Gruppe mit gleichem Grundnamen vorgeschlagen; Sprach- und Qualitätsvarianten bleiben erhalten. Die Übernahme benötigt die genaue Bestätigung und betrifft ausschließlich vorbereitete Ausgabedateien.

Für den Sender wird `publication-plan.json` Version 1 exportiert. Die Datei enthält geordnete Textnachrichten und geprüfte Ausgabedateien mit relativen Pfaden, Byte-Größen und SHA-256-Werten. Absolute Pfade und SRT-Inhalte fehlen; eine vorhandene Plandatei wird nicht überschrieben.
