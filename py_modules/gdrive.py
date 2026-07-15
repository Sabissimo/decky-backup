"""Minimal Google Drive client: OAuth 2.0 device flow + Drive v3 REST, stdlib only.

Uses the `drive.file` scope, so the plugin can only see files it created.
The OAuth client (id/secret) is user-supplied — created once in Google Cloud
Console as a "TVs and Limited Input devices" client — and stored alongside
the token in the plugin settings dir.
"""

import calendar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import decky

SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_NAME = "Deck Backup"
FOLDER_MIME = "application/vnd.google-apps.folder"

CLIENT_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "gdrive_client.json")
TOKEN_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "gdrive_token.json")

# Shared OAuth client bundled with releases so users can skip the Cloud
# Console setup. For device-flow ("limited input") clients Google does not
# treat the secret as confidential — shipping it in source is standard
# practice (rclone does the same). Empty strings disable the bundled client;
# a user-supplied client in CLIENT_FILE always takes precedence.
DEFAULT_CLIENT_ID = ""
DEFAULT_CLIENT_SECRET = ""

_pending_device_code = None
_folder_id_cache = None


class GDriveError(RuntimeError):
    pass


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.chmod(path, 0o600)


def _post_form(url, fields, timeout=30):
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # OAuth endpoints return structured errors as JSON bodies.
        try:
            return json.load(e)
        except ValueError:
            raise GDriveError(f"HTTP {e.code} from {url}") from e


def has_client() -> bool:
    client = _read_json(CLIENT_FILE)
    if client and client.get("client_id") and client.get("client_secret"):
        return True
    return bool(DEFAULT_CLIENT_ID and DEFAULT_CLIENT_SECRET)


def set_client(client_id: str, client_secret: str):
    _write_json(CLIENT_FILE, {"client_id": client_id, "client_secret": client_secret})


def is_connected() -> bool:
    token = _read_json(TOKEN_FILE)
    return bool(token and token.get("refresh_token"))


def disconnect():
    global _folder_id_cache
    _folder_id_cache = None
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass


def _client() -> dict:
    client = _read_json(CLIENT_FILE)
    if client and client.get("client_id") and client.get("client_secret"):
        return client
    if DEFAULT_CLIENT_ID and DEFAULT_CLIENT_SECRET:
        return {"client_id": DEFAULT_CLIENT_ID, "client_secret": DEFAULT_CLIENT_SECRET}
    raise GDriveError("No Google OAuth client configured")


def auth_start() -> dict:
    global _pending_device_code
    client = _client()
    resp = _post_form(DEVICE_CODE_URL, {"client_id": client["client_id"], "scope": SCOPE})
    if "device_code" not in resp:
        raise GDriveError(resp.get("error_description") or resp.get("error") or "Device auth failed")
    _pending_device_code = resp["device_code"]
    return {
        "user_code": resp["user_code"],
        "verification_url": resp.get("verification_url") or resp.get("verification_uri"),
        "interval": resp.get("interval", 5),
        "expires_in": resp.get("expires_in", 1800),
    }


def auth_poll() -> dict:
    global _pending_device_code
    if not _pending_device_code:
        return {"status": "error", "error": "No authorization in progress"}
    client = _client()
    resp = _post_form(TOKEN_URL, {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "device_code": _pending_device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    })
    error = resp.get("error")
    if error in ("authorization_pending", "slow_down"):
        return {"status": "pending"}
    if error:
        _pending_device_code = None
        return {"status": "error", "error": resp.get("error_description") or error}
    resp["expires_at"] = time.time() + resp.get("expires_in", 3600) - 60
    _write_json(TOKEN_FILE, resp)
    _pending_device_code = None
    return {"status": "connected"}


def _access_token() -> str:
    token = _read_json(TOKEN_FILE)
    if not token:
        raise GDriveError("Google Drive is not connected")
    if time.time() < token.get("expires_at", 0):
        return token["access_token"]
    client = _client()
    resp = _post_form(TOKEN_URL, {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type": "refresh_token",
    })
    if "access_token" not in resp:
        raise GDriveError("Google Drive session expired — please reconnect")
    token.update(resp)
    token["expires_at"] = time.time() + resp.get("expires_in", 3600) - 60
    _write_json(TOKEN_FILE, token)
    return token["access_token"]


def _api(method, url, *, params=None, body=None, timeout=60):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", f"Bearer {_access_token()}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except ValueError:
            pass
        raise GDriveError(f"Google Drive error {e.code}: {detail or e.reason}") from e


def _folder_id() -> str:
    global _folder_id_cache
    if _folder_id_cache:
        return _folder_id_cache
    q = f"name = '{FOLDER_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    found = _api("GET", f"{API}/files", params={"q": q, "fields": "files(id)"})
    files = found.get("files", [])
    if files:
        _folder_id_cache = files[0]["id"]
    else:
        created = _api("POST", f"{API}/files", body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME})
        _folder_id_cache = created["id"]
    return _folder_id_cache


def upload(local_path: str, name: str) -> str:
    """Resumable upload in a single PUT; returns the Drive file id."""
    size = os.path.getsize(local_path)
    metadata = {"name": name, "parents": [_folder_id()]}
    req = urllib.request.Request(
        f"{UPLOAD_API}?uploadType=resumable", data=json.dumps(metadata).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {_access_token()}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Upload-Content-Type", "application/gzip")
    req.add_header("X-Upload-Content-Length", str(size))
    with urllib.request.urlopen(req, timeout=60) as resp:
        session_url = resp.headers["Location"]
    with open(local_path, "rb") as f:
        put = urllib.request.Request(session_url, data=f, method="PUT")
        put.add_header("Content-Length", str(size))
        put.add_header("Content-Type", "application/gzip")
        with urllib.request.urlopen(put, timeout=600) as resp:
            return json.load(resp)["id"]


def list_backups(prefix: str) -> list:
    q = f"'{_folder_id()}' in parents and trashed = false and name contains '{prefix}'"
    resp = _api("GET", f"{API}/files", params={
        "q": q, "fields": "files(id,name,size,modifiedTime)", "pageSize": 100})
    backups = []
    for f in resp.get("files", []):
        backups.append({
            "id": f["id"],
            "name": f["name"],
            "size": int(f.get("size", 0)),
            "mtime": calendar.timegm(time.strptime(f["modifiedTime"][:19], "%Y-%m-%dT%H:%M:%S")),
        })
    return backups


def download(file_id: str, dest_path: str):
    req = urllib.request.Request(f"{API}/files/{urllib.parse.quote(file_id)}?alt=media")
    req.add_header("Authorization", f"Bearer {_access_token()}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = dest_path + ".part"
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp, dest_path)


def delete(file_id: str):
    _api("DELETE", f"{API}/files/{urllib.parse.quote(file_id)}")
