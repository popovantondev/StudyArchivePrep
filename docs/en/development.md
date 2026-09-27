# Development

## Requirements

- macOS 13 or later on Apple Silicon
- Python 3.12
- Xcode Command Line Tools for packaging the native application

## Setup and checks

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Keep unit checks deterministic, offline, and independent of real study folders, Telegram accounts, and model services. Use temporary directories and small synthetic fixtures. Check generated archive contents and preserved source files.

The local `.work-memory` folder holds implementation task status, continuation notes, and evidence. It is ignored by Git. Do not copy its machine-specific contents to public documentation.

## Release

Build from a reviewed, clean Git commit. Start with a new versioned output directory; do not replace an existing release. Test the actual app archive using a fresh app-data directory. Follow the release checklist and verify the full repository, archive, screenshots, third-party licenses, and checksum before publishing.

Install CMake and Xcode Command Line Tools for the native components, then run `scripts/build_macos_native_tools.sh`. The script pins source revisions and verifies the FFmpeg SHA-256. Install Python build requirements with `python -m pip install -e '.[build]'`, then run `scripts/build_macos_app.sh`; the app is written to `release-build/app-dist/StudyArchivePrep.app`. Run `scripts/package_macos_release.sh` to create the ZIP and SHA-256 file without replacing an existing archive. The local ad-hoc signature is not a Developer ID signature or notarization.
