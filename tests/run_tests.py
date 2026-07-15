"""Unit tests for the backup/restore/schedule logic, runnable anywhere.

The real `decky` module only exists on a Deck, so a stub is installed
before importing the plugin. Run with: python3 tests/run_tests.py
"""

import asyncio
import io
import json
import logging
import os
import sys
import tarfile
import tempfile
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# ---- decky stub (must exist before importing main/gdrive) ----
decky = types.ModuleType("decky")
TMP = tempfile.mkdtemp(prefix="deck-backup-test-")
decky.DECKY_USER_HOME = TMP
decky.DECKY_HOME = os.path.join(TMP, "homebrew")
decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(TMP, "homebrew", "data", "decky-backup")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(TMP, "homebrew", "settings", "decky-backup")
decky.logger = logging.getLogger("deck-backup-test")

EMITTED = []


async def _emit(name, *args):
    EMITTED.append((name, args))


decky.emit = _emit
sys.modules["decky"] = decky

import main  # noqa: E402
import gdrive  # noqa: E402


def make_archive(path: str):
    with tarfile.open(path, "w:gz") as tar:
        def addf(name, content=b"x"):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        manifest = json.dumps({
            "plugins": [{"dir": "PowerTools", "name": "PowerTools", "version": "1.5"}],
        }).encode()
        addf("manifest.json", manifest)
        addf("settings/PowerTools/config.json")
        addf("settings/legacy-plugin.json")
        addf("settings/CSS Loader/settings.json")
        addf("data/PowerTools/cache.bin")
        addf("themes/MyTheme/theme.css")
        addf("../../evil.txt")  # traversal attempt — must never extract


def extracted_files():
    return sorted(
        os.path.relpath(os.path.join(dp, f), decky.DECKY_HOME).replace("\\", "/")
        for dp, _dirs, files in os.walk(decky.DECKY_HOME)
        for f in files
    )


def reset_home():
    import shutil
    if os.path.isdir(decky.DECKY_HOME):
        shutil.rmtree(decky.DECKY_HOME)
    os.makedirs(decky.DECKY_HOME)


def test_inspect_and_selective_restore():
    reset_home()
    archive = os.path.join(TMP, "deckbackup-test.tar.gz")
    make_archive(archive)

    info = main._inspect_archive(archive)
    assert info["plugins"] == ["CSS Loader", "PowerTools", "legacy-plugin"], info["plugins"]
    assert info["themes"] == ["MyTheme"], info["themes"]
    assert info["manifest"]["plugins"][0]["dir"] == "PowerTools"

    # Selective restore: only PowerTools, no themes
    main._restore_archive(
        archive, {"everything": False, "themes": False, "plugins": ["PowerTools"]},
        lambda s: None)
    assert extracted_files() == [
        "data/PowerTools/cache.bin", "settings/PowerTools/config.json",
    ], extracted_files()
    assert not os.path.exists(os.path.join(TMP, "evil.txt")), "path traversal escaped!"

    # Full restore
    result = main._restore_archive(
        archive, {"everything": True, "themes": False, "plugins": []}, lambda s: None)
    files = extracted_files()
    assert "themes/MyTheme/theme.css" in files and "settings/legacy-plugin.json" in files
    assert not os.path.exists(os.path.join(TMP, "evil.txt"))
    # Missing-plugin diff: nothing installed locally, so PowerTools is missing
    assert result["missing_plugins"][0]["name"] == "PowerTools"


async def _schedule_tests():
    reset_home()
    EMITTED.clear()
    plugin = main.Plugin()
    plugin.loop = asyncio.get_event_loop()
    os.makedirs(os.path.join(decky.DECKY_HOME, "settings", "PowerTools"), exist_ok=True)
    with open(os.path.join(decky.DECKY_HOME, "settings", "PowerTools", "cfg.json"), "w") as f:
        f.write("{}")

    # Persistence round-trip; unknown keys rejected
    s = await plugin.set_schedule(
        {"enabled": True, "frequency": "weekly", "keep": 2, "bogus_key": 1})
    assert s["enabled"] and s["frequency"] == "weekly" and s["keep"] == 2
    assert "bogus_key" not in s
    assert (await plugin.get_schedule())["keep"] == 2

    # Auto backup writes an auto-tagged archive and emits an event
    await plugin._run_auto_backup(await plugin.get_schedule())
    backups = await plugin.list_backups()
    assert len(backups) == 1 and backups[0]["auto"], backups
    assert backups[0]["name"].startswith("deckbackup-auto-")
    assert EMITTED and EMITTED[-1][0] == "auto_backup" and EMITTED[-1][1][0]["success"]

    # Retention: 3 extra older auto backups, keep=2 -> prune 2
    dest = main._internal_backup_dir()
    for i in range(3):
        path = os.path.join(dest, f"deckbackup-auto-2026010{i + 1}-000000.tar.gz")
        with open(path, "wb") as f:
            f.write(b"x")
        os.utime(path, (1000 + i, 1000 + i))
    pruned = await plugin._prune_auto_backups(dest, 2)
    assert pruned == 2 and len(os.listdir(dest)) == 2, (pruned, os.listdir(dest))

    # Manual backups are never pruned
    manual = os.path.join(dest, "deckbackup-20260101-000000.tar.gz")
    with open(manual, "wb") as f:
        f.write(b"x")
    os.utime(manual, (500, 500))
    assert await plugin._prune_auto_backups(dest, 2) == 0
    assert os.path.exists(manual)

    # Destination fallback when Drive/SD unavailable
    _path, label, warn = plugin._resolve_schedule_dest("gdrive")
    assert label == "Internal storage" and warn == "Google Drive not connected"
    _path, label, warn = plugin._resolve_schedule_dest("/run/media/nope")
    assert label == "Internal storage" and warn == "SD card not mounted"


def test_schedule_and_pruning():
    asyncio.run(_schedule_tests())


def test_gdrive_client_precedence():
    saved = (gdrive.DEFAULT_CLIENT_ID, gdrive.DEFAULT_CLIENT_SECRET)
    try:
        # No bundled client, no user file -> error
        gdrive.DEFAULT_CLIENT_ID = gdrive.DEFAULT_CLIENT_SECRET = ""
        if os.path.isfile(gdrive.CLIENT_FILE):
            os.remove(gdrive.CLIENT_FILE)
        assert not gdrive.has_client()
        try:
            gdrive._client()
            raise AssertionError("expected GDriveError")
        except gdrive.GDriveError:
            pass

        # Bundled client kicks in
        gdrive.DEFAULT_CLIENT_ID = "bundled-id"
        gdrive.DEFAULT_CLIENT_SECRET = "bundled-secret"
        assert gdrive.has_client()
        assert gdrive._client()["client_id"] == "bundled-id"

        # User-supplied client takes precedence over bundled
        gdrive.set_client("user-id", "user-secret")
        assert gdrive._client()["client_id"] == "user-id"
    finally:
        gdrive.DEFAULT_CLIENT_ID, gdrive.DEFAULT_CLIENT_SECRET = saved
        if os.path.isfile(gdrive.CLIENT_FILE):
            os.remove(gdrive.CLIENT_FILE)

    # The shipped bundled client must be present in a release build
    assert gdrive.has_client(), "bundled DEFAULT_CLIENT_ID/SECRET missing"


TESTS = [
    test_inspect_and_selective_restore,
    test_schedule_and_pruning,
    test_gdrive_client_precedence,
]

if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"{test.__name__} OK")
    print(f"ALL {len(TESTS)} TESTS PASSED")
