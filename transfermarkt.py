"""Transfermarkt player season & career statistics via REST API.

Uses the open-source transfermarkt-api (https://github.com/felipeall/transfermarkt-api)
hosted at transfermarkt-api.fly.dev to fetch player data without needing
direct access to transfermarkt.com (which blocks cloud/datacenter IPs).
"""

from __future__ import annotations

import re

import requests

_API_BASE = "https://transfermarkt-api.fly.dev"
_TM_BASE = "https://www.transfermarkt.com"
_TIMEOUT = 15  # seconds


class TmBlockedError(Exception):
    """Raised when the Transfermarkt API is unavailable."""
    pass


# ─── API helpers ──────────────────────────────────────────────────────────

def _api_get(path: str) -> dict | list:
    """Call the Transfermarkt REST API and return parsed JSON."""
    url = f"{_API_BASE}{path}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        raise TmBlockedError("Cannot reach Transfermarkt API (connection error).")
    except requests.Timeout:
        raise TmBlockedError("Transfermarkt API timed out.")
    except requests.HTTPError as exc:
        raise TmBlockedError(f"Transfermarkt API error: {exc.response.status_code}")
    except Exception as exc:
        raise TmBlockedError(f"Transfermarkt API request failed: {exc}")


def _safe_int(value) -> int:
    """Convert a value (str, int, or None) to int, stripping dots/commas."""
    if value is None:
        return 0
    s = str(value).strip().replace(".", "").replace(",", "").replace("'", "")
    if not s or s == "-":
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


# ─── Search ───────────────────────────────────────────────────────────────

def _search_players(name: str) -> list[dict]:
    """Search for players by name. Returns list of result dicts."""
    data = _api_get(f"/players/search/{requests.utils.quote(name)}")
    return data.get("results", [])


def _best_match(candidates: list[dict], target_name: str, target_club: str = "") -> dict | None:
    """Pick the best matching player from search results."""
    if not candidates:
        return None

    target_lower = target_name.lower().strip()
    target_club_lower = target_club.lower().strip()

    def _score(p: dict) -> float:
        s = 0.0
        name_l = p.get("name", "").lower()
        if name_l == target_lower:
            s += 10
        elif target_lower in name_l or name_l in target_lower:
            s += 5
        else:
            target_words = set(target_lower.split())
            name_words = set(name_l.split())
            overlap = len(target_words & name_words)
            s += overlap * 2
        club_name = ""
        club = p.get("club")
        if isinstance(club, dict):
            club_name = club.get("name", "")
        elif isinstance(club, str):
            club_name = club
        if target_club_lower and target_club_lower in club_name.lower():
            s += 3
        return s

    ranked = sorted(candidates, key=_score, reverse=True)
    if _score(ranked[0]) >= 2:
        return ranked[0]
    return ranked[0] if len(ranked) == 1 else None


# ─── Stats ────────────────────────────────────────────────────────────────

def _fetch_player_stats_from_api(player_id: str, target_season: str) -> dict:
    """Fetch stats from the API and aggregate season + career totals.

    target_season is the Transfermarkt season ID, e.g. "2025" for 2025/2026.
    """
    season_matches = 0
    season_goals = 0
    season_assists = 0
    season_minutes = 0

    career_matches = 0
    career_goals = 0
    career_assists = 0
    career_minutes = 0

    data = _api_get(f"/players/{player_id}/stats")
    stats_list = data if isinstance(data, list) else data.get("stats", data.get("results", []))

    if isinstance(stats_list, dict):
        stats_list = [stats_list]

    for entry in stats_list:
        if not isinstance(entry, dict):
            continue

        apps = _safe_int(entry.get("appearances"))
        goals = _safe_int(entry.get("goals"))
        assists = _safe_int(entry.get("assists"))
        minutes = _safe_int(entry.get("minutesPlayed"))

        career_matches += apps
        career_goals += goals
        career_assists += assists
        career_minutes += minutes

        season_id = str(entry.get("seasonID", ""))
        if season_id == target_season:
            season_matches += apps
            season_goals += goals
            season_assists += assists
            season_minutes += minutes

    return {
        "season_matches": season_matches,
        "season_minutes": season_minutes,
        "season_goals": season_goals,
        "season_assists": season_assists,
        "career_matches": career_matches,
        "career_minutes": career_minutes,
        "career_goals": career_goals,
        "career_assists": career_assists,
    }


# ─── Public entry point ──────────────────────────────────────────────────

def fetch_player_stats(player_name: str, player_club: str = "", target_season_label: str = "2025/2026") -> dict:
    """Fetch season and career stats for a player from Transfermarkt.

    Returns a dict with keys:
        season_matches, season_minutes, season_goals, season_assists,
        career_matches, career_minutes, career_goals, career_assists,
        tm_url (the Transfermarkt profile URL)
    """
    empty = {
        "season_matches": 0, "season_minutes": 0,
        "season_goals": 0, "season_assists": 0,
        "career_matches": 0, "career_minutes": 0,
        "career_goals": 0, "career_assists": 0,
        "tm_url": "",
    }

    candidates = _search_players(player_name)
    if not candidates:
        return empty

    player = _best_match(candidates, player_name, player_club)
    if not player:
        return empty

    player_id = str(player.get("id", ""))
    if not player_id:
        return empty

    tm_url = f"{_TM_BASE}/-/profil/spieler/{player_id}"
    empty["tm_url"] = tm_url

    # Convert "2025/2026" → "2025" (Transfermarkt season ID = start year)
    m = re.match(r"(\d{4})/\d{4}", target_season_label)
    target_season = m.group(1) if m else "2025"

    try:
        stats = _fetch_player_stats_from_api(player_id, target_season)
    except TmBlockedError:
        return empty

    stats["tm_url"] = tm_url
    return stats
