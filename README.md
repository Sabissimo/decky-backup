# Deck Backup

One-tap backup and restore of your entire Decky setup — so a SteamOS reinstall or a new Steam Deck doesn't mean rebuilding everything by hand.

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin.

## What it backs up

| Component | Path | Contents |
|---|---|---|
| Plugin settings | `~/homebrew/settings` | Every plugin's config — PowerTools profiles, etc. |
| CSS themes | `~/homebrew/themes` | CSS Loader themes |
| Plugin data | `~/homebrew/data` | Plugin runtime data (optional, can be large) |
| Plugin list | manifest | Names + versions of all installed plugins |

Backups are timestamped `.tar.gz` archives written to internal storage (`~/homebrew/data/decky-backup/backups`), to an SD card (`<sd>/decky-backups`), or to a **Deck Backup** folder in your Google Drive. Each archive contains a `manifest.json` recording what was saved and which plugins were installed at the time.

## Features

- Pick components (settings / themes / data) with a live size estimate
- Back up to internal storage, SD card, or Google Drive
- Browse, restore, and delete backups from the Quick Access Menu — local and cloud in one list
- **Per-plugin restore**: pick exactly which plugins' settings/data to restore from a backup (or restore everything)
- **Auto-reinstall**: after a restore, missing plugins are offered for one-tap reinstall through Decky's own store install flow (native confirmation prompt, verified downloads)
- **Automatic backups**: daily or weekly, to any destination, with retention (keep last N — older auto-backups are pruned, manual ones never touched)
- Backups survive plugin uninstall — they're never deleted automatically

## Google Drive setup

None. Hit **Connect Google Drive** in the plugin: the Deck shows a short code, you enter it at the URL shown (google.com/device) on your phone or PC, done. The plugin uses the `drive.file` OAuth scope, so it can only ever see files it created itself — never the rest of your Drive.

This works out of the box because releases bundle a shared OAuth client (in `py_modules/gdrive.py`; its consent screen is published, so any Google account can connect). Google does not treat device-flow client secrets as confidential, so shipping them in source is standard practice — rclone does the same.

### Using your own OAuth client (optional)

If you'd rather not use the bundled client, create your own free one in [Google Cloud Console](https://console.cloud.google.com/): new project → enable the **Google Drive API** → OAuth client of type **"TVs and Limited Input devices"** (publish the consent screen, or add yourself as a test user). Then write it to `~/homebrew/settings/decky-backup/gdrive_client.json`:

```json
{"client_id": "your-id.apps.googleusercontent.com", "client_secret": "your-secret"}
```

A user-supplied client always takes precedence over the bundled one; disconnect and reconnect Drive after changing it.

## Automatic backups

Enable in the **Automatic backups** section: pick daily/weekly, a destination, and how many auto-backups to keep. The scheduler checks every 30 minutes while the Deck is awake and catches up after sleep or reboot (first check ~5 minutes after boot). If the chosen destination is unavailable (SD card ejected, Drive disconnected), it falls back to internal storage and says so in the completion toast.

Backups made on a schedule are tagged `auto` in the list and named `deckbackup-auto-*`; only these are subject to retention pruning.

> Why no "backup on shutdown"? Decky gives plugins almost no time during unload — a tar + cloud upload would be killed mid-write, silently producing corrupt backups. An interval scheduler that catches up on wake is reliable; a shutdown hook is not.

## Installing from CI builds

Every push to `main` builds an installable zip via GitHub Actions (see the workflow run's **Artifacts**); tagged releases (`v*`) attach the zip to a GitHub Release. To sideload: extract so you get `~/homebrew/plugins/decky-backup/`, then restart Decky Loader.

## Roadmap

- [x] Scheduled automatic backups with retention
- [x] Automatic reinstall of missing plugins from the Decky store on restore
- [x] Bundled shared OAuth client (zero-setup Google Drive)
- [ ] Submission to the official Decky plugin store
- [ ] Other cloud destinations (Dropbox, OneDrive, rclone remotes)
- [ ] Controller layout + non-Steam shortcut backup

## Development

```bash
npm ci
npm run build              # bundles src/ -> dist/index.js via @decky/rollup
python3 tests/run_tests.py # backend unit tests (decky module is stubbed)
```

Both also run in CI on every push. Backend is pure-stdlib Python (`main.py` + `py_modules/gdrive.py`), frontend is React/TypeScript (`src/index.tsx`) using `@decky/ui` and `@decky/api`.

Deploy to a Deck for testing via Decky settings → Developer → **Install Plugin from URL** (paste a release zip URL), or copy the plugin folder (with `dist/`, `main.py`, `py_modules/`, `plugin.json`, `package.json`) to `~/homebrew/plugins/decky-backup` and restart Decky Loader.

## License

BSD-3-Clause
