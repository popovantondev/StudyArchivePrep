<!-- ppk-readme:head:start -->
<a href="https://popovantondev.github.io/StudyArchivePrep/index-en.html"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/header-en-dark.37205952.svg"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/header-en-light.8ba464f5.svg" width="880" height="188" alt="Study Archive Prep — Organizes study materials by date and extracts audio. macOS 13+ · Apple Silicon, Source only 0.1.0"></picture></a>
<!-- ppk-readme:head:end -->

# Study Archive Prep

[Русский](README.ru.md) · [Deutsch](README.md) · **English**

<!-- ppk-readme:body:start -->
<p>
<a href="https://github.com/popovantondev/StudyArchivePrep"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-source-en-dark.6c26e348.svg"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-source-en-light.35286b46.svg" width="109" height="36" alt="Source"></picture></a>
<a href="https://popovantondev.github.io/StudyArchivePrep/index-en.html"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-website-en-dark.b21ceabf.svg"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-website-en-light.668ccc63.svg" width="120" height="36" alt="Website"></picture></a>
<a href="https://popovantondev.github.io/StudyArchivePrep/Guide-en.html"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-guide-en-dark.3702391b.svg"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-guide-en-light.e7be3f3a.svg" width="141" height="36" alt="User guide"></picture></a>
<a href="https://github.com/popovantondev/StudyArchivePrep/issues/new/choose"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-bug-en-dark.593a4e3a.svg"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/btn-bug-en-light.d1495d84.svg" width="196" height="36" alt="Report a problem"></picture></a>
</p>

<p><a href="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/images/study-archive-prep-workspace-en.png"><picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/preview-en-dark.0d07248e.webp"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/preview-en-light.d6faa404.webp" width="880" height="516" alt="Study Archive Prep interface"></picture></a><br>
<sub><a href="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/images/study-archive-prep-workspace-en.png">Full screenshot</a></sub></p>

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/divider-dark.4fe89eda.svg"><img src="https://raw.githubusercontent.com/popovantondev/StudyArchivePrep/main/docs/readme/divider-light.db9fb42e.svg" width="880" height="6" alt="Divider"></picture>
<!-- ppk-readme:body:end -->

<!-- public-release:start -->
Organize study materials by date, extract audio and prepare a publication order for Telegram Media Sender.

**macOS 13+ · Apple Silicon · Source only 0.1.0**

**[Source](https://github.com/popovantondev/StudyArchivePrep)** · **[User guide](https://popovantondev.github.io/StudyArchivePrep/Guide-en.html)** · **[Report a problem](https://github.com/popovantondev/StudyArchivePrep/issues/new/choose)**

**Requirements and limitations:** Early development: source only, no ready-to-install package. Python 3.12; set up the local model and engine separately for title suggestions.

**First steps:** Follow the source setup guide. This app does not send materials to Telegram itself.
<!-- public-release:end -->

Study Archive Prep organizes study files into dated folders, helps review recordings and subtitles, and prepares an ordered publication plan for Telegram Media Sender.

## Project status

This is an early development build. It scans selected source folders, groups files by dates and weeks, lets you review and edit the publication order, copies files and creates ZIP archives with a local recovery journal, extracts audio from video without re-encoding, and exports a versioned publication plan. Local Russian title suggestions use the selected first five or ten minutes of an SRT after the model and local inference engine are installed. This app does not send Telegram messages.

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

Source folders are selected by the user and scanned locally when a project is created or rescanned. Processing writes to a separate output folder, uses temporary files and a private recovery journal, and does not replace existing files. Extracted audio is kept in private app data before it is copied to the prepared output. Original recordings are retained. No files are uploaded by this application. Never add study files, subtitle text, personal paths, local projects, model weights, account credentials, or runtime logs to Git.

The project uses SQLite for project state and operation history. Model weights are downloaded only after the user asks for them and are not stored in this repository. See the [rights and third-party notices](THIRD_PARTY_NOTICES.md).

## Development

See the [development guide](docs/en/development.md), [architecture overview](docs/en/architecture.md), and [release checklist](docs/release-check.md).

See [changelog](CHANGELOG.md) for version history and [third-party notices](THIRD_PARTY_NOTICES.md) for included component terms.

## License and permissions

The project owner's code remains under the rights stated in `RIGHTS.md`; no license for reuse is granted by public visibility alone. Third-party software and model licenses remain applicable.
