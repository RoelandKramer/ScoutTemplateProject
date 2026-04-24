"""Video slot helpers — keep RAM bounded while giving instant preview.

Upload path:
  * ``save_uploaded_to_local`` streams the file from Streamlit's uploader
    to a local disk path (``data/_videos/<report_id>/<slot>_<name>``) in
    a few-MB chunks. Peak RAM ≈ one chunk regardless of clip size.
  * Preview plays directly from that local path via ``st.video(path)`` —
    no OneDrive round-trip, no wait.

Persistence path:
  * ``push_slot_to_onedrive`` is called at **save-draft** time so drafts
    survive container restarts. Not called on upload, so the UX is
    instant and abandoned reports never leave OneDrive litter.
  * ``ensure_local`` re-materialises a slot's local_path from OneDrive
    when a draft is reopened in a fresh container.

Cleanup:
  * ``cleanup_report`` deletes the per-report local folder and (optionally)
    the OneDrive copy — called after generation/share, when a draft is
    deleted, or on logout.

Slot shape (JSON-safe except for runtime-only ``local_path``):

    {
      "filename":     "clip.mp4",
      "size":          123456789,
      "local_path":   "data/_videos/<rid>/00_clip.mp4",   # None after reload
      "onedrive_path": "ScoutTemplateProject/<scout>/videos/<rid>/00_clip.mp4",  # None until saved
      "report_id":    "<rid>",
    }
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import onedrive_sync


_VIDEOS_ROOT = Path(__file__).parent / "data" / "_videos"
_VIDEOS_ROOT.mkdir(parents=True, exist_ok=True)


def _report_dir(report_id: str) -> Path:
    d = _VIDEOS_ROOT / report_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip() or "video"


def coerce_slot(raw: Any) -> dict | None:
    """Normalise whatever is in session_state. Tolerates legacy tuples and
    old-style onedrive-only refs from prior versions of this module.
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
                "local_path": None,
                "onedrive_path": None,
                "_legacy_bytes": bytes(data),
            }
    return None


def save_uploaded_to_local(
    uploaded_file,
    *,
    report_id: str,
    slot_idx: int,
) -> dict | None:
    """Stream a Streamlit ``UploadedFile`` to disk. Peak RAM = one chunk.

    Returns the slot dict, or None for an empty input.
    """
    if uploaded_file is None:
        return None

    original_name = getattr(uploaded_file, "name", "video.mp4")
    safe_name = f"{slot_idx:02d}_{_safe(original_name)}"
    target = _report_dir(report_id) / safe_name

    uploaded_file.seek(0)
    total = 0
    with open(target, "wb") as out:
        while True:
            chunk = uploaded_file.read(2 * 1024 * 1024)  # 2 MB
            if not chunk:
                break
            out.write(chunk)
            total += len(chunk)

    return {
        "filename": original_name,
        "size": total,
        "local_path": str(target),
        "onedrive_path": None,
        "report_id": report_id,
    }


def preview_path(slot: dict | None) -> str | None:
    """Return a filesystem path playable by ``st.video``. No network calls;
    only looks at ``local_path`` (or materialises legacy bytes once)."""
    if not slot:
        return None
    if "_legacy_bytes" in slot:
        rid = slot.get("report_id") or "legacy"
        dst = _report_dir(rid) / _safe(slot.get("filename") or "video.mp4")
        with open(dst, "wb") as fp:
            fp.write(slot.pop("_legacy_bytes"))
        slot["local_path"] = str(dst)
    lp = slot.get("local_path")
    if lp and Path(lp).exists():
        return lp
    return None


def ensure_local(slot: dict, scout: str) -> str | None:
    """When a draft is reopened in a fresh container, the local file is gone
    but the OneDrive copy remains. Pull it down into the local cache.
    Returns the local path, or None on failure.
    """
    if not slot:
        return None
    lp = preview_path(slot)
    if lp:
        return lp
    onedrive_path = slot.get("onedrive_path")
    if not onedrive_path:
        return None
    rid = slot.get("report_id") or "orphan"
    name = _safe(slot.get("filename") or "video.mp4")
    target = _report_dir(rid) / name
    ok, _err = onedrive_sync.download_to_path(scout, onedrive_path, str(target))
    if not ok:
        return None
    slot["local_path"] = str(target)
    return str(target)


def push_slot_to_onedrive(slot: dict, *, scout: str, report_id: str, slot_idx: int) -> bool:
    """Upload a single slot's local file to OneDrive, setting ``onedrive_path``.
    Idempotent: skips if already uploaded.
    """
    if not slot or slot.get("onedrive_path"):
        return True
    lp = slot.get("local_path")
    if not lp or not Path(lp).exists():
        return False
    ok, _err, onedrive_path = onedrive_sync.upload_video(
        scout=scout,
        report_id=report_id,
        slot_idx=slot_idx,
        local_path=lp,
        original_filename=slot.get("filename") or "video.mp4",
    )
    if not ok:
        return False
    slot["onedrive_path"] = onedrive_path
    slot["report_id"] = report_id
    return True


def push_all_slots_to_onedrive(video_data: list, *, scout: str, report_id: str) -> None:
    """Called from save_draft to persist every slot's clip to OneDrive so
    the draft survives container restarts."""
    for i, raw in enumerate(video_data or []):
        slot = coerce_slot(raw)
        if slot is None:
            continue
        push_slot_to_onedrive(slot, scout=scout, report_id=report_id, slot_idx=i)


def materialize_tuples(video_data: list, scout: str | None = None) -> list:
    """Read each slot's bytes into memory for python-pptx embedding.
    Called only at generate/share time, and the caller should ``del`` the
    result the moment the pptx is built.
    """
    out: list = []
    for raw in video_data or []:
        slot = coerce_slot(raw)
        if slot is None:
            out.append(None)
            continue
        lp = slot.get("local_path")
        if (not lp or not Path(lp).exists()) and scout:
            lp = ensure_local(slot, scout)
        if not lp or not Path(lp).exists():
            out.append(None)
            continue
        try:
            with open(lp, "rb") as fp:
                data = fp.read()
        except OSError:
            out.append(None)
            continue
        out.append((data, slot.get("filename") or "video.mp4"))
    return out


def extract_refs(video_data: list) -> list:
    """Return JSON-safe slot refs (drops ``local_path`` since it isn't
    meaningful across containers)."""
    out: list = []
    for raw in video_data or []:
        slot = coerce_slot(raw)
        if slot is None:
            out.append(None)
            continue
        out.append({
            "filename": slot.get("filename"),
            "size": slot.get("size"),
            "onedrive_path": slot.get("onedrive_path"),
            "report_id": slot.get("report_id"),
        })
    return out


def cleanup_report(report_id: str | None, *, scout: str | None = None) -> None:
    """Delete local + OneDrive video copies for a given report id. Called
    after successful generation/share, on draft deletion, and on logout.
    Safe to call with unknown/missing ids."""
    if not report_id:
        return
    try:
        p = _VIDEOS_ROOT / report_id
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass
    if scout:
        try:
            onedrive_sync.delete_video_folder(scout, report_id)
        except Exception:
            pass


def cleanup_all_local() -> None:
    """Drop the entire local video cache — useful on logout."""
    try:
        if _VIDEOS_ROOT.exists():
            shutil.rmtree(_VIDEOS_ROOT, ignore_errors=True)
            _VIDEOS_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
