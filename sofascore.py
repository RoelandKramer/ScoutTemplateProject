"""Sofascore scraping helpers used to compute player availability.

Availability = (matches the player was in the team's matchday squad)
             / (total finished team matches in the season)

Notes:
- This is intentionally not branded in the UI. Internally we resolve a player
  by name (with optional club hint), look up their current team, then count
  the team's finished matches and the player's appearances over the same
  span. The Sofascore "events/last/{page}" endpoints return matches in
  reverse chronological order; the player's events list contains every match
  they were part of the matchday squad (starter or unused sub).
- All network calls are best-effort: failures and rate-limits return None.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


_BASES = ("https://api.sofascore.com", "https://www.sofascore.com")
_TIMEOUT = 20.0
_RETRIES = 4
_PAGE_LIMIT = 6  # ~6 pages × 30 events ≈ a full season


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Referer": "https://www.sofascore.com/",
            "Origin": "https://www.sofascore.com",
        }
    )
    return s


def _get_json(path: str) -> Optional[Dict[str, Any]]:
    last: Optional[Exception] = None
    for base in _BASES:
        url = base.rstrip("/") + path
        s = _make_session()
        for attempt in range(_RETRIES):
            try:
                r = s.get(url, timeout=_TIMEOUT)
                if r.status_code == 429:
                    time.sleep(1.25 * (attempt + 1) + random.random())
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
                time.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
    return None


# ─── Player + team resolution ─────────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _search_player(name: str, club_hint: str = "") -> Optional[Dict[str, Any]]:
    """Find the best matching player. Returns the search-result dict or None."""
    if not name:
        return None
    data = _get_json(f"/api/v1/search/all?q={requests.utils.quote(name)}&page=0")
    if not data:
        return None
    results = data.get("results") or []
    players = [r for r in results if r.get("type") == "player" and r.get("entity")]
    if not players:
        return None

    target_name = _normalize(name)
    target_club = _normalize(club_hint)

    def score(item: Dict[str, Any]) -> int:
        ent = item.get("entity") or {}
        nm = _normalize(ent.get("name", ""))
        team = (ent.get("team") or {}).get("name") or ""
        team_n = _normalize(team)
        s = 0
        if nm == target_name: s += 100
        elif target_name in nm: s += 50
        if target_club and team_n:
            if team_n == target_club: s += 60
            elif target_club in team_n or team_n in target_club: s += 25
        return s

    players.sort(key=score, reverse=True)
    return players[0].get("entity")


def _get_player_full(player_id: int) -> Optional[Dict[str, Any]]:
    data = _get_json(f"/api/v1/player/{player_id}")
    if not data:
        return None
    return data.get("player") or data


def _resolve(name: str, club_hint: str = "") -> Tuple[Optional[int], Optional[int]]:
    """Return (player_id, team_id) or (None, None)."""
    hit = _search_player(name, club_hint)
    if not hit:
        return None, None
    pid = hit.get("id")
    team = hit.get("team") or {}
    tid = team.get("id")
    if not tid and pid:
        full = _get_player_full(pid)
        if full:
            tid = ((full.get("team") or {}).get("id")
                   or (full.get("currentTeam") or {}).get("id"))
    return pid, tid


# ─── Event listing (paginated) ────────────────────────────────────────────

def _list_events(kind: str, entity_id: int) -> List[Dict[str, Any]]:
    """Fetch up to _PAGE_LIMIT pages of last events for player or team."""
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for page in range(_PAGE_LIMIT):
        data = _get_json(f"/api/v1/{kind}/{entity_id}/events/last/{page}")
        if not data:
            break
        events = data.get("events") or []
        if not events:
            break
        new_count = 0
        for ev in events:
            eid = ev.get("id")
            if eid is None or eid in seen:
                continue
            seen.add(eid)
            out.append(ev)
            new_count += 1
        if new_count == 0:
            break
    return out


def _is_finished(event: Dict[str, Any]) -> bool:
    status = (event.get("status") or {}).get("type")
    return status == "finished"


def _season_window(now_ts: Optional[int] = None) -> Tuple[int, int]:
    """Return (start_ts, end_ts) for the current European football season.

    A season runs roughly Aug 1 → Jun 30. Today's date determines which one.
    """
    now = now_ts if now_ts is not None else int(time.time())
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    year = dt.year
    if dt.month >= 7:
        start_year = year
    else:
        start_year = year - 1
    start = int(datetime(start_year, 7, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(start_year + 1, 7, 1, tzinfo=timezone.utc).timestamp())
    return start, end


def _filter_season(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    s, e = _season_window()
    out = []
    for ev in events:
        ts = ev.get("startTimestamp") or 0
        if s <= ts < e and _is_finished(ev):
            out.append(ev)
    return out


# ─── Public API ───────────────────────────────────────────────────────────

def get_player_availability(
    player_name: str,
    club_hint: str = "",
) -> Dict[str, Optional[float]]:
    """Return {availability_pct, availability_in_squad, availability_total}.

    Best-effort. On any failure values default to (None, 0, 0).
    """
    out: Dict[str, Optional[float]] = {
        "availability_pct": None,
        "availability_in_squad": 0,
        "availability_total": 0,
    }
    try:
        pid, tid = _resolve(player_name, club_hint)
        if not pid or not tid:
            return out

        team_events = _filter_season(_list_events("team", tid))
        if not team_events:
            return out
        team_event_ids = {ev.get("id") for ev in team_events}

        player_events = _filter_season(_list_events("player", pid))
        in_squad = sum(1 for ev in player_events if ev.get("id") in team_event_ids)
        total = len(team_event_ids)
        if total == 0:
            return out

        pct = round(100.0 * in_squad / total, 1)
        out["availability_pct"] = pct
        out["availability_in_squad"] = in_squad
        out["availability_total"] = total
        return out
    except Exception:
        return out


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Lionel Messi"
    club = sys.argv[2] if len(sys.argv) > 2 else ""
    print(get_player_availability(name, club))
