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


def _folder_path(cfg: dict, scout: str, subfolder: str = "") -> str:
    base = f"{_safe(cfg['base_folder'])}/{_safe(scout)}"
    return f"{base}/{_safe(subfolder)}" if subfolder else base


# ─── Folder creation ──────────────────────────────────────────────────────

def _create_folder_raw(cfg: dict, token: str, parent_path: str, name: str) -> tuple[bool, str | None]:
    """Create a single folder named `name` under `parent_path` (relative to drive root).

    If `parent_path` is empty, creates at drive root. Uses Graph's conflict
    resolution 'replace' so existing folders are kept (no error).
    """
    safe_name = _safe(name)
    if parent_path:
        url = f"{_drive_prefix(cfg)}/root:/{parent_path}:/children"
    else:
        url = f"{_drive_prefix(cfg)}/root/children"
    body = {
        "name": safe_name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "replace",
    }
    try:
        resp = requests.post(
            url,
            headers={**_auth_headers(token), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        # 201 = created, 200 = replaced/exists
        if resp.status_code in (200, 201):
            return True, None
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return False, str(exc)


def create_folder_tree(
    scout: str,
    main_folder: str,
    subfolders: list[str],
    base_subfolder: str = "Videos",
) -> tuple[bool, str | None, list[str]]:
    """Create <scout>/<base_subfolder>/<main_folder>/<sub>/ on the configured OneDrive.

    Returns (ok, error, created_paths).
    Idempotent: existing folders are reused.
    """
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured", []
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}", []

    # Build up the parent tree: base_folder / scout / base_subfolder / main_folder
    parts = [_safe(cfg["base_folder"]), _safe(scout)]
    if base_subfolder:
        parts.append(_safe(base_subfolder))
    parts.append(_safe(main_folder))

    # Walk the path, creating each segment under its parent.
    current = ""
    for seg in parts:
        ok, err = _create_folder_raw(cfg, token, current, seg)
        if not ok:
            return False, f"Failed creating '{current}/{seg}': {err}", []
        current = f"{current}/{seg}" if current else seg

    main_path = current
    created: list[str] = [main_path]
    for sub in subfolders:
        ok, err = _create_folder_raw(cfg, token, main_path, sub)
        if not ok:
            return False, f"Failed creating subfolder '{sub}': {err}", created
        created.append(f"{main_path}/{_safe(sub)}")

    return True, None, created


# ─── Upload ────────────────────────────────────────────────────────────────

def upload_pptx(
    scout: str,
    report_id: str,
    pptx_bytes: bytes,
    subfolder: str = "",
) -> tuple[bool, str | None]:
    """Upload a PPTX file.  Returns (ok, error)."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout, subfolder)
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
    subfolder: str = "",
) -> tuple[bool, str | None]:
    """Upload a JSON metadata file.  Returns (ok, error)."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout, subfolder)
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
    subfolder: str = "",
) -> tuple[bool, str | None]:
    """Upload an arbitrary file (photos, videos) into a scout's folder."""
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    folder = _folder_path(cfg, scout, subfolder)
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
    subfolder: str = "",
) -> tuple[bool, str | None]:
    """Delete all files for a report (pptx, json, photos, videos).

    If subfolder is empty, deletes from both the finished area and the
    drafts/ subfolder so a single report_id is fully purged.
    """
    cfg = _get_config()
    if not cfg:
        return False, "OneDrive not configured"
    try:
        token = _get_token(cfg)
    except Exception as exc:
        return False, f"Auth error: {exc}"

    targets = [subfolder] if subfolder else ["", "drafts"]
    errors: list[str] = []

    for sub in targets:
        folder = _folder_path(cfg, scout, sub)
        list_url = f"{_drive_prefix(cfg)}/root:/{folder}:/children"
        try:
            resp = requests.get(list_url, headers=_auth_headers(token), timeout=15)
            if resp.status_code == 404:
                continue  # folder doesn't exist, nothing to delete
            resp.raise_for_status()
            items = resp.json().get("value", [])
        except Exception as exc:
            errors.append(str(exc))
            continue

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

def restore_scout_to_local(scout: str, data_dir: Path) -> tuple[int, int]:
    """Restore a scout's OneDrive files to local cache.

    Each JSON on OneDrive is either:
      - a finished report (written to data/<scout>/finished/)
      - a share reference (is_share_ref=True) — written to data/<scout>/received/
        and the pointed-to PPTX/photos/videos are fetched from the original
        scout's folder and mirrored locally under the share_id filename.

    Returns (finished_count, received_count).
    """
    files = list_scout_files(scout)
    if not files:
        return (0, 0)

    finished_dir = data_dir / scout / "finished"
    received_dir = data_dir / scout / "received"
    finished_dir.mkdir(parents=True, exist_ok=True)
    received_dir.mkdir(parents=True, exist_ok=True)

    share_refs: list[tuple[str, dict]] = []
    finished_ids: set[str] = set()

    # Pass 1 — classify JSONs
    for f in files:
        name = f["name"]
        if not name.endswith(".json"):
            continue
        data = download_file(scout, name)
        if not data:
            continue
        try:
            meta = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        stem = name.rsplit(".", 1)[0]
        if meta.get("is_share_ref"):
            share_refs.append((stem, meta))
            (received_dir / name).write_bytes(data)
        else:
            finished_ids.add(stem)
            (finished_dir / name).write_bytes(data)

    # Pass 2 — download finished PPTX + photos + videos
    for f in files:
        name = f["name"]
        if name.endswith(".json"):
            continue
        stem_base = name.split("_")[0] if "_" in name else name.rsplit(".", 1)[0]
        if stem_base in finished_ids:
            local_path = finished_dir / name
            if not local_path.exists():
                d = download_file(scout, name)
                if d:
                    local_path.write_bytes(d)

    # Pass 3 — resolve share refs: fetch original PPTX/photos/videos
    for share_id, meta in share_refs:
        original_scout = meta.get("original_scout") or meta.get("shared_by")
        original_id = meta.get("original_id")
        if not original_scout or not original_id:
            continue
        orig_files = list_scout_files(original_scout) or []
        for of in orig_files:
            oname = of["name"]
            if not oname.startswith(original_id):
                continue
            # Skip the original JSON — the share ref JSON is authoritative
            if oname == f"{original_id}.json":
                continue
            new_name = oname.replace(original_id, share_id, 1)
            local_path = received_dir / new_name
            if not local_path.exists():
                d = download_file(original_scout, oname)
                if d:
                    local_path.write_bytes(d)

    return (len(finished_ids), len(share_refs))


def restore_all_scouts(data_dir: Path) -> dict[str, tuple[int, int]]:
    """Scan OneDrive base folder for all scout sub-folders and restore them.

    Returns {scout_name: (finished_count, received_count)}.
    """
    cfg = _get_config()
    if not cfg:
        return {}
    try:
        _get_token(cfg)
    except Exception:
        return {}

    base = _safe(cfg["base_folder"])
    url = f"{_drive_prefix(cfg)}/root:/{base}:/children"
    try:
        resp = requests.get(url, headers=_auth_headers(_get_token(cfg)), timeout=15)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        items = resp.json().get("value", [])
    except Exception:
        return {}

    results: dict[str, tuple[int, int]] = {}
    for item in items:
        if item.get("folder"):
            scout_name = item["name"]
            fin, rec = restore_scout_to_local(scout_name, data_dir)
            if fin or rec:
                results[scout_name] = (fin, rec)

    return results


# ─── Public helpers ────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Quick check whether OneDrive secrets are present."""
    return _get_config() is not None
