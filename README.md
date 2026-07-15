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
- Restore tells you which plugins from the backup are missing so you can reinstall them from the store
- **Automatic backups**: daily or weekly, to any destination, with retention (keep last N — older auto-backups are pruned, manual ones never touched)
- Backups survive plugin uninstall — they're never deleted automatically

## Google Drive setup (one-time, ~2 minutes)

The plugin authenticates with Google's device flow: it shows a short code on the Deck, you enter it on your phone at the URL shown, done. It uses the `drive.file` scope, so it can only ever see files it created — never the rest of your Drive.

You bring your own (free) OAuth client:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project (any name)
2. **APIs & Services → Library** → enable **Google Drive API**
3. **APIs & Services → OAuth consent screen** → External → fill in the app name + your email → add yourself as a test user
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** → application type **"TVs and Limited Input devices"**
5. Copy the Client ID and Client secret into the plugin when prompted (stored only on your Deck, in `~/homebrew/settings/decky-backup/`)

Then hit **Connect Google Drive** in the plugin and follow the code prompt.

## Automatic backups

Enable in the **Automatic backups** section: pick daily/weekly, a destination, and how many auto-backups to keep. The scheduler checks every 30 minutes while the Deck is awake and catches up after sleep or reboot (first check ~5 minutes after boot). If the chosen destination is unavailable (SD card ejected, Drive disconnected), it falls back to internal storage and says so in the completion toast.

Backups made on a schedule are tagged `auto` in the list and named `deckbackup-auto-*`; only these are subject to retention pruning.

> Why no "backup on shutdown"? Decky gives plugins almost no time during unload — a tar + cloud upload would be killed mid-write, silently producing corrupt backups. An interval scheduler that catches up on wake is reliable; a shutdown hook is not.

## Installing from CI builds

Every push to `main` builds an installable zip via GitHub Actions (see the workflow run's **Artifacts**); tagged releases (`v*`) attach the zip to a GitHub Release. To sideload: extract so you get `~/homebrew/plugins/decky-backup/`, then restart Decky Loader.

## Roadmap

- [x] Scheduled automatic backups with retention
- [ ] Automatic reinstall of missing plugins from the Decky store on restore
- [ ] Shared OAuth client for store release (skip the Cloud Console setup)
- [ ] Other cloud destinations (Dropbox, OneDrive, rclone remotes)
- [ ] Controller layout + non-Steam shortcut backup

## Development

```bash
pnpm install
pnpm run build   # bundles src/ -> dist/index.js via @decky/rollup
```

Deploy to a Deck for testing by copying the plugin folder (with `dist/`, `main.py`, `plugin.json`, `package.json`) to `~/homebrew/plugins/decky-backup` and restarting Decky Loader, or use [decky-cli / VS Code deploy tasks](https://github.com/SteamDeckHomebrew/decky-plugin-template#development) from the plugin template.

Backend is pure-stdlib Python (`main.py`), frontend is React/TypeScript (`src/index.tsx`) using `@decky/ui` and `@decky/api`.

## License

BSD-3-Clause
