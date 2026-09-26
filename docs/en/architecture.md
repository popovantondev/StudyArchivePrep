# Architecture

The application is split into a Qt interface and testable Python modules for project state, scanning, file processing, title suggestions, persistence, and publication-plan export. Long-running scans and media operations run away from the UI thread.

The accepted behavior is defined in `docs/PLAN.md`. Implement one task from the local `.work-memory/TASKS.md` queue at a time. Project files and logs remain in local application data; synthetic fixtures are used by automated tests.

No code in the application sends files to Telegram. The optional `publication-plan.json` is a versioned local interchange file consumed by the separate Telegram Media Sender.
