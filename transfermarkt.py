"""Transfermarkt scraping for player season & career statistics."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
_BASE = "https://www.transfermarkt.com"
_DELAY = 1.2  # polite delay between requests


@dataclass
class TmPlayer:
    name: str
    url: str  # profile URL path like /player-name/profil/spieler/12345
    club: str
    tm_id: int


# ─── Search ─────────────────────────────────────────────────────────────────

def search_player(name: str) -> list[TmPlayer]:
    """Search Transfermarkt for players matching *name*."""
    url = f"{_BASE}/schnellsuche/ergebnis/schnellsuche"
    params = {"query": name, "x": 0, "y": 0}
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results: list[TmPlayer] = []
    # Player result rows in search results table
    for table in soup.select("table.items"):
        for row in table.select("tbody tr"):
            link = row.select_one("td.hauptlink a")
            if not link or "/profil/spieler/" not in (link.get("href") or ""):
                continue
            href = link["href"]
            pname = link.get_text(strip=True)
            # Extract TM id from URL
            m = re.search(r"/spieler/(\d+)", href)
            if not m:
                continue
            tm_id = int(m.group(1))
            # Club name
            club_td = row.select("td.zentriert")
            club_el = row.select_one("td:nth-of-type(4) a, td:nth-of-type(5) a, img[alt]")
            club_name = ""
            # Try to get club from row
            for img in row.select("img"):
                alt = img.get("alt", "")
                if alt and alt != pname and "flag" not in (img.get("class") or [""]):
                    club_name = alt
            results.append(TmPlayer(name=pname, url=href, club=club_name, tm_id=tm_id))
    return results


def _best_match(candidates: list[TmPlayer], target_name: str, target_club: str = "") -> TmPlayer | None:
    """Pick the best matching player from search results."""
    if not candidates:
        return None

    target_lower = target_name.lower().strip()
    target_club_lower = target_club.lower().strip()

    def _score(p: TmPlayer) -> float:
        s = 0.0
        name_l = p.name.lower()
        if name_l == target_lower:
            s += 10
        elif target_lower in name_l or name_l in target_lower:
            s += 5
        else:
            # Word overlap
            target_words = set(target_lower.split())
            name_words = set(name_l.split())
            overlap = len(target_words & name_words)
            s += overlap * 2
        if target_club_lower and target_club_lower in p.club.lower():
            s += 3
        return s

    ranked = sorted(candidates, key=_score, reverse=True)
    if _score(ranked[0]) >= 2:
        return ranked[0]
    return ranked[0] if len(ranked) == 1 else None


# ─── Stats extraction ───────────────────────────────────────────────────────

def _parse_int(text: str) -> int:
    """Parse a number from text like '1.234' or '12' or '-'."""
    text = text.strip().replace(".", "").replace(",", "")
    if not text or text == "-":
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def _fetch_stats_page(profile_url: str) -> BeautifulSoup:
    """Fetch the player's detailed stats page."""
    # Convert profile URL to stats URL
    # /player-name/profil/spieler/12345 -> /player-name/leistungsdatendetails/spieler/12345
    stats_url = profile_url.replace("/profil/spieler/", "/leistungsdatendetails/spieler/")
    full_url = f"{_BASE}{stats_url}"
    time.sleep(_DELAY)
    resp = requests.get(full_url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def _extract_season_stats(soup: BeautifulSoup, target_season: str = "24/25") -> dict[str, int]:
    """Extract stats for a specific season from the detailed stats page.

    target_season should be in format "24/25" for 2024/2025 season.
    """
    stats = {"matches": 0, "minutes": 0, "goals": 0, "assists": 0}

    # Find all competition rows for the target season
    # The stats page has tables grouped by season
    for table in soup.select("table.items"):
        rows = table.select("tbody tr")
        for row in rows:
            tds = row.select("td")
            if len(tds) < 5:
                continue

            # Check if this row's season matches
            season_el = row.select_one("td.zentriert a[href*='saison_id']")
            if not season_el:
                # Try the first cell
                first_td = tds[0].get_text(strip=True)
                if target_season not in first_td:
                    continue
            else:
                if target_season not in season_el.get_text(strip=True):
                    continue

            # Find the stats columns — look for numeric values
            # Typical order: competition, appearances, goals, assists, minutes
            # But layout varies. Parse all numeric cells.
            appearances = 0
            goals = 0
            assists = 0
            minutes_played = 0

            numeric_tds = [td for td in tds if td.get_text(strip=True).replace(".", "").replace("-", "").replace("'", "").isdigit() or td.get_text(strip=True) == "-"]

            # Try to find specific columns by position
            for td in tds:
                text = td.get_text(strip=True)
                # Minutes often have a ' suffix
                if "'" in text:
                    minutes_played += _parse_int(text.replace("'", ""))

            # Use footer/total row approach — look for class or total markers
            # For now, sum up all competition rows

    # Alternative: use the compact stats boxes on the page
    # Look for the stats summary section
    for box in soup.select(".data-header__details, .data-header__info-box"):
        text = box.get_text(" ", strip=True)
        # This sometimes contains "X goals" etc.

    return stats


def fetch_player_stats(player_name: str, player_club: str = "", target_season_label: str = "2025/2026") -> dict:
    """Fetch season and career stats for a player from Transfermarkt.

    Returns a dict with keys:
        season_matches, season_minutes, season_goals, season_assists,
        career_matches, career_minutes, career_goals, career_assists,
        tm_url (the Transfermarkt profile URL)
    """
    result = {
        "season_matches": 0, "season_minutes": 0,
        "season_goals": 0, "season_assists": 0,
        "career_matches": 0, "career_minutes": 0,
        "career_goals": 0, "career_assists": 0,
        "tm_url": "",
    }

    # Search for the player
    candidates = search_player(player_name)
    if not candidates:
        return result

    player = _best_match(candidates, player_name, player_club)
    if not player:
        return result

    result["tm_url"] = f"{_BASE}{player.url}"

    # Convert season label "2025/2026" -> "25/26" for matching
    m = re.match(r"(\d{4})/(\d{4})", target_season_label)
    if m:
        season_short = f"{m.group(1)[2:]}/{m.group(2)[2:]}"
    else:
        season_short = "25/26"

    # Fetch the stats page
    try:
        soup = _fetch_stats_page(player.url)
    except Exception:
        return result

    # Parse the detailed stats table
    # Transfermarkt detailed stats page has rows per competition per season
    # We need to find all rows for the target season and sum them up
    _parse_detailed_stats(soup, result, season_short)

    return result


def _parse_detailed_stats(soup: BeautifulSoup, result: dict, season_short: str) -> None:
    """Parse the detailed performance data table on Transfermarkt."""

    # The page contains a responsive table with class "items"
    # Each row has: season | competition | matchday | squad_number | appearances | goals | assists | ...
    # There are also total/footer rows

    # Strategy: find all data rows grouped by season, sum per-competition lines
    season_matches = 0
    season_goals = 0
    season_assists = 0
    season_minutes = 0

    career_matches = 0
    career_goals = 0
    career_assists = 0
    career_minutes = 0

    found_season = False

    # Look for the main stats table
    tables = soup.select("div.responsive-table table.items, table.items")
    if not tables:
        return

    for table in tables:
        # Check for tfoot (totals row)
        tfoot = table.select_one("tfoot")
        if tfoot:
            # Career totals from the footer
            tds = tfoot.select("td")
            for i, td in enumerate(tds):
                text = td.get_text(strip=True)
                # The footer typically has: label | appearances | goals | assists | ... | minutes
                if i == 1 or (td.get("class") and "zentriert" in td.get("class", [])):
                    pass  # Skip non-numeric

            # Parse footer cells more carefully
            numeric_cells = []
            for td in tds:
                text = td.get_text(strip=True).replace(".", "").replace("'", "").replace("-", "0")
                if text.isdigit():
                    numeric_cells.append(int(text))

            # Typical order in footer: appearances, goals, assists, yellow, 2nd yellow, red, minutes
            if len(numeric_cells) >= 3:
                career_matches = numeric_cells[0]
                career_goals = numeric_cells[1]
                career_assists = numeric_cells[2]
            if len(numeric_cells) >= 7:
                career_minutes = numeric_cells[6]
            elif len(numeric_cells) >= 4:
                career_minutes = numeric_cells[-1]

        # Parse individual rows for the target season
        rows = table.select("tbody tr:not(.bg_blau_20)")
        current_season = ""
        for row in rows:
            # Skip separator / header rows
            if "bg_blau_20" in (row.get("class") or []):
                continue

            tds = row.select("td")
            if len(tds) < 4:
                continue

            # First column often contains the season or is empty (continuation)
            first_text = tds[0].get_text(strip=True)
            if re.match(r"\d{2}/\d{2}", first_text):
                current_season = first_text

            if current_season == season_short:
                found_season = True
                # Extract numeric columns
                nums = []
                for td in tds[1:]:
                    text = td.get_text(strip=True).replace(".", "").replace("'", "")
                    if text == "-":
                        nums.append(0)
                    elif text.isdigit():
                        nums.append(int(text))

                # Typically: competition | appearances | goals | assists | ... | minutes
                if len(nums) >= 3:
                    season_matches += nums[0]
                    season_goals += nums[1]
                    season_assists += nums[2]
                if len(nums) >= 7:
                    season_minutes += nums[6]
                elif len(nums) >= 4:
                    season_minutes += nums[-1]

    result["season_matches"] = season_matches
    result["season_minutes"] = season_minutes
    result["season_goals"] = season_goals
    result["season_assists"] = season_assists
    result["career_matches"] = career_matches
    result["career_minutes"] = career_minutes
    result["career_goals"] = career_goals
    result["career_assists"] = career_assists
