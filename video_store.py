"""Video slot helpers — keep RAM usage bounded regardless of clip size.

A *video slot* is the per-competency video upload on the rating page. To stop
the app from holding N × 350 MB in session_state, each slot stores a
**reference dict** rather than raw bytes:

    {
      "filename":     "clip.mp4",
      "size":          123456789,
      "onedrive_path": "ScoutTemplateProject/<scout>/videos/<report_id>/00_clip.mp4",
      "report_id":     "<report_id>",
      "local_preview_path": "/tmp/scoutvid_xyz.mp4",   # optional — set while previewing
    }

The module provides:
  * ``save_uploaded_to_onedrive`` — stream an ``UploadedFile`` to disk, push
    to OneDrive via the chunked helper, and return a ref dict. Peak RAM is
    one chunk (~3 MiB).
  * ``ensure_preview_cached`` — lazily download the clip from OneDrive to a
    tempfile so ``st.video`` can play a file path. Only one slot at a time.
  * ``release_preview`` — delete the tempfile and clear ``local_preview_path``.
  * ``release_all_previews_except`` — keep at most one clip on disk.
  * ``download_for_embed`` — fetch into a caller-provided temp directory at
    PPTX generation / save-draft time.
  * ``delete_all_report_videos`` — cleanup after successful generation.

Video refs are safe to serialize to JSON. Legacy ``(bytes, filename)`` tuples
from old drafts are tolerated by ``coerce_slot`` (returned as-is with no
onedrive_path set).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import onedrive_sync


_TMP_PREFIX = "scoutvid_"


def _session():
    import streamlit as st
    return st.session_state


def coerce_slot(raw: Any) -> dict | None:
    """Normalise whatever is currently sitting in session_state for a slot.

    Returns a ref dict, or None for empty slots. Tolerates the legacy
    ``(bytes, filename)`` tuple shape so old drafts still load.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        data, filename = raw[0], raw[1]
        if isinstance(data, (bytes, bytearray)):
            return {
                "filename": filename or "video.mp4",
                "size": len(data),
                "onedrive_path": None,
                "_legacy_bytes": bytes(data),
            }
    return None


def save_uploaded_to_onedrive(
    uploaded_file,
    *,
    scout: str,
    report_id: str,
    slot_idx: int,
) -> dict | None:
    """Stream an ``UploadedFile`` from Streamlit to a tempfile, then chunk-upload
    it to OneDrive. Returns a reference dict (see module docstring) or None
    on failure. Peak RAM ≈ one chunk.
    """
    if uploaded_file is None:
        return None

    original_name = getattr(uploaded_file, "name", "video.mp4")
    suffix = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ".mp4"

    fd, tmp_path = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=suffix)
    os.close(fd)
    try:
        # Stream from the uploader to disk in 2 MB chunks — never whole bytes in RAM.
        total = 0
        uploaded_file.seek(0)
        with open(tmp_path, "wb") as out:
            while True:
                chunk = uploaded_file.read(2 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                total += len(chunk)

        ok, err, onedrive_path = onedrive_sync.upload_video(
            scout=scout,
            report_id=report_id,
            slot_idx=slot_idx,
            local_path=tmp_path,
            original_filename=original_name,
        )
        if not ok:
            return {"error": f"OneDrive upload failed: {err}",
                    "filename": original_name, "size": total,
                    "onedrive_path": None}
        return {
            "filename": original_name,
            "size": total,
            "onedrive_path": onedrive_path,
            "report_id": report_id,
            "local_preview_path": None,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def ensure_preview_cached(slot: dict, scout: str) -> str | None:
    """Download the clip from OneDrive to a tempfile if not already cached.
    Returns the local path (or None on failure).
    """
    if not slot:
        return None
    # Legacy bytes slots — write bytes to disk once, then forget them.
    if "_legacy_bytes" in slot and slot.get("local_preview_path") is None:
        data = slot.pop("_legacy_bytes")
        suffix = _path_suffix(slot.get("filename"))
        fd, tmp_path = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=suffix)
        os.close(fd)
        with open(tmp_path, "wb") as fp:
            fp.write(data)
        slot["local_preview_path"] = tmp_path
        return tmp_path

    existing = slot.get("local_preview_path")
    if existing and Path(existing).exists():
        return existing

    onedrive_path = slot.get("onedrive_path")
    if not onedrive_path:
        return None

    suffix = _path_suffix(slot.get("filename"))
    fd, tmp_path = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=suffix)
    os.close(fd)
    ok, err = onedrive_sync.download_to_path(scout, onedrive_path, tmp_path)
    if not ok:
        try: os.unlink(tmp_path)
        except OSError: pass
        return None
    slot["local_preview_path"] = tmp_path
    return tmp_path


def release_preview(slot: dict | None) -> None:
    if not slot:
        return
    p = slot.get("local_preview_path")
    if p:
        try:
            os.unlink(p)
        except OSError:
            pass
    slot["local_preview_path"] = None


def release_all_previews_except(slots_state: dict, keep_key: str | None) -> None:
    """Drop cached preview tempfiles for all slot keys except ``keep_key``.
    Ensures at most one clip sits on disk at a time.
    """
    for key, val in list(slots_state.items()):
        if key == keep_key:
            continue
        slot = coerce_slot(val)
        if slot and slot.get("local_preview_path"):
            release_preview(slot)
            slots_state[key] = slot


def download_for_embed(slot: dict, scout: str, dest_dir: str) -> str | None:
    """Stream the clip from OneDrive into ``dest_dir`` so it can be embedded
    into a PPTX from disk. Returns the local path (or None on failure).
    """
    if not slot:
        return None
    if "_legacy_bytes" in slot:
        path = os.path.join(dest_dir, slot.get("filename") or "clip.mp4")
        with open(path, "wb") as fp:
            fp.write(slot["_legacy_bytes"])
        return path
    onedrive_path = slot.get("onedrive_path")
    if not onedrive_path:
        return None
    filename = slot.get("filename") or "clip.mp4"
    path = os.path.join(dest_dir, filename)
    ok, _err = onedrive_sync.download_to_path(scout, onedrive_path, path)
    return path if ok else None


def delete_all_report_videos(scout: str, report_id: str) -> None:
    """Drop the entire /videos/<report_id>/ folder on OneDrive — called after
    successful generation/share since the pptx already holds the videos."""
    try:
        onedrive_sync.delete_video_folder(scout, report_id)
    except Exception:
        pass


def _path_suffix(filename: str | None) -> str:
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ".mp4"
