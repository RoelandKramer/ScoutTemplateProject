"""Transfermarkt scraping for player season & career statistics.

Uses Playwright with stealth to bypass bot detection on Streamlit Cloud.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass

from bs4 import BeautifulSoup

_BASE = "https://www.transfermarkt.com"
_DELAY = 1.5  # polite delay between requests

_BROWSER_READY = False


class TmBlockedError(Exception):
    """Raised when Transfermarkt blocks our requests."""
    pass


def _ensure_browser() -> None:
    """Install Playwright Chromium browser binary if not already present.

    On Streamlit Cloud the pip install only gets the Python package;
    the actual browser binary must be downloaded separately.
    This is idempotent — fast no-op when already installed.
    """
    global _BROWSER_READY
    if _BROWSER_READY:
        return

    try:
        subprocess.run(
            ["playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise TmBlockedError(
            "Playwright CLI not found. Run: pip install playwright"
        )
    except subprocess.TimeoutExpired:
        raise TmBlockedError("Timed out installing Chromium browser.")
    except subprocess.CalledProcessError as exc:
        raise TmBlockedError(f"Failed to install Chromium: {exc.stderr}")

    _BROWSER_READY = True


@dataclass
class TmPlayer:
    name: str
    url: str  # profile URL path like /player-name/profil/spieler/12345
    club: str
    tm_id: int


# ─── Browser-based fetching ────────────────────────────────────────────────

def _fetch_page(url: str) -> BeautifulSoup:
    """Fetch a page using a headless Playwright browser with stealth.

    This bypasses Transfermarkt's bot detection (TLS fingerprinting,
    Cloudflare challenges) which blocks plain requests from cloud servers.
    """
    _ensure_browser()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise TmBlockedError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )

    try:
        from playwright_stealth import stealth_sync
    except ImportError:
        stealth_sync = None  # proceed without stealth if not available

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1920, "height": 1080},
                java_script_enabled=True,
            )
            # Remove the webdriver flag that bots are detected by
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            if stealth_sync is not None:
                stealth_sync(page)

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for JS rendering + Cloudflare challenge resolution
            page.wait_for_timeout(3000)

            html = page.content()
            title = page.title()
            browser.close()

            # Check for explicit block pages (Cloudflare, WAF)
            block_signals = [
                "<title>Access Denied</title>",
                "<title>403 Forbidden</title>",
                "<title>Just a moment...</title>",  # Cloudflare challenge
                "Attention Required! | Cloudflare",
            ]
            html_lower = html.lower()
            for signal in block_signals:
                if signal.lower() in html_lower:
                    raise TmBlockedError(
                        f"Transfermarkt blocked the request (page title: {title!r})."
                    )

            # If we got a nearly empty page, something went wrong
            if len(html) < 1000:
                raise TmBlockedError(
                    f"Page too small ({len(html)} bytes), likely blocked. "
                    f"Title: {title!r}"
                )

            return BeautifulSoup(html, "lxml")
    except TmBlockedError:
        raise
    except Exception as exc:
        raise TmBlockedError(f"Browser fetch failed: {exc}")


# ─── Search ─────────────────────────────────────────────────────────────────

def search_player(name: str) -> list[TmPlayer]:
    """Search Transfermarkt for players matching *name*."""
    query = name.replace(" ", "+")
    url = f"{_BASE}/schnellsuche/ergebnis/schnellsuche?query={query}&x=0&y=0"
    soup = _fetch_page(url)

    results: list[TmPlayer] = []
    for table in soup.select("table.items"):
        for row in table.select("tbody tr"):
            link = row.select_one("td.hauptlink a")
            if not link or "/profil/spieler/" not in (link.get("href") or ""):
                continue
            href = link["href"]
            pname = link.get_text(strip=True)
            m = re.search(r"/spieler/(\d+)", href)
            if not m:
                continue
            tm_id = int(m.group(1))
            club_name = ""
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
    stats_url = profile_url.replace("/profil/spieler/", "/leistungsdatendetails/spieler/")
    full_url = f"{_BASE}{stats_url}"
    time.sleep(_DELAY)
    return _fetch_page(full_url)


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

    candidates = search_player(player_name)
    if not candidates:
        return result

    player = _best_match(candidates, player_name, player_club)
    if not player:
        return result

    result["tm_url"] = f"{_BASE}{player.url}"

    m = re.match(r"(\d{4})/(\d{4})", target_season_label)
    if m:
        season_short = f"{m.group(1)[2:]}/{m.group(2)[2:]}"
    else:
        season_short = "25/26"

    try:
        soup = _fetch_stats_page(player.url)
    except Exception:
        return result

    _parse_detailed_stats(soup, result, season_short)
    return result


def _parse_detailed_stats(soup: BeautifulSoup, result: dict, season_short: str) -> None:
    """Parse the detailed performance data table on Transfermarkt."""
    season_matches = 0
    season_goals = 0
    season_assists = 0
    season_minutes = 0

    career_matches = 0
    career_goals = 0
    career_assists = 0
    career_minutes = 0

    tables = soup.select("div.responsive-table table.items, table.items")
    if not tables:
        return

    for table in tables:
        tfoot = table.select_one("tfoot")
        if tfoot:
            tds = tfoot.select("td")
            numeric_cells = []
            for td in tds:
                text = td.get_text(strip=True).replace(".", "").replace("'", "").replace("-", "0")
                if text.isdigit():
                    numeric_cells.append(int(text))

            if len(numeric_cells) >= 3:
                career_matches = numeric_cells[0]
                career_goals = numeric_cells[1]
                career_assists = numeric_cells[2]
            if len(numeric_cells) >= 7:
                career_minutes = numeric_cells[6]
            elif len(numeric_cells) >= 4:
                career_minutes = numeric_cells[-1]

        rows = table.select("tbody tr:not(.bg_blau_20)")
        current_season = ""
        for row in rows:
            if "bg_blau_20" in (row.get("class") or []):
                continue

            tds = row.select("td")
            if len(tds) < 4:
                continue

            first_text = tds[0].get_text(strip=True)
            if re.match(r"\d{2}/\d{2}", first_text):
                current_season = first_text

            if current_season == season_short:
                nums = []
                for td in tds[1:]:
                    text = td.get_text(strip=True).replace(".", "").replace("'", "")
                    if text == "-":
                        nums.append(0)
                    elif text.isdigit():
                        nums.append(int(text))

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
