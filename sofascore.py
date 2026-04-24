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
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


# ─── Debug log — captured per-lookup so the app can surface it ─────────────

_DEBUG: List[str] = []
_DEBUG_MAX = 80


def _dbg(msg: str) -> None:
    """Append a debug line and also print it to stderr so Railway's log
    captures it. Tail-limited to avoid unbounded growth."""
    _DEBUG.append(msg)
    if len(_DEBUG) > _DEBUG_MAX:
        del _DEBUG[: len(_DEBUG) - _DEBUG_MAX]
    print(f"[sofascore] {msg}", file=sys.stderr, flush=True)


def _dbg_reset() -> None:
    _DEBUG.clear()


def get_debug_log() -> List[str]:
    """Return a shallow copy of recent debug lines for display in the UI."""
    return list(_DEBUG)


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
                    _dbg(f"GET {path} -> 429 (retry {attempt+1})")
                    time.sleep(1.25 * (attempt + 1) + random.random())
                    continue
                if r.status_code == 404:
                    _dbg(f"GET {path} -> 404")
                    return None
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
                _dbg(f"GET {path} -> {type(e).__name__}: {str(e)[:80]}")
                time.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
    _dbg(f"GET {path} FAILED after retries ({type(last).__name__ if last else 'unknown'})")
    return None


# ─── Player + team resolution ─────────────────────────────────────────────

def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _search_player(name: str, club_hint: str = "") -> Optional[Dict[str, Any]]:
    """Find the best matching player. Returns the search-result dict or None."""
    if not name:
        _dbg("search_player: empty name")
        return None
    _dbg(f"search_player: q='{name}' club_hint='{club_hint}'")
    data = _get_json(f"/api/v1/search/all?q={requests.utils.quote(name)}&page=0")
    if not data:
        _dbg("search_player: search endpoint returned nothing")
        return None
    results = data.get("results") or []
    players = [r for r in results if r.get("type") == "player" and r.get("entity")]
    _dbg(f"search_player: {len(results)} total results, {len(players)} players")
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
    top = players[0].get("entity") or {}
    _dbg(f"search_player: picked id={top.get('id')} name='{top.get('name')}' "
         f"team='{(top.get('team') or {}).get('name')}'")
    return top


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


def _event_unique_tournament(ev: Dict[str, Any]) -> Tuple[Optional[int], str, str]:
    """Return (uniqueTournament id, uniqueTournament name, category name)."""
    t = ev.get("tournament") or {}
    ut = t.get("uniqueTournament") or {}
    cat = (t.get("category") or {}).get("name", "") or ""
    return ut.get("id"), (ut.get("name") or ""), cat


def _is_friendly(ev: Dict[str, Any]) -> bool:
    _uid, uname, cat = _event_unique_tournament(ev)
    blob = f"{uname} {cat}".lower()
    return "friendly" in blob or "friendlies" in blob


def _primary_tournament_id(events: Iterable[Dict[str, Any]]) -> Optional[int]:
    """Pick the uniqueTournament id with the most matches (excl. friendlies).

    Used to restrict a team's event list to its current main competition so
    availability and match lists don't mix league, cup, and friendly games.
    """
    from collections import Counter
    counts: Counter = Counter()
    for ev in events:
        if _is_friendly(ev):
            continue
        uid, _uname, _cat = _event_unique_tournament(ev)
        if uid:
            counts[uid] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _filter_by_tournament(
    events: Iterable[Dict[str, Any]],
    ut_id: Optional[int],
) -> List[Dict[str, Any]]:
    if not ut_id:
        return [ev for ev in events if not _is_friendly(ev)]
    out = []
    for ev in events:
        uid, _uname, _cat = _event_unique_tournament(ev)
        if uid == ut_id:
            out.append(ev)
    return out


# ─── Public API ───────────────────────────────────────────────────────────

def _event_match_dict(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Sofascore event into a slim match dict for the UI.

    Returned keys:
      id          — Sofascore event id (used for de-dupe)
      ts          — startTimestamp (int)
      date        — formatted as MM-DD-YYYY (American style, requested by user)
      home        — home team name
      away        — away team name
      label       — 'MM-DD-YYYY Home - Away'
    """
    from datetime import datetime, timezone
    ts = int(ev.get("startTimestamp") or 0)
    date_str = ""
    if ts:
        try:
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d-%Y")
        except Exception:
            date_str = ""
    home = ((ev.get("homeTeam") or {}).get("name") or "").strip()
    away = ((ev.get("awayTeam") or {}).get("name") or "").strip()
    label = f"{date_str} {home} - {away}".strip()
    return {
        "id": ev.get("id"),
        "ts": ts,
        "date": date_str,
        "home": home,
        "away": away,
        "label": label,
    }


def get_player_availability(
    player_name: str,
    club_hint: str = "",
) -> Dict[str, Any]:
    """Return availability + the player's in-squad matches this season.

    Returned keys:
      availability_pct, availability_in_squad, availability_total
      matches  — list[dict] of in-squad matches (see _event_match_dict),
                 newest first

    Best-effort. On any failure values default to (None, 0, 0, []).
    """
    out: Dict[str, Any] = {
        "availability_pct": None,
        "availability_in_squad": 0,
        "availability_total": 0,
        "matches": [],
    }
    try:
        pid, tid = _resolve(player_name, club_hint)
        if not pid or not tid:
            return out

        team_events_all = _filter_season(_list_events("team", tid))
        if not team_events_all:
            return out

        # Restrict both team and player events to the team's primary
        # competition this season (typically the league) so cup and
        # friendly matches don't skew availability.
        primary_ut = _primary_tournament_id(team_events_all)
        team_events = _filter_by_tournament(team_events_all, primary_ut)
        if not team_events:
            return out
        team_event_ids = {ev.get("id") for ev in team_events}

        player_events_all = _filter_season(_list_events("player", pid))
        player_events = _filter_by_tournament(player_events_all, primary_ut)
        in_squad_events = [ev for ev in player_events if ev.get("id") in team_event_ids]
        in_squad = len(in_squad_events)
        total = len(team_event_ids)
        if total == 0:
            return out

        pct = round(100.0 * in_squad / total, 1)
        # Newest first.
        in_squad_events.sort(key=lambda e: int(e.get("startTimestamp") or 0), reverse=True)
        out["availability_pct"] = pct
        out["availability_in_squad"] = in_squad
        out["availability_total"] = total
        out["matches"] = [_event_match_dict(ev) for ev in in_squad_events]
        return out
    except Exception:
        return out


# ─── Team match list (used when player isn't in our physical-data universe) ─

# Tokens that almost every football club shares — they should not count as
# evidence two clubs are the same. ``AFC Amsterdam`` and ``AFC Ajax`` only
# share the generic ``AFC`` prefix; the distinctive tokens (``Amsterdam`` vs
# ``Ajax``) must overlap before we consider them a match.
_GENERIC_CLUB_TOKENS = {
    "fc", "afc", "sc", "sv", "vv", "cv", "ac", "as", "ss", "us",
    "cf", "kf", "kv", "kvc", "ks", "sk", "rs", "rfc", "rcd", "real",
    "club", "atletico", "athletic", "deportivo", "olimpico",
    "sporting", "the", "1.", "1.fc", "fk", "vfb", "vfl", "ssv",
    "ssc", "calcio", "united", "city", "town", "rovers", "wanderers",
    "sportif", "olympique",
}


def _distinctive_tokens(s: str) -> set[str]:
    return set(_normalize(s).split()) - _GENERIC_CLUB_TOKENS


def _search_team(club_hint: str) -> Optional[Dict[str, Any]]:
    """Find the Sofascore team best matching ``club_hint``.

    Uses a strict-ish Jaccard over distinctive (non-generic) tokens so
    e.g. ``AFC Amsterdam`` doesn't accidentally match ``AFC Ajax`` just
    because they share the ``AFC`` prefix. Returns None when no candidate
    has a meaningful overlap.
    """
    if not club_hint:
        return None
    data = _get_json(f"/api/v1/search/all?q={requests.utils.quote(club_hint)}&page=0")
    if not data:
        return None
    results = data.get("results") or []
    teams = [r for r in results if r.get("type") == "team" and r.get("entity")]
    if not teams:
        return None

    target_norm = _normalize(club_hint)
    target_tokens = _distinctive_tokens(club_hint)

    def score(item: Dict[str, Any]) -> int:
        nm = (item.get("entity") or {}).get("name", "") or ""
        nm_norm = _normalize(nm)
        if nm_norm == target_norm:
            return 1000
        nm_tokens = _distinctive_tokens(nm)
        if not target_tokens or not nm_tokens:
            return 0
        overlap = target_tokens & nm_tokens
        if not overlap:
            return 0
        union = target_tokens | nm_tokens
        return int(round(100.0 * len(overlap) / len(union)))

    scored = sorted(teams, key=score, reverse=True)
    top = scored[0]
    if score(top) <= 0:
        return None
    return top.get("entity")


def get_team_matches(club_hint: str) -> List[Dict[str, Any]]:
    """Return this season's matches for the team matching ``club_hint``.

    Restricted to the team's primary competition (skips friendlies and
    cup/unrelated competitions). Newest first. Used as a fallback in the
    scouting-session UI when a player isn't covered by our physical-data
    CSV and the KKD/Eredivisie match list isn't available.
    """
    try:
        team = _search_team(club_hint)
        if not team:
            return []
        tid = team.get("id")
        if not tid:
            return []
        events_all = _filter_season(_list_events("team", tid))
        if not events_all:
            return []
        primary_ut = _primary_tournament_id(events_all)
        events = _filter_by_tournament(events_all, primary_ut)
        events.sort(key=lambda e: int(e.get("startTimestamp") or 0), reverse=True)
        return [_event_match_dict(ev) for ev in events]
    except Exception:
        return []


# ─── Season + career stats (used when Transfermarkt is unreachable) ──────

def _current_season_year_label() -> str:
    """Return Sofascore's 'year' string for the current European season, e.g. '25/26'."""
    from datetime import datetime, timezone
    dt = datetime.now(tz=timezone.utc)
    start_year = dt.year if dt.month >= 7 else dt.year - 1
    return f"{str(start_year)[2:]}/{str(start_year + 1)[2:]}"


def _count_from_events(pid: int) -> Dict[str, int]:
    """Fallback: aggregate match counts from the player's events list when
    Sofascore's per-tournament statistics endpoint is empty (common for
    smaller leagues like the Eerste Divisie). Returns just the match
    counts — goals / assists / minutes stay 0 in this fallback.
    """
    counts = {"season_matches": 0, "career_matches": 0}
    all_events = _list_events("player", pid)
    if not all_events:
        return counts
    finished = [ev for ev in all_events if _is_finished(ev) and not _is_friendly(ev)]
    counts["career_matches"] = len(finished)
    counts["season_matches"] = len(_filter_season(finished))
    return counts


def get_player_stats(
    player_name: str,
    club_hint: str = "",
) -> Dict[str, Any]:
    """Return season + career totals from Sofascore.

    The "career" totals sum every (tournament, season) pair listed — this
    **includes cup competitions and league**, per user request. The "season"
    totals sum tournaments for the current European season (`YY/YY+1`).

    If the per-tournament statistics endpoint returns nothing useful (which
    happens for smaller leagues), we fall back to counting the player's
    finished events directly so at least season_matches / career_matches
    are populated. All zero on total failure.
    """
    _dbg_reset()
    _dbg(f"get_player_stats: name='{player_name}' club_hint='{club_hint}'")
    out: Dict[str, Any] = {
        "season_matches": 0, "season_goals": 0,
        "season_assists": 0, "season_minutes": 0,
        "career_matches": 0, "career_goals": 0,
        "career_assists": 0, "career_minutes": 0,
    }
    try:
        pid, _tid = _resolve(player_name, club_hint)
        _dbg(f"resolved pid={pid} tid={_tid}")
        if not pid:
            _dbg("abort: no player id")
            return out

        data = _get_json(f"/api/v1/player/{pid}/statistics/seasons")
        _dbg(f"statistics/seasons: {'null' if data is None else 'keys='+str(list(data.keys())[:6])}")

        cur_year = _current_season_year_label()
        _dbg(f"current season year label: {cur_year}")
        tournament_entries = (data or {}).get("uniqueTournamentSeasons") or []
        _dbg(f"uniqueTournamentSeasons: {len(tournament_entries)} tournaments")
        for entry in tournament_entries:
            ut = (entry.get("uniqueTournament") or {}).get("id")
            if not ut:
                continue
            # Every season pair (including cup tournaments) counts toward career;
            # the matching-year pair counts toward season.
            for season in entry.get("seasons") or []:
                sid = season.get("id")
                if not sid:
                    continue
                stats = _get_json(
                    f"/api/v1/player/{pid}/unique-tournament/{ut}"
                    f"/season/{sid}/statistics/overall"
                )
                if not stats:
                    continue
                s = stats.get("statistics") or {}
                apps = int(s.get("appearances") or 0)
                goals = int(s.get("goals") or 0)
                assists = int(s.get("assists") or 0)
                mins = int(s.get("minutesPlayed") or 0)

                out["career_matches"] += apps
                out["career_goals"] += goals
                out["career_assists"] += assists
                out["career_minutes"] += mins

                if str(season.get("year") or "") == cur_year:
                    out["season_matches"] += apps
                    out["season_goals"] += goals
                    out["season_assists"] += assists
                    out["season_minutes"] += mins

        # Fallback when the detailed stats endpoint returns nothing usable —
        # keeps the Eerste Divisie / KKD case from showing a blank card.
        if out["career_matches"] == 0 and out["season_matches"] == 0:
            _dbg("career_matches and season_matches both 0 → falling back to event counts")
            fallback = _count_from_events(pid)
            _dbg(f"fallback event counts: season={fallback['season_matches']} "
                 f"career={fallback['career_matches']}")
            out["career_matches"] = fallback["career_matches"]
            out["season_matches"] = fallback["season_matches"]

        _dbg(f"final: season_m={out['season_matches']} season_g={out['season_goals']} "
             f"career_m={out['career_matches']} career_g={out['career_goals']}")
        return out
    except Exception as exc:
        _dbg(f"get_player_stats exception: {type(exc).__name__}: {str(exc)[:120]}")
        return out


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "Lionel Messi"
    club = sys.argv[2] if len(sys.argv) > 2 else ""
    print(get_player_availability(name, club))
    print(get_player_stats(name, club))
