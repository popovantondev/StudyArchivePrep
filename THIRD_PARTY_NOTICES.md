# Third-party notices

This list is an initial development inventory, not a release bill of materials. Verify the exact versions, enabled build options, license texts, source/offers, and redistribution obligations before packaging or publishing a release.

- **Python** — Python Software Foundation License.
- **PySide6 / Qt for Python** — review and comply with the LGPL option chosen for the final build; include applicable notices and source/relinking materials.
- **PyInstaller** — GPL license with bootloader exception; review its exception and bundled runtime-hook licenses for the exact release.
- **FFmpeg / ffprobe** — configure and audit the exact build, enabled codecs, linked libraries, LGPL/GPL status, source obligations, and notices. Do not assume every prebuilt FFmpeg binary is redistributable under the same terms.
- **llama.cpp** — MIT License; include the relevant notice for the pinned build.
- **Qwen3-4B GGUF weights** — the upstream model card states Apache-2.0; retain the exact model card and license revision used by the released downloader. The weights are downloaded separately and are not embedded in Git or the application archive.

Before release, replace this inventory with a verified component list and include the exact required license texts in the application archive.
