# Architecture

The application is split into a Qt interface and testable Python modules for project state, scanning, file processing, title suggestions, persistence, and publication-plan export. Long-running scans and media operations run away from the UI thread.

The accepted behavior is defined in `docs/PLAN.md`. Implement one task from the local `.work-memory/TASKS.md` queue at a time. Project files and logs remain in local application data; synthetic fixtures are used by automated tests.

No code in the application sends files to Telegram. The optional `publication-plan.json` is a versioned local interchange file consumed by the separate Telegram Media Sender.

Audio tracks are inspected with FFprobe. FFmpeg uses audio stream copy (`-c:a copy`) and installs an output only after track, codec, duration, and full-read checks pass. No audio is re-encoded. The release build must bundle an audited FFmpeg/FFprobe pair and include its applicable notices.

Copy and archive operations have a private SQLite journal, per-operation checksums, restart reconciliation, and a single-writer lock. Deleting originals is a separate opt-in action that requires an exact approved path list, a rechecked audio receipt, an unchanged source fingerprint, and confirmation that other selected container data was saved.
