"""Transfermarkt player season & career statistics via direct web scraping.

Scrapes transfermarkt.com directly with browser-like headers and retry logic.
Falls back to the hosted REST API at transfermarkt-api.fly.dev when direct
scraping fails.  Both approaches rotate User-Agents and retry on transient errors.
"""

from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_TM_BASE = "https://www.transfermarkt.com"
_API_BASE = "https://transfermarkt-api.fly.dev"
_TIMEOUT = 20
_MAX_RETRIES = 3

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]


class TmBlockedError(Exception):
    """Raised when Transfermarkt data cannot be fetched."""
    pass


# ─── Session management ──────────────────────────────────────────────────

_session: requests.Session | None = None


def _new_session() -> requests.Session:
    """Create a fresh requests session with randomized browser-like headers."""
    s = requests.Session()
    ua = random.choice(_USER_AGENTS)
    s.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    return s


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _new_session()
    return _session


def _reset_session() -> None:
    global _session
    _session = _new_session()


def _fetch_page(url: str) -> BeautifulSoup:
    """Fetch a page from transfermarkt.com with retries and UA rotation."""
    session = _get_session()
    last_error = ""
    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            time.sleep(1.0 + random.uniform(0.5, 1.5) * attempt)
            _reset_session()
            session = _get_session()
        try:
            resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                return BeautifulSoup(resp.content, "html.parser")
            last_error = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last_error = str(e)
    raise TmBlockedError(f"Could not reach transfermarkt.com after {_MAX_RETRIES} attempts ({last_error})")


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


# ─── Direct scraping: search ─────────────────────────────────────────────

def _search_players_scrape(name: str) -> list[dict]:
    """Search transfermarkt.com directly for players by name."""
    url = f"{_TM_BASE}/schnellsuche/ergebnis/schnellsuche?query={quote(name)}"
    soup = _fetch_page(url)

    # The players section header can be in English, German, or other languages
    player_box = None
    for box in soup.select("div.box"):
        h2 = box.select_one("h2")
        if h2:
            text = h2.get_text().lower()
            if "player" in text or "spieler" in text or "giocator" in text:
                player_box = box
                break

    if player_box is None:
        return []

    results = []
    for row in player_box.select("tbody tr"):
        link = row.select_one("td.hauptlink a")
        if not link:
            continue
        href = link.get("href", "")
        pname = link.get("title", "") or link.get_text(strip=True)

        m = re.search(r"/spieler/(\d+)", href)
        if not m:
            continue
        player_id = m.group(1)

        club_img = row.select_one("img.tiny_wappen")
        club_name = club_img.get("title", "") if club_img else ""

        results.append({
            "id": player_id,
            "name": pname,
            "club": {"name": club_name},
        })

    return results


# ─── Direct scraping: stats ──────────────────────────────────────────────

def _fetch_stats_scrape(player_id: str, target_season: str) -> dict:
    """Scrape the detailed performance stats page for a player."""
    url = f"{_TM_BASE}/-/leistungsdatendetails/spieler/{player_id}"
    soup = _fetch_page(url)

    table = soup.select_one("table.items")
    if not table:
        raise TmBlockedError("Stats table not found on page")

    # Build column-index map from <th> title attributes
    col_map: dict[str, int] = {}
    for i, th in enumerate(table.select("thead tr th")):
        title = (th.get("title") or th.get_text(strip=True)).lower()
        if "appearance" in title or "einsätze" in title or "einsaetze" in title:
            col_map["apps"] = i
        elif title in ("goals", "tore"):
            col_map["goals"] = i
        elif title in ("assists", "vorlagen"):
            col_map["assists"] = i
        elif "minutes" in title or "minuten" in title:
            col_map["minutes"] = i

    totals = {
        "season_matches": 0, "season_goals": 0,
        "season_assists": 0, "season_minutes": 0,
        "career_matches": 0, "career_goals": 0,
        "career_assists": 0, "career_minutes": 0,
    }

    for row in table.select("tbody tr"):
        tds = row.select("td")

        # Extract season ID from the competition link href
        season_id = ""
        for a_tag in row.select("a[href]"):
            m = re.search(r"/saison_id/(\d+)", a_tag.get("href", ""))
            if m:
                season_id = m.group(1)
                break

        def _val(col_name: str) -> int:
            idx = col_map.get(col_name)
            if idx is not None and idx < len(tds):
                return _safe_int(tds[idx].get_text(strip=True))
            return 0

        apps = _val("apps")
        goals = _val("goals")
        assists = _val("assists")
        minutes = _val("minutes")

        totals["career_matches"] += apps
        totals["career_goals"] += goals
        totals["career_assists"] += assists
        totals["career_minutes"] += minutes

        if season_id == target_season:
            totals["season_matches"] += apps
            totals["season_goals"] += goals
            totals["season_assists"] += assists
            totals["season_minutes"] += minutes

    return totals


# ─── API fallback ────────────────────────────────────────────────────────

def _api_get(path: str) -> dict | list:
    """Call the hosted Transfermarkt REST API (fallback)."""
    url = f"{_API_BASE}{path}"
    resp = requests.get(
        url, timeout=_TIMEOUT,
        headers={"User-Agent": random.choice(_USER_AGENTS), "Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


def _search_players_api(name: str) -> list[dict]:
    data = _api_get(f"/players/search/{quote(name)}")
    return data.get("results", [])


def _fetch_stats_api(player_id: str, target_season: str) -> dict:
    data = _api_get(f"/players/{player_id}/stats")
    stats_list = data if isinstance(data, list) else data.get("stats", data.get("results", []))
    if isinstance(stats_list, dict):
        stats_list = [stats_list]

    totals = {
        "season_matches": 0, "season_goals": 0,
        "season_assists": 0, "season_minutes": 0,
        "career_matches": 0, "career_goals": 0,
        "career_assists": 0, "career_minutes": 0,
    }
    for entry in stats_list:
        if not isinstance(entry, dict):
            continue
        apps = _safe_int(entry.get("appearances"))
        goals = _safe_int(entry.get("goals"))
        assists = _safe_int(entry.get("assists"))
        minutes = _safe_int(entry.get("minutesPlayed"))

        totals["career_matches"] += apps
        totals["career_goals"] += goals
        totals["career_assists"] += assists
        totals["career_minutes"] += minutes

        sid = str(entry.get("seasonID", entry.get("seasonId", "")))
        if sid == target_season:
            totals["season_matches"] += apps
            totals["season_goals"] += goals
            totals["season_assists"] += assists
            totals["season_minutes"] += minutes

    return totals


# ─── Matching ────────────────────────────────────────────────────────────

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
            s += len(target_words & name_words) * 2
        club = p.get("club")
        club_name = ""
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


# ─── Public entry point ──────────────────────────────────────────────────

def fetch_player_stats(player_name: str, player_club: str = "", target_season_label: str = "2025/2026") -> dict:
    """Fetch season and career stats for a player from Transfermarkt.

    Tries direct scraping first, falls back to the REST API.

    Returns a dict with keys:
        season_matches, season_minutes, season_goals, season_assists,
        career_matches, career_minutes, career_goals, career_assists,
        tm_url (the Transfermarkt profile URL)
    """
    empty: dict = {
        "season_matches": 0, "season_minutes": 0,
        "season_goals": 0, "season_assists": 0,
        "career_matches": 0, "career_minutes": 0,
        "career_goals": 0, "career_assists": 0,
        "tm_url": "",
    }

    m = re.match(r"(\d{4})/\d{4}", target_season_label)
    target_season = m.group(1) if m else "2025"

    # ── Step 1: find the player ──────────────────────────────────────────
    player_id: str | None = None
    search_errors: list[str] = []

    # Strategy A – direct scraping
    try:
        candidates = _search_players_scrape(player_name)
        if candidates:
            player = _best_match(candidates, player_name, player_club)
            if player:
                player_id = str(player.get("id", ""))
    except Exception as exc:
        search_errors.append(f"direct: {exc}")
        log.warning("Direct Transfermarkt search failed: %s", exc)

    # Strategy B – hosted API
    if not player_id:
        try:
            candidates = _search_players_api(player_name)
            if candidates:
                player = _best_match(candidates, player_name, player_club)
                if player:
                    player_id = str(player.get("id", ""))
        except Exception as exc:
            search_errors.append(f"api: {exc}")
            log.warning("Transfermarkt API search fallback failed: %s", exc)

    if not player_id:
        if search_errors:
            raise TmBlockedError(
                "Could not find player on Transfermarkt. "
                f"Errors: {'; '.join(search_errors)}"
            )
        return empty  # player simply not found

    tm_url = f"{_TM_BASE}/-/profil/spieler/{player_id}"
    empty["tm_url"] = tm_url

    # ── Step 2: fetch stats ──────────────────────────────────────────────
    # Strategy A – direct scraping
    try:
        stats = _fetch_stats_scrape(player_id, target_season)
        stats["tm_url"] = tm_url
        return stats
    except Exception as exc:
        log.warning("Direct stats scraping failed: %s", exc)

    # Strategy B – hosted API
    try:
        stats = _fetch_stats_api(player_id, target_season)
        stats["tm_url"] = tm_url
        return stats
    except Exception as exc:
        log.warning("API stats fallback failed: %s", exc)

    # Both failed for stats – still return the URL so the user has a link
    empty["tm_url"] = tm_url
    return empty
