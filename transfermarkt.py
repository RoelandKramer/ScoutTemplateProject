"""Transfermarkt player season & career statistics.

Stats are fetched from the open-source transfermarkt-api
(https://github.com/felipeall/transfermarkt-api) hosted at
transfermarkt-api.fly.dev — that proxy returns clean JSON and is the
approach that worked reliably in earlier versions of this app.

The player portrait image is still scraped directly from
transfermarkt.com (only used for visual confirmation in the UI — not
stored or shared).

Availability (% of team matches in squad) is computed elsewhere via
Sofascore; the keys are still populated here with safe defaults so
downstream readers see a consistent dict shape.
"""

from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

_API_BASE = "https://transfermarkt-api.fly.dev"
_TM_BASE = "https://www.transfermarkt.com"
_TIMEOUT = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
_DELAY = 1.0  # polite delay before scraping the profile page for the image


class TmBlockedError(Exception):
    """Raised when the Transfermarkt API is unavailable."""


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


# ─── Search / matching ────────────────────────────────────────────────────

def _search_players(name: str) -> list[dict]:
    """Search for players by name. Returns list of result dicts."""
    data = _api_get(f"/players/search/{requests.utils.quote(name)}")
    return data.get("results", []) if isinstance(data, dict) else []


def _best_match(candidates: list[dict], target_name: str, target_club: str = "") -> dict | None:
    """Pick the best matching player from search results."""
    if not candidates:
        return None

    target_lower = target_name.lower().strip()
    target_club_lower = target_club.lower().strip()

    def _score(p: dict) -> float:
        s = 0.0
        name_l = (p.get("name") or "").lower()
        if name_l == target_lower:
            s += 10
        elif target_lower in name_l or (name_l and name_l in target_lower):
            s += 5
        else:
            target_words = set(target_lower.split())
            name_words = set(name_l.split())
            overlap = len(target_words & name_words)
            s += overlap * 2
        club_name = ""
        club = p.get("club")
        if isinstance(club, dict):
            club_name = club.get("name", "") or ""
        elif isinstance(club, str):
            club_name = club
        if target_club_lower and target_club_lower in club_name.lower():
            s += 3
        return s

    ranked = sorted(candidates, key=_score, reverse=True)
    if _score(ranked[0]) >= 2:
        return ranked[0]
    return ranked[0] if len(ranked) == 1 else None


# ─── Stats aggregation ───────────────────────────────────────────────────

def _fetch_player_stats_from_api(player_id: str, target_season: str) -> dict:
    """Fetch stats from the API and aggregate season + career totals.

    target_season is the Transfermarkt season ID, e.g. "2025" for 2025/2026.
    """
    season_matches = season_goals = season_assists = season_minutes = 0
    career_matches = career_goals = career_assists = career_minutes = 0

    data = _api_get(f"/players/{player_id}/stats")
    stats_list = data if isinstance(data, list) else data.get(
        "stats", data.get("results", []),
    )
    if isinstance(stats_list, dict):
        stats_list = [stats_list]

    for entry in stats_list or []:
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


# ─── Player portrait image (scraped directly) ────────────────────────────

def _profile_url_path(player_id: str) -> str:
    return f"/-/profil/spieler/{player_id}"


def _fetch_player_image(player_id: str) -> bytes | None:
    """Fetch the player's portrait from their TM profile page."""
    if not player_id:
        return None
    full_url = f"{_TM_BASE}{_profile_url_path(player_id)}"
    try:
        time.sleep(_DELAY)
        resp = requests.get(full_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    for selector in (
        "img.data-header__profile-image",
        "header img[src*='portrait']",
        "header img[src*='/header/']",
        "div.data-header__profile-container img",
        "img[data-src*='portrait']",
    ):
        img_tag = soup.select_one(selector)
        if not img_tag:
            continue
        img_url = img_tag.get("src") or img_tag.get("data-src") or ""
        if not img_url or "default.jpg" in img_url or not img_url.startswith("http"):
            continue
        try:
            img_resp = requests.get(img_url, headers=_HEADERS, timeout=_TIMEOUT)
            img_resp.raise_for_status()
            if img_resp.headers.get("content-type", "").startswith("image"):
                return img_resp.content
        except Exception:
            pass
    return None


# ─── Public entry point ──────────────────────────────────────────────────

def fetch_player_stats(
    player_name: str,
    player_club: str = "",
    target_season_label: str = "2025/2026",
) -> dict:
    """Fetch season and career stats for a player from Transfermarkt.

    Returns a dict with keys:
        season_matches, season_minutes, season_goals, season_assists,
        career_matches, career_minutes, career_goals, career_assists,
        availability_pct, availability_in_squad, availability_total
            (None / 0 here — populated downstream from Sofascore),
        tm_url (Transfermarkt profile URL),
        tm_image (raw image bytes, or None).
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

    try:
        candidates = _search_players(player_name)
    except TmBlockedError:
        return result
    if not candidates:
        return result

    player = _best_match(candidates, player_name, player_club)
    if not player:
        return result

    player_id = str(player.get("id", "") or "")
    if not player_id:
        return result

    result["tm_url"] = f"{_TM_BASE}{_profile_url_path(player_id)}"

    # Convert "2025/2026" → "2025" (TM season ID is the start year)
    m = re.match(r"(\d{4})/\d{4}", target_season_label)
    target_season = m.group(1) if m else "2025"

    try:
        stats = _fetch_player_stats_from_api(player_id, target_season)
        result.update(stats)
    except TmBlockedError:
        pass  # leave numeric fields at 0, still return image + url

    # Best-effort portrait fetch (scraped). Failure leaves it None.
    try:
        result["tm_image"] = _fetch_player_image(player_id)
    except Exception:
        pass

    return result
