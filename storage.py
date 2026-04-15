"""Persistent storage for scout report drafts and finished reports.

Each user gets a folder under  data/<username>/
  - drafts/<report_id>.json   — in-progress reports (stars, comments, metadata)
  - finished/<report_id>.pptx — generated PowerPoint files
  - finished/<report_id>.json — metadata for finished reports

Videos within drafts are stored as separate files to keep JSON small:
  - drafts/<report_id>_video_<i>.<ext>
"""

import base64
import json
import os
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _user_dir(username: str) -> Path:
    return DATA_DIR / username


def _drafts_dir(username: str) -> Path:
    d = _user_dir(username) / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _finished_dir(username: str) -> Path:
    d = _user_dir(username) / "finished"
    d.mkdir(parents=True, exist_ok=True)
    return d


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

    drafts = _drafts_dir(username)

    # Save video files separately
    video_refs = []
    for i, vd in enumerate(video_data):
        if vd is not None:
            vbytes, vname = vd
            ext = vname.rsplit(".", 1)[-1] if "." in vname else "mp4"
            vpath = drafts / f"{report_id}_video_{i}.{ext}"
            vpath.write_bytes(vbytes)
            video_refs.append({"filename": vname, "path": str(vpath.name)})
        else:
            video_refs.append(None)

    # Save upload bytes if present
    upload_ref = None
    if upload_bytes:
        upath = drafts / f"{report_id}_upload.pptx"
        upath.write_bytes(upload_bytes)
        upload_ref = {"filename": upload_filename or "upload.pptx", "path": str(upath.name)}

    # Save player photos if present
    photo_refs = {}
    if photo_full:
        pfull_path = drafts / f"{report_id}_photo_full.png"
        pfull_path.write_bytes(photo_full)
        photo_refs["full"] = str(pfull_path.name)
    if photo_circular:
        pcirc_path = drafts / f"{report_id}_photo_circ.png"
        pcirc_path.write_bytes(photo_circular)
        photo_refs["circular"] = str(pcirc_path.name)

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
        "created_at": _load_draft_meta(username, report_id).get("created_at", time.time()),
    }

    (drafts / f"{report_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_id


def _load_draft_meta(username: str, report_id: str) -> dict:
    p = _drafts_dir(username) / f"{report_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_draft(username: str, report_id: str) -> dict | None:
    """Load a draft including video bytes. Returns None if not found."""
    meta = _load_draft_meta(username, report_id)
    if not meta:
        return None

    drafts = _drafts_dir(username)

    # Resolve video refs to actual bytes
    video_data = []
    for vref in meta.get("video_refs", []):
        if vref is not None:
            vpath = drafts / vref["path"]
            if vpath.exists():
                video_data.append((vpath.read_bytes(), vref["filename"]))
            else:
                video_data.append(None)
        else:
            video_data.append(None)
    meta["video_data"] = video_data

    # Resolve upload ref
    uref = meta.get("upload_ref")
    if uref:
        upath = drafts / uref["path"]
        if upath.exists():
            meta["upload_bytes"] = upath.read_bytes()
            meta["upload_filename"] = uref["filename"]

    # Resolve photo refs
    prefs = meta.get("photo_refs") or {}
    if prefs.get("full"):
        pfull = drafts / prefs["full"]
        if pfull.exists():
            meta["photo_full"] = pfull.read_bytes()
    if prefs.get("circular"):
        pcirc = drafts / prefs["circular"]
        if pcirc.exists():
            meta["photo_circular"] = pcirc.read_bytes()

    return meta


def list_drafts(username: str) -> list[dict]:
    """Return all drafts for a user, sorted by most recently updated."""
    drafts = _drafts_dir(username)
    results = []
    for f in drafts.glob("*.json"):
        if f.stem.count("_") == 0:  # only root JSON, not video refs
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                results.append(meta)
            except Exception:
                pass
    results.sort(key=lambda m: m.get("updated_at", 0), reverse=True)
    return results


def delete_draft(username: str, report_id: str) -> None:
    """Delete a draft and all its associated files."""
    drafts = _drafts_dir(username)
    for f in drafts.glob(f"{report_id}*"):
        f.unlink(missing_ok=True)


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
    finished = _finished_dir(username)

    (finished / f"{report_id}.pptx").write_bytes(pptx_bytes)

    # Save photos
    photo_refs = {}
    if photo_full:
        (finished / f"{report_id}_photo_full.png").write_bytes(photo_full)
        photo_refs["full"] = f"{report_id}_photo_full.png"
    if photo_circular:
        (finished / f"{report_id}_photo_circ.png").write_bytes(photo_circular)
        photo_refs["circular"] = f"{report_id}_photo_circ.png"

    # Save video files separately
    video_refs = []
    if video_data:
        for i, vd in enumerate(video_data):
            if vd is not None:
                vbytes, vname = vd
                ext = vname.rsplit(".", 1)[-1] if "." in vname else "mp4"
                vpath = finished / f"{report_id}_video_{i}.{ext}"
                vpath.write_bytes(vbytes)
                video_refs.append({"filename": vname, "path": str(vpath.name)})
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
    (finished / f"{report_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Clean up the draft if it exists
    delete_draft(username, report_id)

    return report_id


def list_finished(username: str) -> list[dict]:
    """Return all finished reports, sorted by most recently finished."""
    finished = _finished_dir(username)
    results = []
    for f in finished.glob("*.json"):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            results.append(meta)
        except Exception:
            pass
    results.sort(key=lambda m: m.get("finished_at", 0), reverse=True)
    return results


def load_finished_pptx(username: str, report_id: str) -> bytes | None:
    """Return the PPTX bytes for a finished report."""
    p = _finished_dir(username) / f"{report_id}.pptx"
    return p.read_bytes() if p.exists() else None


def load_finished(username: str, report_id: str) -> dict | None:
    """Load a finished report's full state including PPTX, videos, photos.
    Returns None if not found.
    """
    finished = _finished_dir(username)
    p = finished / f"{report_id}.json"
    if not p.exists():
        return None
    meta = json.loads(p.read_text(encoding="utf-8"))

    # Attach PPTX bytes
    pptx_path = finished / f"{report_id}.pptx"
    if pptx_path.exists():
        meta["pptx_bytes"] = pptx_path.read_bytes()

    # Resolve video refs to bytes
    video_data = []
    for vref in meta.get("video_refs", []) or []:
        if vref is not None:
            vpath = finished / vref["path"]
            if vpath.exists():
                video_data.append((vpath.read_bytes(), vref["filename"]))
            else:
                video_data.append(None)
        else:
            video_data.append(None)
    meta["video_data"] = video_data

    # Resolve photo refs
    prefs = meta.get("photo_refs") or {}
    if prefs.get("full"):
        pfull = finished / prefs["full"]
        if pfull.exists():
            meta["photo_full"] = pfull.read_bytes()
    if prefs.get("circular"):
        pcirc = finished / prefs["circular"]
        if pcirc.exists():
            meta["photo_circular"] = pcirc.read_bytes()

    return meta


def mark_shared(username: str, report_id: str, shared_to: str) -> None:
    """Mark a finished report as shared to another user."""
    p = _finished_dir(username) / f"{report_id}.json"
    if not p.exists():
        return
    meta = json.loads(p.read_text(encoding="utf-8"))
    shared_list = meta.get("shared_to", [])
    if shared_to not in shared_list:
        shared_list.append(shared_to)
    meta["shared_to"] = shared_list
    meta["shared_at"] = time.time()
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_finished(username: str, report_id: str) -> None:
    finished = _finished_dir(username)
    for f in finished.glob(f"{report_id}*"):
        f.unlink(missing_ok=True)


# ─── Received (shared) report operations ────────────────────────────────────

def _received_dir(username: str) -> Path:
    d = _user_dir(username) / "received"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    """Copy a finished report into the recipient's received folder,
    preserving the full editable state (videos, player data, stats) so the
    recipient can resume editing it with everything filled in.
    """
    received = _received_dir(to_username)
    share_id = uuid.uuid4().hex[:12]

    (received / f"{share_id}.pptx").write_bytes(pptx_bytes)

    # Save video files separately (same pattern as drafts)
    video_refs = []
    if video_data:
        for i, vd in enumerate(video_data):
            if vd is not None:
                vbytes, vname = vd
                ext = vname.rsplit(".", 1)[-1] if "." in vname else "mp4"
                vpath = received / f"{share_id}_video_{i}.{ext}"
                vpath.write_bytes(vbytes)
                video_refs.append({"filename": vname, "path": str(vpath.name)})
            else:
                video_refs.append(None)

    # Save player photos
    photo_refs = {}
    if photo_full:
        (received / f"{share_id}_photo_full.png").write_bytes(photo_full)
        photo_refs["full"] = f"{share_id}_photo_full.png"
    if photo_circular:
        (received / f"{share_id}_photo_circ.png").write_bytes(photo_circular)
        photo_refs["circular"] = f"{share_id}_photo_circ.png"

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
    (received / f"{share_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return share_id


def list_received(username: str) -> list[dict]:
    """Return all received reports, sorted by most recently shared."""
    received = _received_dir(username)
    results = []
    for f in received.glob("*.json"):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            results.append(meta)
        except Exception:
            pass
    results.sort(key=lambda m: m.get("shared_at", 0), reverse=True)
    return results


def load_received_pptx(username: str, report_id: str) -> bytes | None:
    p = _received_dir(username) / f"{report_id}.pptx"
    return p.read_bytes() if p.exists() else None


def load_received(username: str, report_id: str) -> dict | None:
    """Load a received report's full state including video bytes and PPTX.
    Returns None if not found.
    """
    received = _received_dir(username)
    p = received / f"{report_id}.json"
    if not p.exists():
        return None
    meta = json.loads(p.read_text(encoding="utf-8"))

    # Resolve video refs to bytes
    video_data = []
    for vref in meta.get("video_refs", []) or []:
        if vref is not None:
            vpath = received / vref["path"]
            if vpath.exists():
                video_data.append((vpath.read_bytes(), vref["filename"]))
            else:
                video_data.append(None)
        else:
            video_data.append(None)
    meta["video_data"] = video_data

    # Attach PPTX bytes
    pptx_path = received / f"{report_id}.pptx"
    if pptx_path.exists():
        meta["pptx_bytes"] = pptx_path.read_bytes()

    # Resolve photo refs
    prefs = meta.get("photo_refs") or {}
    if prefs.get("full"):
        pfull = received / prefs["full"]
        if pfull.exists():
            meta["photo_full"] = pfull.read_bytes()
    if prefs.get("circular"):
        pcirc = received / prefs["circular"]
        if pcirc.exists():
            meta["photo_circular"] = pcirc.read_bytes()

    return meta


def delete_received(username: str, report_id: str) -> None:
    received = _received_dir(username)
    for f in received.glob(f"{report_id}*"):
        f.unlink(missing_ok=True)