# Release checklist

Use this checklist only after the release build and documentation are ready.

- [ ] Start from a clean, reviewed commit on the intended release branch.
- [ ] Confirm that the app version and changelog entry agree.
- [ ] Run the full deterministic unit suite.
- [ ] Build a new Apple Silicon archive without replacing an earlier build.
- [ ] Extract the archive with macOS archive tooling and verify bundle and executable permissions.
- [ ] Launch the packaged application with a new empty data directory.
- [ ] Exercise source-folder selection, project reopening, output preview, cancel/recovery, and language switch with synthetic data.
- [ ] Confirm the local title model has no listener exposed on the network interface and works offline after model download.
- [ ] Verify model source revision, model checksum, engine revision, third-party notices, and license texts.
- [ ] Inspect Git diff, commit history, release archive, docs and screenshots for personal paths/data, credentials, local projects, real SRT, model weights, and session files.
- [ ] Confirm `publication-plan.json` passes the consumer's compatibility and tamper tests in an isolated sender worktree.
- [ ] Generate `SHA256SUMS.txt` from the final archive and verify the checksums.
- [ ] Confirm GitHub contains exactly the reviewed commit and no unreviewed local artifacts.

Never use real Telegram credentials or send actual study files as a release check.
