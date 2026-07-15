import asyncio
import glob
import io
import json
import os
import sys
import tarfile
import time
from datetime import datetime

import decky

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "py_modules"))
import gdrive  # noqa: E402

VERSION = "0.2.0"

# What we back up, relative to the Decky homebrew root (~/homebrew).
# "settings" holds every plugin's config (PowerTools profiles, etc.),
# "themes" holds CSS Loader themes, "data" holds plugin runtime data.
COMPONENT_DIRS = {
    "settings": "settings",
    "themes": "themes",
    "data": "data",
}

ARCHIVE_PREFIX = "deckbackup-"
MANIFEST_NAME = "manifest.json"
SD_BACKUP_DIRNAME = "decky-backups"
GDRIVE_PREFIX = "gdrive:"

# Our own runtime dir lives under homebrew/data — never back up our own backups.
OWN_DATA_DIRNAME = "decky-backup"


def _internal_backup_dir() -> str:
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "backups")


def _cloud_cache_dir() -> str:
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "cache")


def _sd_mounts() -> list[str]:
    """Removable media mount points (SD card shows up under /run/media)."""
    mounts = []
    for pattern in ("/run/media/*/*", "/run/media/*"):
        for path in glob.glob(pattern):
            if os.path.ismount(path) and os.access(path, os.W_OK):
                mounts.append(path)
    seen = set()
    unique = []
    for m in mounts:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def _installed_plugins() -> list[dict]:
    """Name + version of every installed plugin, read from plugins/*/plugin.json."""
    plugins = []
    plugins_root = os.path.join(decky.DECKY_HOME, "plugins")
    if not os.path.isdir(plugins_root):
        return plugins
    for entry in sorted(os.listdir(plugins_root)):
        plugin_json = os.path.join(plugins_root, entry, "plugin.json")
        package_json = os.path.join(plugins_root, entry, "package.json")
        if not os.path.isfile(plugin_json):
            continue
        info = {"dir": entry, "name": entry, "version": None}
        try:
            with open(plugin_json, encoding="utf-8") as f:
                info["name"] = json.load(f).get("name", entry)
            if os.path.isfile(package_json):
                with open(package_json, encoding="utf-8") as f:
                    info["version"] = json.load(f).get("version")
        except (OSError, ValueError) as e:
            decky.logger.warning(f"Could not read metadata for plugin {entry}: {e}")
        plugins.append(info)
    return plugins


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _create_archive(dest_dir: str, components: list[str], progress) -> dict:
    """Build the tar.gz. Runs in an executor thread; `progress(stage)` reports back."""
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = os.path.join(dest_dir, f"{ARCHIVE_PREFIX}{stamp}.tar.gz")

    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "components": components,
        "plugins": _installed_plugins(),
        "deck_backup_version": VERSION,
    }

    def _exclude(tarinfo: tarfile.TarInfo):
        # Never archive our own backups (recursion) or our own runtime data.
        parts = tarinfo.name.split("/")
        if len(parts) >= 2 and parts[0] == "data" and parts[1] == OWN_DATA_DIRNAME:
            return None
        return tarinfo

    with tarfile.open(archive_path, "w:gz") as tar:
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest_bytes)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(manifest_bytes))

        for component in components:
            subdir = COMPONENT_DIRS.get(component)
            if subdir is None:
                continue
            src = os.path.join(decky.DECKY_HOME, subdir)
            if not os.path.isdir(src):
                decky.logger.info(f"Skipping missing component dir: {src}")
                continue
            progress(f"Archiving {component}…")
            tar.add(src, arcname=subdir, filter=_exclude)

    return {
        "path": archive_path,
        "size": os.path.getsize(archive_path),
        "manifest": manifest,
    }


def _normalize_member_name(name: str) -> str | None:
    normalized = os.path.normpath(name).replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith(".."):
        return None
    return normalized


def _plugin_key(parts: list[str]) -> str | None:
    """Per-plugin key of an archive member: settings/<key>(.json) or data/<key>."""
    if len(parts) < 2 or parts[0] not in ("settings", "data"):
        return None
    key = parts[1]
    if parts[0] == "settings" and len(parts) == 2 and key.endswith(".json"):
        key = key[: -len(".json")]
    return key


def _member_selected(name: str, selection: dict) -> bool:
    parts = name.split("/")
    root = parts[0]
    if selection.get("everything"):
        return root in COMPONENT_DIRS.values()
    if root == "themes":
        return bool(selection.get("themes"))
    key = _plugin_key(parts)
    return key is not None and key in set(selection.get("plugins", []))


def _safe_members(tar: tarfile.TarFile, selection: dict):
    """Yield only members that stay inside DECKY_HOME and match the selection."""
    for member in tar.getmembers():
        name = _normalize_member_name(member.name)
        if name is None:
            decky.logger.warning(f"Skipping unsafe archive member: {member.name}")
            continue
        if member.issym() or member.islnk():
            decky.logger.warning(f"Skipping link in archive: {member.name}")
            continue
        if _member_selected(name, selection):
            yield member


def _inspect_archive(archive_path: str) -> dict:
    """Per-plugin contents of a backup, for the selective-restore UI."""
    plugins = set()
    themes = set()
    manifest = {}
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            name = _normalize_member_name(member.name)
            if name is None or name == MANIFEST_NAME:
                continue
            parts = name.split("/")
            key = _plugin_key(parts)
            if key is not None:
                plugins.add(key)
            elif parts[0] == "themes" and len(parts) >= 2:
                themes.add(parts[1])
        try:
            manifest = json.load(tar.extractfile(MANIFEST_NAME))
        except (KeyError, ValueError, TypeError):
            manifest = {}
    return {"plugins": sorted(plugins), "themes": sorted(themes), "manifest": manifest}


def _restore_archive(archive_path: str, selection: dict, progress) -> dict:
    with tarfile.open(archive_path, "r:gz") as tar:
        try:
            manifest = json.load(tar.extractfile(MANIFEST_NAME))
        except (KeyError, ValueError, TypeError):
            manifest = {}
        progress("Restoring files…")
        tar.extractall(path=decky.DECKY_HOME, members=_safe_members(tar, selection))

    installed_dirs = {p["dir"] for p in _installed_plugins()}
    missing = [
        p for p in manifest.get("plugins", [])
        if p.get("dir") not in installed_dirs and p.get("dir") != OWN_DATA_DIRNAME
    ]
    return {"manifest": manifest, "missing_plugins": missing}


class Plugin:
    async def _emit_progress(self, stage: str):
        await decky.emit("backup_progress", stage)

    def _progress_cb(self):
        """Thread-safe progress reporter usable from executor threads."""
        def report(stage: str):
            asyncio.run_coroutine_threadsafe(self._emit_progress(stage), self.loop)
        return report

    def _ensure_local(self, path: str, progress) -> str:
        """Local filesystem path for a backup, downloading Drive backups to a cache."""
        if not path.startswith(GDRIVE_PREFIX):
            return path
        file_id = path[len(GDRIVE_PREFIX):]
        cached = os.path.join(_cloud_cache_dir(), f"{file_id}.tar.gz")
        if not os.path.isfile(cached):
            progress("Downloading from Google Drive…")
            gdrive.download(file_id, cached)
        return cached

    async def get_destinations(self) -> list[dict]:
        dests = [{"id": "internal", "label": "Internal storage", "path": _internal_backup_dir()}]
        for mount in _sd_mounts():
            dests.append({
                "id": mount,
                "label": f"SD card ({os.path.basename(mount)})",
                "path": os.path.join(mount, SD_BACKUP_DIRNAME),
            })
        if gdrive.is_connected():
            dests.append({"id": "gdrive", "label": "Google Drive", "path": "gdrive"})
        return dests

    async def get_size_estimate(self, components: list[str]) -> int:
        total = 0
        for component in components:
            subdir = COMPONENT_DIRS.get(component)
            if subdir:
                path = os.path.join(decky.DECKY_HOME, subdir)
                if os.path.isdir(path):
                    total += await self.loop.run_in_executor(None, _dir_size, path)
        return total

    async def create_backup(self, components: list[str], dest_path: str) -> dict:
        decky.logger.info(f"Creating backup of {components} -> {dest_path}")
        progress = self._progress_cb()
        to_gdrive = dest_path == "gdrive"
        try:
            result = await self.loop.run_in_executor(
                None, _create_archive,
                _internal_backup_dir() if to_gdrive else dest_path,
                components, progress,
            )
            if to_gdrive:
                progress("Uploading to Google Drive…")
                name = os.path.basename(result["path"])
                file_id = await self.loop.run_in_executor(
                    None, gdrive.upload, result["path"], name)
                os.remove(result["path"])
                result["path"] = f"{GDRIVE_PREFIX}{file_id}"
            decky.logger.info(f"Backup written: {result['path']} ({result['size']} bytes)")
            return {"success": True, **result}
        except Exception as e:
            decky.logger.exception("Backup failed")
            return {"success": False, "error": str(e)}

    async def list_backups(self) -> list[dict]:
        backups = []
        search_dirs = [_internal_backup_dir()] + [
            os.path.join(m, SD_BACKUP_DIRNAME) for m in _sd_mounts()
        ]
        for directory in search_dirs:
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                if not (name.startswith(ARCHIVE_PREFIX) and name.endswith(".tar.gz")):
                    continue
                path = os.path.join(directory, name)
                try:
                    stat = os.stat(path)
                    backups.append({
                        "path": path,
                        "name": name,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "location": "internal" if directory.startswith(
                            decky.DECKY_PLUGIN_RUNTIME_DIR) else "sd",
                    })
                except OSError:
                    continue
        if gdrive.is_connected():
            try:
                cloud = await self.loop.run_in_executor(
                    None, gdrive.list_backups, ARCHIVE_PREFIX)
                for entry in cloud:
                    backups.append({
                        "path": f"{GDRIVE_PREFIX}{entry['id']}",
                        "name": entry["name"],
                        "size": entry["size"],
                        "mtime": entry["mtime"],
                        "location": "gdrive",
                    })
            except Exception as e:
                decky.logger.warning(f"Could not list Google Drive backups: {e}")
        backups.sort(key=lambda b: b["mtime"], reverse=True)
        return backups

    async def inspect_backup(self, archive_path: str) -> dict:
        try:
            progress = self._progress_cb()
            local = await self.loop.run_in_executor(
                None, self._ensure_local, archive_path, progress)
            result = await self.loop.run_in_executor(None, _inspect_archive, local)
            return {"success": True, **result}
        except Exception as e:
            decky.logger.exception("Inspect failed")
            return {"success": False, "error": str(e)}

    async def restore_backup(self, archive_path: str, selection: dict) -> dict:
        decky.logger.info(f"Restoring from {archive_path} with selection {selection}")
        try:
            progress = self._progress_cb()
            local = await self.loop.run_in_executor(
                None, self._ensure_local, archive_path, progress)
            result = await self.loop.run_in_executor(
                None, _restore_archive, local, selection, progress)
            return {"success": True, **result}
        except Exception as e:
            decky.logger.exception("Restore failed")
            return {"success": False, "error": str(e)}

    async def delete_backup(self, archive_path: str) -> dict:
        try:
            if archive_path.startswith(GDRIVE_PREFIX):
                file_id = archive_path[len(GDRIVE_PREFIX):]
                await self.loop.run_in_executor(None, gdrive.delete, file_id)
                cached = os.path.join(_cloud_cache_dir(), f"{file_id}.tar.gz")
                if os.path.isfile(cached):
                    os.remove(cached)
                return {"success": True}
            # Only delete files that look like our own archives.
            name = os.path.basename(archive_path)
            if not (name.startswith(ARCHIVE_PREFIX) and name.endswith(".tar.gz")):
                return {"success": False, "error": "Not a Deck Backup archive"}
            os.remove(archive_path)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def gdrive_status(self) -> dict:
        return {"has_client": gdrive.has_client(), "connected": gdrive.is_connected()}

    async def gdrive_set_client(self, client_id: str, client_secret: str) -> dict:
        try:
            gdrive.set_client(client_id, client_secret)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def gdrive_auth_start(self) -> dict:
        try:
            result = await self.loop.run_in_executor(None, gdrive.auth_start)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def gdrive_auth_poll(self) -> dict:
        try:
            return await self.loop.run_in_executor(None, gdrive.auth_poll)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def gdrive_disconnect(self) -> dict:
        gdrive.disconnect()
        return {"success": True}

    async def _main(self):
        self.loop = asyncio.get_event_loop()
        os.makedirs(_internal_backup_dir(), exist_ok=True)
        # Drop stale cloud downloads from previous sessions.
        cache = _cloud_cache_dir()
        if os.path.isdir(cache):
            for name in os.listdir(cache):
                try:
                    os.remove(os.path.join(cache, name))
                except OSError:
                    pass
        decky.logger.info("Deck Backup loaded")

    async def _unload(self):
        decky.logger.info("Deck Backup unloaded")

    async def _uninstall(self):
        # Keep user backups on uninstall — they are the whole point.
        decky.logger.info("Deck Backup uninstalled (backups left in place)")
