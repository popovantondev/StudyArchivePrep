# Third-party software and model notices

This release is built for macOS 13 or later on Apple Silicon. The application archive includes the corresponding license notices and source archives under `StudyArchivePrep.app/Contents/Frameworks` resources. The matching source revisions and build options are recorded beside those archives.

## Components included in the macOS application

- **Python 3.12.14** — Python Software Foundation License. The runtime and license text are bundled. The Python source release is available at <https://www.python.org/downloads/release/python-31214/>.
- **PySide6 / Qt for Python 6.10.2 and shiboken6 6.10.2** — LGPL-3.0-only or GPL-2.0-only or GPL-3.0-only. This application selects the LGPL option and dynamically links Qt libraries. LGPL-3.0 and GPL-3.0 license texts are included. Qt for Python license/source information: <https://doc.qt.io/qtforpython-6/licenses.html>; exact source release: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.2-src/>. Qt 6.10.2 source: <https://download.qt.io/official_releases/qt/6.10/6.10.2/single/>. Users can replace compatible Qt libraries in the app bundle under the LGPL terms. The source archives for these two large upstream projects are linked above rather than embedded in this development archive.
- **PyInstaller 6.19.0** — GPL-2.0-or-later with the bootloader exception. Its license is included in the application resources. Build helpers include `altgraph`, `macholib`, `packaging`, `pyinstaller-hooks-contrib`, and `setuptools`; their package metadata and licenses are published by their respective projects.
- **FFmpeg and ffprobe 8.1.3** — LGPL-2.1-or-later. Built from the official FFmpeg source archive with `--disable-gpl --disable-nonfree --disable-network --disable-autodetect`; no GPL or nonfree components are enabled. The exact source archive, SHA-256, and configure options are bundled alongside the executables. FFmpeg license and source: <https://ffmpeg.org/legal.html> and <https://ffmpeg.org/download.html>.
- **llama.cpp** — MIT License, pinned to commit `7fe450e19305b828c199d602c23a8337aaa1f03b`. Built with Metal enabled and OpenSSL disabled. The exact source archive, MIT license, and upstream license directory are included. Source: <https://github.com/ggml-org/llama.cpp>.

## Optional model download

The application does not include model weights. If the user requests it, the app downloads `Qwen3-4B-Q4_K_M.gguf` (2,497,280,256 bytes) from the pinned `Qwen/Qwen3-4B-GGUF` revision `bc640142c66e1fdd12af0bd68f40445458f3869b`. SHA-256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`. The model card declares Apache-2.0. Model card and license: <https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/bc640142c66e1fdd12af0bd68f40445458f3869b/README.md> and <https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/bc640142c66e1fdd12af0bd68f40445458f3869b/LICENSE>.

## Distribution notes

The application bundle includes exact FFmpeg and llama.cpp source archives and their notices; source for Qt for Python and Qt is linked above. This 0.1.0 archive is a local development artifact, not a public binary release: its LGPL relinking/source package has not been independently audited. The app is ad-hoc signed and not notarized; macOS may require the user to approve opening it. Complete a release-specific license/source review and Developer ID signing/notarization before distributing a public app binary.
