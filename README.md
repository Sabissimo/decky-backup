# Deck Backup

Back up everything you've set up on your Steam Deck — plugin settings, themes, and your plugin list — and bring it all back in a couple of taps. Save backups on the Deck, an SD card, or Google Drive.

A plugin for [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).

## Why

Reinstalling SteamOS (or moving to a new Deck) normally means redoing every plugin setting, theme, and tweak by hand. Deck Backup turns that into a two-minute restore.

## Install

Not in the Decky store yet. Until then:

1. In Game Mode, open Decky settings (the gear) → **Developer** → enable developer mode
2. Choose **Install Plugin from URL** and paste:
   `https://github.com/Sabissimo/decky-backup/releases/latest/download/decky-backup.zip`

## How to use it

**Back up** — open the Quick Access Menu → Deck Backup, choose what to include, pick a destination, hit **Back up now**. The button shows roughly how big the backup will be.

**Restore** — pick a backup from the list. Restore everything, or switch off "Restore everything" and pick just the plugins you want back. If the backup mentions plugins you no longer have installed, Deck Backup offers to reinstall them from the store for you.

**Automatic backups** — flip it on, choose daily or weekly and a destination. It keeps the last few automatic backups and cleans up older ones; backups you made yourself are never touched.

**Google Drive** — tap **Connect Google Drive**, enter the short code it shows at google.com/device on your phone, done. The plugin can only see the backups it uploaded — nothing else in your Drive, guaranteed by the permission it asks for.

## Good to know

- Backups survive uninstalling the plugin.
- If your SD card or Drive isn't reachable when a scheduled backup runs, it saves to internal storage instead and tells you.
- Scheduled backups run while the Deck is awake and catch up after sleep or a reboot. (There's no "back up at shutdown" — SteamOS doesn't give plugins enough time for that to be safe.)
- After a restore, restart Decky Loader (or the Deck) so plugins pick up their restored settings.

<details>
<summary>What exactly gets backed up, and where it goes</summary>

| Component | Path | Contents |
|---|---|---|
| Plugin settings | `~/homebrew/settings` | Every plugin's config — PowerTools profiles, etc. |
| CSS themes | `~/homebrew/themes` | CSS Loader themes |
| Plugin data | `~/homebrew/data` | Plugin runtime data (optional, can be large) |
| Plugin list | manifest | Names + versions of all installed plugins |

Backups are timestamped `.tar.gz` archives (automatic ones are named `deckbackup-auto-*`), stored in `~/homebrew/data/decky-backup/backups`, `<sd card>/decky-backups`, or a **Deck Backup** folder in your Drive. Each contains a `manifest.json` listing what was saved and which plugins were installed at the time.
</details>

<details>
<summary>Advanced: use your own Google OAuth client</summary>

Releases bundle a shared OAuth client so Drive works with zero setup (device-flow client secrets aren't confidential — rclone ships theirs the same way). If you'd rather use your own: create a free OAuth client in [Google Cloud Console](https://console.cloud.google.com/) (type **"TVs and Limited Input devices"**, Drive API enabled, consent screen published or yourself added as test user), then save it on the Deck as `~/homebrew/settings/decky-backup/gdrive_client.json`:

```json
{"client_id": "your-id.apps.googleusercontent.com", "client_secret": "your-secret"}
```

Your client always wins over the bundled one. Disconnect and reconnect Drive after changing it.
</details>

## Roadmap

- [ ] Submission to the official Decky plugin store
- [ ] Other cloud destinations (Dropbox, OneDrive, rclone remotes)
- [ ] Controller layout + non-Steam shortcut backup

## Development

```bash
npm ci && npm run build     # frontend: src/index.tsx -> dist/index.js
python3 tests/run_tests.py  # backend tests (decky module is stubbed)
```

Both run in CI on every push; tagging `v*` attaches an installable zip to a GitHub Release. Architecture notes live in [CLAUDE.md](CLAUDE.md).

## License

BSD-3-Clause
