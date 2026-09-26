# Third-party notices

This list is an initial development inventory, not a release bill of materials. Verify the exact versions, enabled build options, license texts, source/offers, and redistribution obligations before packaging or publishing a release.

- **Python** — Python Software Foundation License.
- **PySide6 / Qt for Python** — review and comply with the LGPL option chosen for the final build; include applicable notices and source/relinking materials.
- **PyInstaller** — GPL license with bootloader exception; review its exception and bundled runtime-hook licenses for the exact release.
- **FFmpeg / ffprobe** — configure and audit the exact build, enabled codecs, linked libraries, LGPL/GPL status, source obligations, and notices. Do not assume every prebuilt FFmpeg binary is redistributable under the same terms.
- **llama.cpp** — pinned for development to release `v0.5.0`, commit `7fe450e19305b828c199d602c23a8337aaa1f03b`; MIT License. Verify the exact source archive and include its notice in each release.
- **Qwen3-4B GGUF weights** — pinned to `Qwen/Qwen3-4B-GGUF` revision `bc640142c66e1fdd12af0bd68f40445458f3869b`, file `Qwen3-4B-Q4_K_M.gguf`, 2,497,280,256 bytes, SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`. The model card declares Apache-2.0. The file is downloaded separately and is not embedded in Git or the application archive; the installer records links to the exact pinned model card and LICENSE.

Before release, replace this inventory with a verified component list and include the exact required license texts in the application archive.
