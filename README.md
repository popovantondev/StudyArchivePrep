# Study Archive Prep

**[Русский](docs/ru/README.md) · [Deutsch](docs/de/README.md) · [English](README.md)**

macOS 13 or newer · Apple Silicon · Version 0.1.0

Study Archive Prep organizes study files into dated folders, helps review recordings and subtitles, and prepares an ordered publication plan for Telegram Media Sender.

## Project status

This is an early development build. The first screen currently collects source folders and a separate output folder. Scanning, processing, publishing-plan export, and local title suggestions are still being implemented. This build does not send Telegram messages.

## Run from source

Requires Python 3.12 and macOS.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
study-archive-prep
```

For an isolated UI preview, pass `--data-dir /tmp/study-archive-prep-preview`. The option redirects local app settings and project data.

## Safety and privacy

Source folders are selected by the user and are not scanned until a project scan action is added. No files are uploaded by this application. Never add study files, subtitle text, personal paths, local projects, model weights, account credentials, or runtime logs to Git.

The project uses a SQLite database and will use a local language model for title suggestions. Model weights are downloaded only after the user asks for them and will not be stored in this repository. See the [rights and third-party notices](THIRD_PARTY_NOTICES.md).

## Development

See the [development guide](docs/en/development.md), [architecture overview](docs/en/architecture.md), and [release checklist](docs/release-check.md). The full accepted requirements and progress handoff are maintained separately; runtime project memory is excluded from Git.

## License and permissions

The project owner's code remains under the rights stated in `RIGHTS.md`; no license for reuse is granted by public visibility alone. Third-party software and model licenses remain applicable.
