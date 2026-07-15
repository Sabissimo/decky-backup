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

Backups are timestamped `.tar.gz` archives written to internal storage (`~/homebrew/data/decky-backup/backups`) or to an SD card (`<sd>/decky-backups`), each containing a `manifest.json` recording what was saved and which plugins were installed at the time.

## Features

- Pick components (settings / themes / data) with a live size estimate
- Back up to internal storage or SD card
- Browse, restore, and delete backups from the Quick Access Menu
- Restore overwrites settings/themes in place and tells you which plugins from the backup are missing so you can reinstall them from the store
- Backups survive plugin uninstall — they're never deleted automatically

## Roadmap

- [ ] Automatic reinstall of missing plugins from the Decky store on restore
- [ ] Scheduled automatic backups (daily / on shutdown)
- [ ] Cloud destinations (rclone-compatible remotes)
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
