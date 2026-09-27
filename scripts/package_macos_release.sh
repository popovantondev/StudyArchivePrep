#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/release-build/app-dist/StudyArchivePrep.app"
VERSION="$(PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" -c 'from study_archive_prep import __version__; print(__version__)')"
OUT="$ROOT/release-build/releases"
ARCHIVE="$OUT/StudyArchivePrep-$VERSION-macos-arm64.zip"
SUMS="$OUT/SHA256SUMS.txt"

[[ -d "$APP" ]] || { echo "Build the .app bundle first." >&2; exit 2; }
mkdir -p "$OUT"
[[ ! -e "$ARCHIVE" ]] || { echo "Refusing to replace an existing release archive: $ARCHIVE" >&2; exit 2; }
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ARCHIVE"
(cd "$OUT" && shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$SUMS")")
(cd "$OUT" && shasum -a 256 -c "$(basename "$SUMS")")
printf 'Archive: %s\nChecksums: %s\n' "$ARCHIVE" "$SUMS"
