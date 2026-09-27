#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NATIVE="$ROOT/release-deps/macos-arm64"
DIST="$ROOT/release-build/app-dist"
WORK="$ROOT/release-build/pyinstaller-work"
PYTHON="$ROOT/.venv/bin/python"
PYINSTALLER_LICENSE="$ROOT/.venv/lib/python3.12/site-packages/PyInstaller-6.19.0.dist-info/licenses/COPYING.txt"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "Build the app on an Apple Silicon Mac." >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Create the project virtual environment and install the pinned build requirements first." >&2
  exit 2
fi
for needed in "$NATIVE/ffmpeg/ffmpeg" "$NATIVE/ffmpeg/ffprobe" "$NATIVE/llama/llama-cli"; do
  [[ -x "$needed" ]] || { echo "Missing native tool: $needed" >&2; exit 2; }
done

ARGS=(--noconfirm --clean --windowed --name StudyArchivePrep --paths "$ROOT/src"
  --osx-bundle-identifier org.studyarchiveprep.StudyArchivePrep
  --target-arch arm64 --distpath "$DIST" --workpath "$WORK" --specpath "$WORK"
  --add-binary "$NATIVE/ffmpeg/ffmpeg:study_archive_prep/tools"
  --add-binary "$NATIVE/ffmpeg/ffprobe:study_archive_prep/tools"
  --add-binary "$NATIVE/llama/llama-cli:resources/bin"
  --add-data "$NATIVE/ffmpeg/COPYING.LGPLv2.1:resources/licenses/ffmpeg"
  --add-data "$NATIVE/ffmpeg/BUILD-INFO.txt:resources/licenses/ffmpeg"
  --add-data "$NATIVE/ffmpeg/ffmpeg-8.1.3-source.tar.xz:resources/source"
  --add-data "$NATIVE/llama/LICENSE:resources/licenses/llama.cpp"
  --add-data "$NATIVE/llama/licenses:resources/licenses/llama.cpp/licenses"
  --add-data "$NATIVE/llama/BUILD-INFO.txt:resources/licenses/llama.cpp"
  --add-data "$NATIVE/llama/llama.cpp-7fe450e19305b828c199d602c23a8337aaa1f03b-source.tar.gz:resources/source"
  --add-data "$ROOT/THIRD_PARTY_NOTICES.md:resources/licenses"
  --add-data "$ROOT/licenses/LGPL-3.0.txt:resources/licenses"
  --add-data "$ROOT/licenses/GPL-3.0.txt:resources/licenses"
  --add-data "$ROOT/licenses/Python-3.12-PSF-License.txt:resources/licenses"
  --add-data "$PYINSTALLER_LICENSE:resources/licenses/pyinstaller")
for library in "$NATIVE"/llama/*.dylib; do
  ARGS+=(--add-binary "$library:resources/bin")
done
"$PYTHON" -m PyInstaller "${ARGS[@]}" "$ROOT/scripts/pyinstaller_entry.py"

APP="$DIST/StudyArchivePrep.app"
[[ -d "$APP" ]] || { echo "The app bundle was not generated." >&2; exit 1; }
codesign --force --deep --sign - "$APP"
"$APP/Contents/MacOS/StudyArchivePrep" --version
printf 'Build directory: %s\n' "$APP"
