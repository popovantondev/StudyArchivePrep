# Architecture

The application is split into a Qt interface and testable Python modules for project state, scanning, file processing, title suggestions, persistence, and publication-plan export. Long-running scans and media operations run away from the UI thread.

The accepted behavior is defined in `docs/PLAN.md`. Implement one task from the local `.work-memory/TASKS.md` queue at a time. Project files and logs remain in local application data; synthetic fixtures are used by automated tests.

No code in the application sends files to Telegram. The optional `publication-plan.json` is a versioned local interchange file consumed by the separate Telegram Media Sender.

Audio tracks are inspected with FFprobe. FFmpeg uses audio stream copy (`-c:a copy`) and installs an output only after track, codec, duration, and full-read checks pass. No audio is re-encoded. The release build must bundle an audited FFmpeg/FFprobe pair and include its applicable notices.

Copy and archive operations have a private SQLite journal, per-operation checksums, restart reconciliation, and a single-writer lock. Deleting originals is a separate opt-in action that requires an exact approved path list, a rechecked audio receipt, an unchanged source fingerprint, and confirmation that other selected container data was saved.

Title suggestions use the pinned Qwen3-4B Q4_K_M file (2,497,280,256 bytes, SHA-256 recorded in `local_model.py`) and the llama.cpp CLI at the pinned commit. Internet access is used only for the first model download. Downloads resume through HTTP ranges and are installed only after size and checksum verification; inference runs as a local process and receives transcript text through a private temporary prompt file.

Subtitle analysis reads only the first five or ten minutes of SRT cues and removes display markup without changing the source. The local model proposes one short Russian title. Related file names are proposed only for an unambiguous same-stem group; language and quality variants remain in the output names. Applying a proposal requires an exact approval and touches prepared output files only.
