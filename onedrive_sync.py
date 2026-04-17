"""OneDrive persistent storage for scout reports.

All finished reports (PPTX + JSON metadata) are stored on OneDrive, organised
per scout:

    <base_folder>/<scout_name>/<report_id>.pptx
    <base_folder>/<scout_name>/<report_id>.json

The local filesystem acts as a fast read-cache.  On app startup the local
cache is repopulated from OneDrive when it is empty (e.g. after a redeploy).

Uses the Microsoft Graph API with client-credentials (app-only) flow against
a specific user's OneDrive for Business.

Required secrets in st.secrets:

    [onedrive]
    tenant_id     = "aa736a64-..."
    client_id     = "e016dfcf-..."
    client_secret = "0D68Q~..."
    user_email    = "stage.it@fcdenbosch.nl"
    base_folder   = "ScoutTemplateProject"
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests
import streamlit as st


# ─── Auth ──────────────────────────────────────────────────────────────────

_token_cache: dict = {"access_token": "", "expires_at": 0.0}


def _get_config() -> dict | None:
    """Read OneDrive settings from Streamlit secrets."""
    try:
        cfg = st.secrets.get("onedrive", {})
    except Exception:
        return None
    if not cfg or not cfg.get("tenant_id"):
        return None
    return {
        "tenant_id": cfg["tenant_id"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "user_email": cfg["user_email"],
        "base_folder": cfg.get("base_folder", "ScoutTemplateProject"),
    }


def _get_token(cfg: dict) -> str:
    """Obtain (or reuse) an app-only access token via client credentials."""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    url = f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "scope": "https://graph.microsoft.com/.default",
    }
    resp = requests.post(url, data=data, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    _token_cache["access_token"] = body["access_token"]
    _token_cache["expires_at"] = now + body.get("expires_in", 3600)
    return _token_cache["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _drive_prefix(cfg: dict) -> str:
    """Graph URL prefix for the user's OneDrive."""
    email = cfg["user_email"]
    return f"https://graph.microsoft.com/v1.0/users/{email}/drive"


# ─── Helpers ───────────────────────────────────────────────────────────────

def _safe(name: str) -> str:
    """Remove characters illegal in OneDrive file/folder names."""
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "_"


def _folder_path(cfg: dict, scout: str) -> str:
    return f"{_safe(cfg['base_folder'])}/{_safe(scout)}"


# ─── Upload ────────────────────────────────────────────────────────────────

def upload_pptx(
    scout: str,
    report_id: str,
    pptx_bytes: bytes,
) -> tuple[bool, str | None]:
    """Upload a PPTX file.  Returns (ok, error)."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout)
    path = f"{folder}/{report_id}.pptx"
    url = f"{_drive_prefix(cfg)}/root:/{path}:/content"
    try:
        resp = requests.put(url, headers={
            **_auth_headers(token),
            "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }, data=pptx_bytes, timeout=60)
        resp.raise_for_status()
        return True, None
    except Exception as exc:
        return False, str(exc)


def upload_json(
    scout: str,
    report_id: str,
    meta: dict,
) -> tuple[bool, str | None]:
    """Upload a JSON metadata file.  Returns (ok, error)."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout)
    path = f"{folder}/{report_id}.json"
    url = f"{_drive_prefix(cfg)}/root:/{path}:/content"
    body = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        resp = requests.put(url, headers={
            **_auth_headers(token),
            "Content-Type": "application/json",
        }, data=body, timeout=30)
        resp.raise_for_status()
        return True, None
    except Exception as exc:
        return False, str(exc)


def upload_file(
    scout: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> tuple[bool, str | None]:
    """Upload an arbitrary file (photos, videos) into a scout's folder."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout)
    path = f"{folder}/{_safe(filename)}"
    url = f"{_drive_prefix(cfg)}/root:/{path}:/content"
    try:
        resp = requests.put(url, headers={
            **_auth_headers(token),
            "Content-Type": content_type,
        }, data=data, timeout=60)
        resp.raise_for_status()
        return True, None
    except Exception as exc:
        return False, str(exc)


# ─── Delete ────────────────────────────────────────────────────────────────

def delete_report_files(
    scout: str,
    report_id: str,
) -> tuple[bool, str | None]:
    """Delete all files for a report (pptx, json, photos, videos)."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout)
    # List all files in the scout's folder that start with report_id
    list_url = f"{_drive_prefix(cfg)}/root:/{folder}:/children"
    try:
        resp = requests.get(list_url, headers=_auth_headers(token), timeout=15)
        if resp.status_code == 404:
            return True, None  # folder gone already
        resp.raise_for_status()
        items = resp.json().get("value", [])
    except Exception as exc:
        return False, str(exc)

    errors = []
    for item in items:
        if item["name"].startswith(report_id):
            del_url = f"{_drive_prefix(cfg)}/items/{item['id']}"
            try:
                r = requests.delete(del_url, headers=_auth_headers(token), timeout=15)
                if r.status_code not in (204, 404):
                    r.raise_for_status()
            except Exception as exc:
                errors.append(str(exc))

    return (len(errors) == 0), ("; ".join(errors) if errors else None)


# ─── Download / List ───────────────────────────────────────────────────────

def list_scout_files(scout: str) -> list[dict] | None:
    """List files in a scout's folder.  Returns [{"name", "id", "size"}] or None."""
    cfg = _get_config()
    if not cfg:
        return None
    try:
        token = _get_token(cfg)
    except Exception:
        return None

    folder = _folder_path(cfg, scout)
    url = f"{_drive_prefix(cfg)}/root:/{folder}:/children"
    try:
        resp = requests.get(url, headers=_auth_headers(token), timeout=15)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [
            {"name": it["name"], "id": it["id"], "size": it.get("size", 0)}
            for it in resp.json().get("value", [])
        ]
    except Exception:
        return None


def download_file(scout: str, filename: str) -> bytes | None:
    """Download a single file from a scout's folder."""
    cfg = _get_config()
    if not cfg:
        return None
    try:
        token = _get_token(cfg)
    except Exception:
        return None

    folder = _folder_path(cfg, scout)
    path = f"{folder}/{_safe(filename)}"
    url = f"{_drive_prefix(cfg)}/root:/{path}:/content"
    try:
        resp = requests.get(url, headers=_auth_headers(token), timeout=60)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


# ─── Restore local cache from OneDrive ─────────────────────────────────────

def restore_scout_to_local(scout: str, local_finished_dir: Path) -> int:
    """Download all files for a scout from OneDrive into local finished dir.

    Returns number of reports restored.
    """
    files = list_scout_files(scout)
    if not files:
        return 0

    local_finished_dir.mkdir(parents=True, exist_ok=True)
    report_ids: set[str] = set()

    for f in files:
        name = f["name"]
        # Extract report_id from filenames like "abc123def456.pptx"
        stem = name.rsplit(".", 1)[0] if "." in name else name
        # Remove suffixes like "_photo_full", "_video_0" etc.
        base_id = stem.split("_")[0] if "_" in stem else stem
        if len(base_id) == 12 and base_id.isalnum():
            report_ids.add(base_id)

        local_path = local_finished_dir / name
        if not local_path.exists():
            data = download_file(scout, name)
            if data:
                local_path.write_bytes(data)

    return len({rid for rid in report_ids
                if (local_finished_dir / f"{rid}.json").exists()})


def restore_all_scouts(data_dir: Path) -> dict[str, int]:
    """Scan OneDrive base folder for all scout sub-folders and restore them.

    Returns {scout_name: num_reports_restored}.
    """
    cfg = _get_config()
    if not cfg:
        return {}
    try:
        token = _get_token(cfg)
    except Exception:
        return {}

    # List sub-folders under the base folder
    base = _safe(cfg["base_folder"])
    url = f"{_drive_prefix(cfg)}/root:/{base}:/children"
    try:
        resp = requests.get(url, headers=_auth_headers(token), timeout=15)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        items = resp.json().get("value", [])
    except Exception:
        return {}

    results = {}
    for item in items:
        if item.get("folder"):  # is a folder
            scout_name = item["name"]
            finished_dir = data_dir / scout_name / "finished"
            count = restore_scout_to_local(scout_name, finished_dir)
            if count > 0:
                results[scout_name] = count

    return results


# ─── Public helpers ────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Quick check whether OneDrive secrets are present."""
    return _get_config() is not None
