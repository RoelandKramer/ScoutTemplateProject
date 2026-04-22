"""Player season & career statistics.

Transfermarkt blocks datacenter (and often residential) IPs via an AWS WAF
captcha wall, so both direct scraping and third-party proxies (e.g.
transfermarkt-api.fly.dev) fail in deployment. We therefore source player
stats entirely from Sofascore now — the public function name and return
shape are kept identical so the rest of the app doesn't need to change.

Internally:
  * Player resolution, season/career stats, and portrait image all come
    from the Sofascore JSON API (via ``sofascore`` module helpers).
  * The returned ``tm_url`` is left blank (unused by the UI) and ``tm_image``
    contains the player's Sofascore portrait bytes (display-only).

Availability (% of team matches in squad) is still populated downstream
from Sofascore in the physical-data flow; we leave those keys at safe
defaults here so downstream readers see a consistent dict shape.
"""

from __future__ import annotations

import requests

from sofascore import _resolve, get_player_stats

_SS_API_BASE = "https://api.sofascore.com"
_SS_WEB_BASE = "https://www.sofascore.com"
_TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": f"{_SS_WEB_BASE}/",
}


class TmBlockedError(Exception):
    """Raised when the upstream stats API is unavailable.

    Retained for backwards-compatibility with callers that catch this
    exception; in practice we swallow Sofascore failures and return
    zero-filled stats.
    """


def _fetch_player_image(player_id: int) -> bytes | None:
    """Fetch the player's portrait PNG from Sofascore."""
    if not player_id:
        return None
    url = f"{_SS_API_BASE}/api/v1/player/{player_id}/image"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("image") and resp.content:
            return resp.content
    except Exception:
        pass
    return None


def fetch_player_stats(
    player_name: str,
    player_club: str = "",
    target_season_label: str = "2025/2026",
) -> dict:
    """Fetch season and career stats for a player (via Sofascore).

    Returns a dict with keys:
        season_matches, season_minutes, season_goals, season_assists,
        career_matches, career_minutes, career_goals, career_assists,
        availability_pct, availability_in_squad, availability_total
            (None / 0 here — populated downstream from Sofascore),
        tm_url (kept for backwards-compat, empty),
        tm_image (raw portrait bytes, or None).

    ``target_season_label`` is ignored for Sofascore — the current European
    season is derived from today's date inside ``sofascore.get_player_stats``.
    Parameter retained so existing call sites keep working.
    """
    result = {
        "season_matches": 0, "season_minutes": 0,
        "season_goals": 0, "season_assists": 0,
        "career_matches": 0, "career_minutes": 0,
        "career_goals": 0, "career_assists": 0,
        "availability_pct": None,
        "availability_in_squad": 0,
        "availability_total": 0,
        "tm_url": "",
        "tm_image": None,
    }

    if not player_name:
        return result

    try:
        stats = get_player_stats(player_name, player_club)
    except Exception:
        stats = {}
    for k, v in (stats or {}).items():
        if v:
            result[k] = v

    try:
        pid, _tid = _resolve(player_name, player_club)
    except Exception:
        pid = None
    if pid:
        try:
            result["tm_image"] = _fetch_player_image(pid)
        except Exception:
            pass

    return result
