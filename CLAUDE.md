# Deck Backup

Decky Loader (Steam Deck) plugin: backup/restore of `~/homebrew` settings, CSS themes, and plugin data to internal storage, SD card, or Google Drive, with per-plugin selective restore, scheduled auto-backups, and auto-reinstall of missing plugins.

## Commands

```bash
npm ci                      # install (npm, not pnpm; lockfile is package-lock.json)
npm run build               # rollup: src/index.tsx -> dist/index.js
python3 tests/run_tests.py  # backend unit tests; stubs the decky module
```

CI (`.github/workflows/build.yml`) runs all three on push, assembles the plugin zip, uploads it as an artifact, and attaches it to a Release on `v*` tags.

## Architecture

- `main.py` — plugin backend (class `Plugin`, async methods callable from the frontend via `@decky/api` `callable`). Pure stdlib. Blocking work (tar, network) runs in executor threads; progress goes to the frontend via `decky.emit` events (`backup_progress`, `auto_backup`).
- `py_modules/gdrive.py` — stdlib-only Google Drive client: OAuth device flow (`drive.file` scope), resumable upload, list/download/delete. Bundled shared OAuth client in `DEFAULT_CLIENT_ID`/`DEFAULT_CLIENT_SECRET`; a user client in `~/homebrew/settings/decky-backup/gdrive_client.json` takes precedence. The bundled client's Google Cloud setup is complete and live-verified (Google Cloud project `decky-backup`: device-code flow tested, consent screen **in production** so there are no test-user limits, Drive API enabled) — do not redo it.
- `src/index.tsx` — the whole frontend (QAM panel + modals). Auto-reinstall calls Decky Loader's own `utilities/install_plugin(s)` routes through the `window.DeckyBackend` global so the loader shows its native confirm modal and does verified downloads.

Backup archives: `deckbackup-[auto-]YYYYMMDD-HHMMSS.tar.gz` containing `manifest.json` (plugin list + versions) plus `settings/`, `themes/`, `data/` subtrees. Cloud backups are addressed as `gdrive:<fileId>` and cached under the plugin runtime dir on restore.

## Deck-runtime facts (live-debugged on real hardware, 2026-07-15)

- Decky's embedded Python can't verify HTTPS (its OpenSSL default CA paths
  don't exist on SteamOS) — every `urlopen` in `gdrive.py` passes the
  shared `_SSL_CONTEXT`, which falls back to
  `/etc/ssl/certs/ca-certificates.crt`. Keep `context=` on any new call.
- On the Deck, a dropdown opens a full-screen menu; closing it REMOUNTS
  the QAM content and resets useState. The manual destination lives at
  module scope (`rememberedDestId`) so the pick survives — don't move it
  back into plain state.
- `ButtonItem` is a full-width row control; compact icon buttons in a row
  are `DialogButton`s with a fixed width inside a `Focusable`.
- This plugin is root-flagged: its installed files on the Deck are
  root-owned (deploying by scp needs /tmp + `sudo mv`).
- Verified end-to-end on hardware: device-flow connect, manual backup to
  Google Drive, and the destination dropdown holding its selection.

## Constraints and decisions

- No "backup on shutdown": Decky kills plugins during `_unload`; the interval scheduler (30-min tick, catches up after sleep) is the reliable substitute.
- Restore sanitizes archive members (no absolute paths, no `..`, no links) — keep `_safe_members` in the extraction path.
- Auto-backup retention prunes only `deckbackup-auto-*`; never delete manual backups programmatically.
- The plugin's own runtime dir is excluded from backups (recursion guard in `_create_archive`).
- Backend must stay stdlib-only (no pip deps on the Deck).

## Releasing

Bump the version in **both** `package.json` and `VERSION` in `main.py`, push, then tag `v*` and push the tag (a tag pushed together with the branch may not trigger CI — push it separately).
