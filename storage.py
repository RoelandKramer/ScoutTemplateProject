"""Persistent storage for scout report drafts and finished reports.

Uses the GitHub Contents API when credentials are configured (for Streamlit Cloud),
falls back to local filesystem for local development.

GitHub structure (inside the configured repo/branch):
  data/{username}/drafts/{report_id}.json
  data/{username}/finished/{report_id}.pptx
  data/{username}/finished/{report_id}.json
  ...

IMPORTANT: Use a **separate** GitHub repo for data (e.g. ScoutData) so that
commits don't trigger Streamlit Cloud redeployment of the app repo.
"""

import base64
import json
import time
import uuid
from pathlib import Path

import requests as _requests  # already in requirements

# ─── Storage backend ────────────────────────────────────────────────────────

_backend = None          # "github" | "local"
_gh_token = None
_gh_repo = None          # "owner/repo"
_gh_branch = "main"
_gh_prefix = "data"      # root folder inside the repo
DATA_DIR = Path(__file__).parent / "data"

# Upper size limit for GitHub uploads (100 MB via Contents API;
# we stay at 80 MB to leave room for base64 overhead).
_GH_MAX_BYTES = 80_000_000


def _init_backend():
    """Lazy-initialise: GitHub if credentials exist, else local filesystem."""
    global _backend, _gh_token, _gh_repo, _gh_branch, _gh_prefix
    if _backend is not None:
        return
    try:
        import streamlit as st
        cfg = st.secrets["github_storage"]
        _gh_token = cfg["token"]
        _gh_repo = cfg["repo"]
        if not _gh_token or not _gh_repo:
            raise ValueError("GitHub credentials not configured")
        _gh_branch = cfg.get("branch", "main")
        _gh_prefix = cfg.get("path_prefix", "data")
        _backend = "github"
    except Exception:
        _backend = "local"


# ─── GitHub helpers ─────────────────────────────────────────────────────────

def _gh_headers():
    return {
        "Authorization": f"Bearer {_gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_path(username: str, subfolder: str, filename: str) -> str:
    return f"{_gh_prefix}/{username}/{subfolder}/{filename}"


def _gh_get_file_meta(path: str) -> dict | None:
    """GET file metadata (sha, download_url, content). Returns None on 404."""
    r = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        params={"ref": _gh_branch},
    )
    return r.json() if r.status_code == 200 else None


def _gh_read(path: str) -> bytes | None:
    """Download file bytes from GitHub."""
    meta = _gh_get_file_meta(path)
    if meta is None:
        return None
    # Files ≤ 1 MB have base64 content inline
    if meta.get("content"):
        return base64.b64decode(meta["content"])
    # Larger files: follow the download URL
    if meta.get("download_url"):
        dl = _requests.get(meta["download_url"], headers=_gh_headers())
        if dl.status_code == 200:
            return dl.content
    return None


def _gh_write(path: str, data: bytes, message: str = "auto-save") -> bool:
    """Create or update a file in the repo. Returns True on success."""
    if len(data) > _GH_MAX_BYTES:
        return False  # skip files too large for Contents API
    # Need the current SHA if the file already exists (for update)
    meta = _gh_get_file_meta(path)
    body: dict = {
        "message": message,
        "content": base64.b64encode(data).decode("ascii"),
        "branch": _gh_branch,
    }
    if meta and meta.get("sha"):
        body["sha"] = meta["sha"]
    r = _requests.put(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        json=body,
    )
    return r.status_code in (200, 201)


def _gh_delete_file(path: str, message: str = "auto-delete") -> bool:
    """Delete a single file from the repo."""
    meta = _gh_get_file_meta(path)
    if not meta or not meta.get("sha"):
        return False
    r = _requests.delete(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        json={"message": message, "sha": meta["sha"], "branch": _gh_branch},
    )
    return r.status_code == 200


def _gh_list_dir(dirpath: str) -> list[str]:
    """List file names in a GitHub directory. Returns [] on 404."""
    r = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}/contents/{dirpath}",
        headers=_gh_headers(),
        params={"ref": _gh_branch},
    )
    if r.status_code != 200:
        return []
    items = r.json()
    if not isinstance(items, list):
        return []
    return [f["name"] for f in items if f.get("type") == "file"]


# ─── Unified low-level helpers ──────────────────────────────────────────────

def _write_bytes(username: str, subfolder: str, filename: str, data: bytes) -> None:
    _init_backend()
    if _backend == "github":
        path = _gh_path(username, subfolder, filename)
        _gh_write(path, data, message=f"Save {username}/{subfolder}/{filename}")
    else:
        d = DATA_DIR / username / subfolder
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_bytes(data)


def _write_text(username: str, subfolder: str, filename: str, text: str) -> None:
    _write_bytes(username, subfolder, filename, text.encode("utf-8"))


def _read_bytes(username: str, subfolder: str, filename: str) -> bytes | None:
    _init_backend()
    if _backend == "github":
        return _gh_read(_gh_path(username, subfolder, filename))
    else:
        p = DATA_DIR / username / subfolder / filename
        return p.read_bytes() if p.exists() else None


def _read_text(username: str, subfolder: str, filename: str) -> str | None:
    data = _read_bytes(username, subfolder, filename)
    return data.decode("utf-8") if data else None


def _list_filenames(username: str, subfolder: str) -> list[str]:
    """Return all filenames in a user's subfolder."""
    _init_backend()
    if _backend == "github":
        return _gh_list_dir(f"{_gh_prefix}/{username}/{subfolder}")
    else:
        d = DATA_DIR / username / subfolder
        if not d.exists():
            return []
        return [f.name for f in d.iterdir() if f.is_file()]


def _delete_prefix(username: str, subfolder: str, prefix: str) -> None:
    """Delete all files whose name starts with *prefix*."""
    _init_backend()
    if _backend == "github":
        dirpath = f"{_gh_prefix}/{username}/{subfolder}"
        names = _gh_list_dir(dirpath)
        for n in names:
            if n.startswith(prefix):
                try:
                    _gh_delete_file(f"{dirpath}/{n}",
                                    message=f"Delete {username}/{subfolder}/{n}")
                except Exception:
                    pass
    else:
        d = DATA_DIR / username / subfolder
        if d.exists():
            for f in d.glob(f"{prefix}*"):
                f.unlink(missing_ok=True)


# ─── Draft operations ────────────────────────────────────────────────────────

def save_draft(
    username: str,
    report_id: str | None,
    position: str,
    club: str,
    language: str,
    star_values: list[float],
    comments: list[str],
    video_data: list,       # list of (bytes, filename) or None
    source: str = "empty",  # "empty" or "upload"
    upload_bytes: bytes | None = None,
    upload_filename: str | None = None,
    player_data: dict | None = None,
    tm_stats: dict | None = None,
    photo_full: bytes | None = None,
    photo_circular: bytes | None = None,
) -> str:
    """Save or update a draft. Returns the report_id."""
    if not report_id:
        report_id = uuid.uuid4().hex[:12]

    sub = "drafts"

    # Save video files separately
    video_refs = []
    for i, vd in enumerate(video_data):
        if vd is not None:
            vbytes, vname = vd
            ext = vname.rsplit(".", 1)[-1] if "." in vname else "mp4"
            fname = f"{report_id}_video_{i}.{ext}"
            _write_bytes(username, sub, fname, vbytes)
            video_refs.append({"filename": vname, "path": fname})
        else:
            video_refs.append(None)

    # Save upload bytes if present
    upload_ref = None
    if upload_bytes:
        ufname = f"{report_id}_upload.pptx"
        _write_bytes(username, sub, ufname, upload_bytes)
        upload_ref = {"filename": upload_filename or "upload.pptx", "path": ufname}

    # Save player photos if present
    photo_refs = {}
    if photo_full:
        pfname = f"{report_id}_photo_full.png"
        _write_bytes(username, sub, pfname, photo_full)
        photo_refs["full"] = pfname
    if photo_circular:
        pcfname = f"{report_id}_photo_circ.png"
        _write_bytes(username, sub, pcfname, photo_circular)
        photo_refs["circular"] = pcfname

    # Load existing meta for created_at timestamp
    existing = _load_draft_meta(username, report_id)

    meta = {
        "report_id": report_id,
        "position": position,
        "club": club,
        "language": language,
        "star_values": star_values,
        "comments": comments,
        "video_refs": video_refs,
        "source": source,
        "upload_ref": upload_ref,
        "player_data": player_data,
        "tm_stats": tm_stats,
        "photo_refs": photo_refs if photo_refs else None,
        "updated_at": time.time(),
        "created_at": existing.get("created_at", time.time()),
    }

    _write_text(username, sub, f"{report_id}.json",
                json.dumps(meta, ensure_ascii=False, indent=2))
    return report_id


def _load_draft_meta(username: str, report_id: str) -> dict:
    text = _read_text(username, "drafts", f"{report_id}.json")
    if text:
        try:
            return json.loads(text)
        except Exception:
            pass
    return {}


def load_draft(username: str, report_id: str) -> dict | None:
    """Load a draft including video bytes. Returns None if not found."""
    meta = _load_draft_meta(username, report_id)
    if not meta:
        return None

    sub = "drafts"

    # Resolve video refs to actual bytes
    video_data = []
    for vref in meta.get("video_refs", []):
        if vref is not None:
            vbytes = _read_bytes(username, sub, vref["path"])
            if vbytes:
                video_data.append((vbytes, vref["filename"]))
            else:
                video_data.append(None)
        else:
            video_data.append(None)
    meta["video_data"] = video_data

    # Resolve upload ref
    uref = meta.get("upload_ref")
    if uref:
        ubytes = _read_bytes(username, sub, uref["path"])
        if ubytes:
            meta["upload_bytes"] = ubytes
            meta["upload_filename"] = uref["filename"]

    # Resolve photo refs
    prefs = meta.get("photo_refs") or {}
    if prefs.get("full"):
        pfull = _read_bytes(username, sub, prefs["full"])
        if pfull:
            meta["photo_full"] = pfull
    if prefs.get("circular"):
        pcirc = _read_bytes(username, sub, prefs["circular"])
        if pcirc:
            meta["photo_circular"] = pcirc

    return meta


def list_drafts(username: str) -> list[dict]:
    """Return all drafts for a user, sorted by most recently updated."""
    filenames = _list_filenames(username, "drafts")
    results = []
    for fname in filenames:
        if fname.endswith(".json") and "_" not in fname.replace(".json", ""):
            text = _read_text(username, "drafts", fname)
            if text:
                try:
                    results.append(json.loads(text))
                except Exception:
                    pass
    results.sort(key=lambda m: m.get("updated_at", 0), reverse=True)
    return results


def delete_draft(username: str, report_id: str) -> None:
    """Delete a draft and all its associated files."""
    _delete_prefix(username, "drafts", report_id)


# ─── Finished report operations ──────────────────────────────────────────────

def save_finished(
    username: str,
    report_id: str,
    position: str,
    club: str,
    language: str,
    pptx_bytes: bytes,
    player_name: str = "",
    player_data: dict | None = None,
    star_values: list[float] | None = None,
    comments: list[str] | None = None,
    video_data: list | None = None,
    tm_stats: dict | None = None,
    photo_full: bytes | None = None,
    photo_circular: bytes | None = None,
) -> str:
    """Save a finished PPTX + metadata. Returns the report_id."""
    sub = "finished"

    _write_bytes(username, sub, f"{report_id}.pptx", pptx_bytes)

    # Save photos
    photo_refs = {}
    if photo_full:
        pfname = f"{report_id}_photo_full.png"
        _write_bytes(username, sub, pfname, photo_full)
        photo_refs["full"] = pfname
    if photo_circular:
        pcfname = f"{report_id}_photo_circ.png"
        _write_bytes(username, sub, pcfname, photo_circular)
        photo_refs["circular"] = pcfname

    # Save video files separately
    video_refs = []
    if video_data:
        for i, vd in enumerate(video_data):
            if vd is not None:
                vbytes, vname = vd
                ext = vname.rsplit(".", 1)[-1] if "." in vname else "mp4"
                vfname = f"{report_id}_video_{i}.{ext}"
                _write_bytes(username, sub, vfname, vbytes)
                video_refs.append({"filename": vname, "path": vfname})
            else:
                video_refs.append(None)

    meta = {
        "report_id": report_id,
        "position": position,
        "club": club,
        "language": language,
        "player_name": player_name,
        "finished_at": time.time(),
        "player_data": player_data,
        "star_values": star_values or [],
        "comments": comments or [],
        "video_refs": video_refs,
        "tm_stats": tm_stats,
        "photo_refs": photo_refs if photo_refs else None,
    }
    _write_text(username, sub, f"{report_id}.json",
                json.dumps(meta, ensure_ascii=False, indent=2))

    # Clean up the draft if it exists
    delete_draft(username, report_id)

    return report_id


def list_finished(username: str) -> list[dict]:
    """Return all finished reports, sorted by most recently finished."""
    filenames = _list_filenames(username, "finished")
    results = []
    for fname in filenames:
        if fname.endswith(".json"):
            text = _read_text(username, "finished", fname)
            if text:
                try:
                    results.append(json.loads(text))
                except Exception:
                    pass
    results.sort(key=lambda m: m.get("finished_at", 0), reverse=True)
    return results


def load_finished_pptx(username: str, report_id: str) -> bytes | None:
    """Return the PPTX bytes for a finished report."""
    return _read_bytes(username, "finished", f"{report_id}.pptx")


def load_finished(username: str, report_id: str) -> dict | None:
    """Load a finished report's full state including PPTX, videos, photos."""
    text = _read_text(username, "finished", f"{report_id}.json")
    if not text:
        return None
    meta = json.loads(text)
    sub = "finished"

    # Attach PPTX bytes
    pptx = _read_bytes(username, sub, f"{report_id}.pptx")
    if pptx:
        meta["pptx_bytes"] = pptx

    # Resolve video refs to bytes
    video_data = []
    for vref in meta.get("video_refs", []) or []:
        if vref is not None:
            vbytes = _read_bytes(username, sub, vref["path"])
            if vbytes:
                video_data.append((vbytes, vref["filename"]))
            else:
                video_data.append(None)
        else:
            video_data.append(None)
    meta["video_data"] = video_data

    # Resolve photo refs
    prefs = meta.get("photo_refs") or {}
    if prefs.get("full"):
        pfull = _read_bytes(username, sub, prefs["full"])
        if pfull:
            meta["photo_full"] = pfull
    if prefs.get("circular"):
        pcirc = _read_bytes(username, sub, prefs["circular"])
        if pcirc:
            meta["photo_circular"] = pcirc

    return meta


def mark_shared(username: str, report_id: str, shared_to: str) -> None:
    """Mark a finished report as shared to another user."""
    text = _read_text(username, "finished", f"{report_id}.json")
    if not text:
        return
    meta = json.loads(text)
    shared_list = meta.get("shared_to", [])
    if shared_to not in shared_list:
        shared_list.append(shared_to)
    meta["shared_to"] = shared_list
    meta["shared_at"] = time.time()
    _write_text(username, "finished", f"{report_id}.json",
                json.dumps(meta, ensure_ascii=False, indent=2))


def delete_finished(username: str, report_id: str) -> None:
    _delete_prefix(username, "finished", report_id)


# ─── Received (shared) report operations ────────────────────────────────────

def share_report(
    from_username: str,
    to_username: str,
    report_id: str,
    position: str,
    club: str,
    language: str,
    pptx_bytes: bytes,
    player_name: str = "",
    star_values: list[float] | None = None,
    comments: list[str] | None = None,
    video_data: list | None = None,
    player_data: dict | None = None,
    tm_stats: dict | None = None,
    photo_full: bytes | None = None,
    photo_circular: bytes | None = None,
) -> str:
    """Copy a finished report into the recipient's received folder."""
    sub = "received"
    share_id = uuid.uuid4().hex[:12]

    _write_bytes(to_username, sub, f"{share_id}.pptx", pptx_bytes)

    # Save video files
    video_refs = []
    if video_data:
        for i, vd in enumerate(video_data):
            if vd is not None:
                vbytes, vname = vd
                ext = vname.rsplit(".", 1)[-1] if "." in vname else "mp4"
                vfname = f"{share_id}_video_{i}.{ext}"
                _write_bytes(to_username, sub, vfname, vbytes)
                video_refs.append({"filename": vname, "path": vfname})
            else:
                video_refs.append(None)

    # Save player photos
    photo_refs = {}
    if photo_full:
        pfname = f"{share_id}_photo_full.png"
        _write_bytes(to_username, sub, pfname, photo_full)
        photo_refs["full"] = pfname
    if photo_circular:
        pcfname = f"{share_id}_photo_circ.png"
        _write_bytes(to_username, sub, pcfname, photo_circular)
        photo_refs["circular"] = pcfname

    meta = {
        "report_id": share_id,
        "original_id": report_id,
        "position": position,
        "club": club,
        "language": language,
        "player_name": player_name,
        "shared_by": from_username,
        "shared_at": time.time(),
        "star_values": star_values or [],
        "comments": comments or [],
        "video_refs": video_refs,
        "player_data": player_data,
        "tm_stats": tm_stats,
        "photo_refs": photo_refs if photo_refs else None,
    }
    _write_text(to_username, sub, f"{share_id}.json",
                json.dumps(meta, ensure_ascii=False, indent=2))
    return share_id


def list_received(username: str) -> list[dict]:
    """Return all received reports, sorted by most recently shared."""
    filenames = _list_filenames(username, "received")
    results = []
    for fname in filenames:
        if fname.endswith(".json"):
            text = _read_text(username, "received", fname)
            if text:
                try:
                    results.append(json.loads(text))
                except Exception:
                    pass
    results.sort(key=lambda m: m.get("shared_at", 0), reverse=True)
    return results


def load_received_pptx(username: str, report_id: str) -> bytes | None:
    return _read_bytes(username, "received", f"{report_id}.pptx")


def load_received(username: str, report_id: str) -> dict | None:
    """Load a received report's full state including video bytes and PPTX."""
    text = _read_text(username, "received", f"{report_id}.json")
    if not text:
        return None
    meta = json.loads(text)
    sub = "received"

    # Resolve video refs to bytes
    video_data = []
    for vref in meta.get("video_refs", []) or []:
        if vref is not None:
            vbytes = _read_bytes(username, sub, vref["path"])
            if vbytes:
                video_data.append((vbytes, vref["filename"]))
            else:
                video_data.append(None)
        else:
            video_data.append(None)
    meta["video_data"] = video_data

    # Attach PPTX bytes
    pptx = _read_bytes(username, sub, f"{report_id}.pptx")
    if pptx:
        meta["pptx_bytes"] = pptx

    # Resolve photo refs
    prefs = meta.get("photo_refs") or {}
    if prefs.get("full"):
        pfull = _read_bytes(username, sub, prefs["full"])
        if pfull:
            meta["photo_full"] = pfull
    if prefs.get("circular"):
        pcirc = _read_bytes(username, sub, prefs["circular"])
        if pcirc:
            meta["photo_circular"] = pcirc

    return meta


def delete_received(username: str, report_id: str) -> None:
    _delete_prefix(username, "received", report_id)
