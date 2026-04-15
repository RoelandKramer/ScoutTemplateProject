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
import logging
import time
import uuid
from pathlib import Path

import requests as _requests  # already in requirements

log = logging.getLogger(__name__)

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

# ─── In-memory cache (survives across Streamlit reruns within one session) ──
# key → (value, timestamp)
_cache: dict[str, tuple] = {}
_CACHE_TTL = 120  # seconds — cache listing/metadata reads for 2 minutes

# SHA cache: path → sha  (avoids an extra GET before every PUT)
_sha_cache: dict[str, str] = {}


def _cache_get(key):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
        del _cache[key]
    return None


def _cache_set(key, val):
    _cache[key] = (val, time.time())


def _cache_invalidate(prefix: str):
    """Drop all cache entries whose key starts with *prefix*."""
    for k in [k for k in _cache if k.startswith(prefix)]:
        del _cache[k]


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

        # Verify the connection and ensure the repo/branch is ready
        _ensure_repo_ready()
        _backend = "github"
        log.info("Storage backend: GitHub (%s branch %s)", _gh_repo, _gh_branch)
    except Exception as exc:
        log.warning("GitHub storage not available (%s), falling back to local", exc)
        _backend = "local"


def _ensure_repo_ready():
    """Make sure the target branch exists. If the repo is empty, create an
    initial commit so the Contents API can write to it."""
    r = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}/branches/{_gh_branch}",
        headers=_gh_headers(),
    )
    if r.status_code == 200:
        return  # branch exists

    # Get repo info
    r2 = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}",
        headers=_gh_headers(),
    )
    if r2.status_code != 200:
        raise ConnectionError(
            f"Cannot access repo {_gh_repo}: {r2.status_code} {r2.text[:200]}"
        )
    repo_info = r2.json()
    default_branch = repo_info.get("default_branch", "main")

    if repo_info.get("size", 0) == 0:
        # Repo is completely empty — create initial commit with a README
        r3 = _requests.put(
            f"https://api.github.com/repos/{_gh_repo}/contents/README.md",
            headers=_gh_headers(),
            json={
                "message": "Initialize data repository",
                "content": base64.b64encode(
                    b"# Scout Report Data\nPersistent storage for scout reports.\n"
                ).decode("ascii"),
            },
        )
        if r3.status_code not in (200, 201):
            raise ConnectionError(
                f"Cannot initialize repo: {r3.status_code} {r3.text[:200]}"
            )
        if _gh_branch == default_branch:
            return

    # Create our target branch from the default branch
    if _gh_branch != default_branch:
        ref_r = _requests.get(
            f"https://api.github.com/repos/{_gh_repo}/git/refs/heads/{default_branch}",
            headers=_gh_headers(),
        )
        if ref_r.status_code == 200:
            sha = ref_r.json()["object"]["sha"]
            _requests.post(
                f"https://api.github.com/repos/{_gh_repo}/git/refs",
                headers=_gh_headers(),
                json={"ref": f"refs/heads/{_gh_branch}", "sha": sha},
            )


# ─── GitHub helpers ─────────────────────────────────────────────────────────

def _gh_headers():
    return {
        "Authorization": f"Bearer {_gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_path(username: str, subfolder: str, filename: str) -> str:
    return f"{_gh_prefix}/{username}/{subfolder}/{filename}"


def _gh_get_sha(path: str) -> str | None:
    """Get just the SHA for a file (from cache first, then API)."""
    if path in _sha_cache:
        return _sha_cache[path]
    r = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        params={"ref": _gh_branch},
    )
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, dict):
            sha = data.get("sha")
            if sha:
                _sha_cache[path] = sha
            return sha
    return None


def _gh_read(path: str) -> bytes | None:
    """Download file bytes from GitHub."""
    r = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        params={"ref": _gh_branch},
    )
    if r.status_code != 200:
        return None
    data = r.json()
    if not isinstance(data, dict):
        return None
    # Cache the SHA for future writes
    if data.get("sha"):
        _sha_cache[path] = data["sha"]
    # Files ≤ 1 MB have base64 content inline
    if data.get("content"):
        return base64.b64decode(data["content"])
    # Larger files: follow the download URL
    if data.get("download_url"):
        dl = _requests.get(data["download_url"], headers=_gh_headers())
        if dl.status_code == 200:
            return dl.content
    return None


def _gh_write(path: str, data: bytes, message: str = "auto-save") -> None:
    """Create or update a file in the repo. Raises on failure.

    Optimized: tries PUT without SHA first (works for new files),
    falls back to GET SHA + PUT if the file already exists.
    """
    if len(data) > _GH_MAX_BYTES:
        log.warning("Skipping %s: %d bytes exceeds GitHub limit", path, len(data))
        return

    encoded = base64.b64encode(data).decode("ascii")

    # If we have a cached SHA, use it directly (update)
    cached_sha = _sha_cache.get(path)
    if cached_sha:
        body = {
            "message": message,
            "content": encoded,
            "branch": _gh_branch,
            "sha": cached_sha,
        }
        r = _requests.put(
            f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
            headers=_gh_headers(),
            json=body,
        )
        if r.status_code in (200, 201):
            # Update SHA cache with new SHA
            resp_data = r.json()
            if resp_data.get("content", {}).get("sha"):
                _sha_cache[path] = resp_data["content"]["sha"]
            return
        if r.status_code == 409:
            # SHA is stale, clear cache and fall through
            _sha_cache.pop(path, None)
        elif r.status_code == 422:
            # File might not exist anymore, clear cache and fall through
            _sha_cache.pop(path, None)
        else:
            error_msg = r.text[:300] if r.text else "unknown error"
            raise IOError(f"Failed to save {path.split('/')[-1]} to GitHub (HTTP {r.status_code}): {error_msg}")

    # Try creating as new file (no SHA)
    body = {
        "message": message,
        "content": encoded,
        "branch": _gh_branch,
    }
    r = _requests.put(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        json=body,
    )
    if r.status_code in (200, 201):
        resp_data = r.json()
        if resp_data.get("content", {}).get("sha"):
            _sha_cache[path] = resp_data["content"]["sha"]
        return

    if r.status_code == 409 or r.status_code == 422:
        # File exists — need the SHA to update it
        sha = _gh_get_sha(path)
        if sha:
            body["sha"] = sha
            r2 = _requests.put(
                f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
                headers=_gh_headers(),
                json=body,
            )
            if r2.status_code in (200, 201):
                resp_data = r2.json()
                if resp_data.get("content", {}).get("sha"):
                    _sha_cache[path] = resp_data["content"]["sha"]
                return
            error_msg = r2.text[:300] if r2.text else "unknown error"
            raise IOError(f"Failed to save {path.split('/')[-1]} to GitHub (HTTP {r2.status_code}): {error_msg}")

    error_msg = r.text[:300] if r.text else "unknown error"
    raise IOError(f"Failed to save {path.split('/')[-1]} to GitHub (HTTP {r.status_code}): {error_msg}")


def _gh_delete_file(path: str, message: str = "auto-delete") -> bool:
    """Delete a single file from the repo."""
    sha = _sha_cache.get(path) or _gh_get_sha(path)
    if not sha:
        return False
    r = _requests.delete(
        f"https://api.github.com/repos/{_gh_repo}/contents/{path}",
        headers=_gh_headers(),
        json={"message": message, "sha": sha, "branch": _gh_branch},
    )
    _sha_cache.pop(path, None)
    return r.status_code == 200


def _gh_list_dir(dirpath: str) -> list[str]:
    """List file names in a GitHub directory. Returns [] on 404.
    Results are cached."""
    cache_key = f"dir:{dirpath}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    r = _requests.get(
        f"https://api.github.com/repos/{_gh_repo}/contents/{dirpath}",
        headers=_gh_headers(),
        params={"ref": _gh_branch},
    )
    if r.status_code != 200:
        _cache_set(cache_key, [])
        return []
    items = r.json()
    if not isinstance(items, list):
        _cache_set(cache_key, [])
        return []
    names = [f["name"] for f in items if f.get("type") == "file"]
    # Also cache SHAs from the listing (avoids extra GETs on write)
    for f in items:
        if f.get("type") == "file" and f.get("sha"):
            full_path = f"{dirpath}/{f['name']}"
            _sha_cache[full_path] = f["sha"]
    _cache_set(cache_key, names)
    return names


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
    """Read a text file, with caching for small JSON metadata."""
    _init_backend()
    if _backend == "github":
        cache_key = f"txt:{_gh_prefix}/{username}/{subfolder}/{filename}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        data = _gh_read(_gh_path(username, subfolder, filename))
        text = data.decode("utf-8") if data else None
        if text is not None:
            _cache_set(cache_key, text)
        return text
    else:
        p = DATA_DIR / username / subfolder / filename
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None


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
        # Invalidate caches for this folder
        _cache_invalidate(f"dir:{dirpath}")
        _cache_invalidate(f"txt:{dirpath}")
    else:
        d = DATA_DIR / username / subfolder
        if d.exists():
            for f in d.glob(f"{prefix}*"):
                f.unlink(missing_ok=True)


def _invalidate_user_caches(username: str, subfolder: str) -> None:
    """Invalidate all caches related to a user's subfolder after a write."""
    if _backend == "github":
        dirpath = f"{_gh_prefix}/{username}/{subfolder}"
        _cache_invalidate(f"dir:{dirpath}")
        _cache_invalidate(f"txt:{dirpath}")


# ─── Diagnostic ─────────────────────────────────────────────────────────────

def get_backend_info() -> str:
    """Return a short description of the active storage backend (for debugging)."""
    _init_backend()
    if _backend == "github":
        return f"GitHub: {_gh_repo} (branch: {_gh_branch})"
    return f"Local: {DATA_DIR}"


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
    _invalidate_user_caches(username, sub)
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

    _invalidate_user_caches(username, sub)

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
    _invalidate_user_caches(username, "finished")


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
    _invalidate_user_caches(to_username, sub)
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
