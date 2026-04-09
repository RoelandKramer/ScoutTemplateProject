"""SciSports API integration for player data retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

API_BASE = "https://api-recruitment.scisports.app/api"
TOKEN_URL = "https://identity.scisports.app/connect/token"
SEARCH_LIMIT = 50
TARGET_SEASON_LABEL = "2025/2026"
SEASON_RE = re.compile(r"\b(20\d{2})\s*[/\-]\s*(\d{2}|20\d{2})\b")


POSITION_ABBREV: Dict[str, str] = {
    "Goalkeeper": "GK",
    "Right Back": "RB",
    "Left Back": "LB",
    "Centre Back": "CB",
    "Defensive Midfield": "DM",
    "Centre Midfield": "CM",
    "Attacking Midfield": "AM",
    "Right Wing": "RW", "Left Wing": "LW",
    "Centre Forward": "ST", "Striker": "ST",
}


# Map SciSports positions to our template position names
SCISPORTS_TO_TEMPLATE: Dict[str, str] = {
    "Goalkeeper": "Goalkeeper",
    "RightBack": "Wingback", "RightFullback": "Wingback", "LeftBack": "Wingback",
    "Right Back": "Wingback", "Left Back": "Wingback",
    "CentreBack": "Centerback", "Centre back": "Centerback", "Centre Back": "Centerback",
    "DefensiveMidfield": "Deep Lying Playmaker", "Defensive midfield": "Deep Lying Playmaker", "Defensive Midfield": "Deep Lying Playmaker",
    "CentreMidfield": "Box-to-Box Midfielder", "Centre midfield": "Box-to-Box Midfielder", "Centre Midfield": "Box-to-Box Midfielder",
    "AttackingMidfield": "Scoring 10", "Attacking midfield": "Scoring 10", "Attacking Midfield": "Scoring 10",
    "RightWing": "Dribbling Winger", "Right Wing": "Dribbling Winger",
    "LeftWing": "Dribbling Winger", "Left Wing": "Dribbling Winger",
    "CentreForward": "Finisher", "Centre forward": "Finisher", "Centre Forward": "Finisher",
    "Striker": "Finisher",
}


@dataclass(frozen=True)
class PlayerOption:
    player_id: int
    name: str
    age: Optional[int]
    position: str
    club: str
    league: str

    def label(self) -> str:
        age_s = "?" if self.age is None else str(self.age)
        return f"{self.name} — {age_s} — {self.position or '?'} — {self.club or '?'} ({self.league or '?'})"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _as_text(v: Any) -> str:
    return "" if v is None else str(v)

def _fmt_int(v: Any) -> str:
    try:
        return "" if v is None else str(int(v))
    except Exception:
        return ""

def _parse_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            return value

def _fmt_height(cm: Any) -> str:
    try:
        if cm is None: return ""
        m = float(cm) / 100.0
        return f"{m:.2f} M" if m > 0 else ""
    except Exception:
        return ""

def _fmt_money(value: Any) -> str:
    try:
        if value is None: return ""
        v = float(value)
        if abs(v) >= 1_000_000: return f"€ {v/1_000_000:.2f}M"
        if abs(v) >= 1_000: return f"€ {v/1_000:.0f}K"
        return f"€ {v:.0f}"
    except Exception:
        return ""

def _first_position(info: dict) -> str:
    positions = info.get("positions") or []
    return _as_text(positions[0]) if isinstance(positions, list) and positions else ""

def _position_abbrev(pos: str) -> str:
    return POSITION_ABBREV.get((pos or "").strip(), pos)

def normalize_season_label(name: str) -> str:
    if not name: return ""
    m = SEASON_RE.search(str(name))
    if not m: return ""
    y1 = int(m.group(1))
    y2_raw = m.group(2)
    y2 = (y1 // 100) * 100 + int(y2_raw) if len(y2_raw) == 2 else int(y2_raw)
    if y2 < y1: y2 += 100
    return f"{y1}/{y2}"

def _extract_int(d: dict, *paths: str) -> int:
    for p in paths:
        cur = d
        ok = True
        for part in p.split("."):
            if not isinstance(cur, dict) or part not in cur:
                ok = False; break
            cur = cur[part]
        if ok and cur is not None:
            try: return int(round(float(cur)))
            except Exception: pass
    return 0


# ─── Auth ────────────────────────────────────────────────────────────────────

def require_secrets() -> Dict[str, str]:
    """Read SciSports credentials from Streamlit secrets.

    Supports two layouts:
      1. [scisports] section with keys: username, password, client_id, client_secret, scope
      2. Flat top-level keys prefixed SCISPORTS_  (legacy)
    """
    # Try [scisports] section first
    sec = st.secrets.get("scisports", None)
    if sec:
        required = ["username", "password", "client_id", "client_secret"]
        if all(sec.get(k) for k in required):
            return {
                "username": sec["username"],
                "password": sec["password"],
                "client_id": sec["client_id"],
                "client_secret": sec["client_secret"],
                "scope": sec.get("scope", "api recruitment"),
            }
    # Fallback 1: flat top-level keys (username, password, client_id, client_secret)
    flat_keys = ["username", "password", "client_id", "client_secret"]
    if all(st.secrets.get(k) for k in flat_keys):
        return {
            "username": st.secrets["username"],
            "password": st.secrets["password"],
            "client_id": st.secrets["client_id"],
            "client_secret": st.secrets["client_secret"],
            "scope": st.secrets.get("scope", "api recruitment"),
        }
    # Fallback 2: SCISPORTS_ prefixed keys (legacy)
    prefixed = ["SCISPORTS_USERNAME", "SCISPORTS_PASSWORD", "SCISPORTS_CLIENT_ID", "SCISPORTS_CLIENT_SECRET"]
    if all(st.secrets.get(k) for k in prefixed):
        return {
            "username": st.secrets["SCISPORTS_USERNAME"],
            "password": st.secrets["SCISPORTS_PASSWORD"],
            "client_id": st.secrets["SCISPORTS_CLIENT_ID"],
            "client_secret": st.secrets["SCISPORTS_CLIENT_SECRET"],
            "scope": st.secrets.get("SCISPORTS_SCOPE", "api recruitment"),
        }
    return {}


def get_token() -> str:
    creds = require_secrets()
    if not creds:
        raise RuntimeError("SciSports secrets not configured")
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "password", **creds,
    }, timeout=30)
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in response")
    return token


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


# ─── API calls ───────────────────────────────────────────────────────────────

def _fetch_all(token: str, path: str, params: dict, page_limit=200, hard_cap=50000) -> list[dict]:
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    out, offset = [], int(params.get("offset", 0))
    limit = min(max(int(params.get("limit", page_limit)), 1), page_limit)
    while True:
        p = {**params, "offset": offset, "limit": limit}
        resp = s.get(f"{API_BASE}{path}", headers=_auth_headers(token), params=p, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("items") or []
        if not isinstance(items, list): break
        out.extend(it for it in items if isinstance(it, dict))
        total = payload.get("total")
        if (isinstance(total, int) and len(out) >= total) or not items or len(out) >= hard_cap:
            break
        offset += limit
    return out


@st.cache_data(show_spinner=False, ttl=60*15)
def search_players(token: str, query: str) -> tuple[int, list[PlayerOption]]:
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    params: dict = {"offset": 0, "limit": SEARCH_LIMIT}
    if query.strip():
        params["searchText"] = query.strip()
    resp = s.get(f"{API_BASE}/v2/players", headers=_auth_headers(token), params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    total = int(payload.get("total", 0))
    options = []
    for it in payload.get("items") or []:
        info = it.get("info") or {}
        team = it.get("team") or {}
        league = it.get("league") or {}
        pid = info.get("id")
        if pid is None: continue
        options.append(PlayerOption(
            player_id=int(pid),
            name=_as_text(info.get("name") or info.get("footballName") or ""),
            age=info.get("age"),
            position=_position_abbrev(_first_position(info)),
            club=_as_text(team.get("name") or ""),
            league=_as_text(league.get("name") or ""),
        ))
    return total, options


def get_player(token: str, player_id: int) -> dict:
    resp = requests.get(f"{API_BASE}/v2/players/{player_id}", headers=_auth_headers(token), timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_transfer_fee(token: str, player_id: int) -> dict | None:
    resp = requests.get(f"{API_BASE}/v2/metrics/players/transfer-fees",
        headers=_auth_headers(token),
        params={"offset": 0, "limit": 1, "playerIds": player_id, "latestTransferFee": "true"},
        timeout=30)
    resp.raise_for_status()
    items = resp.json().get("items") or []
    return items[0] if items else None


@st.cache_data(show_spinner=False, ttl=3600)
def get_seasons(token: str, player_id: int) -> list[dict]:
    return _fetch_all(token, "/v2/seasons", {"offset": 0, "limit": 200, "playerIds": player_id})


def _season_ids_for(seasons: list[dict], label: str) -> list[int]:
    target = normalize_season_label(label)
    return sorted({it["id"] for it in seasons if isinstance(it.get("id"), int)
                   and normalize_season_label(_as_text(it.get("name"))) == target})


def _aggregate_stats(items: list[dict]) -> dict[str, int]:
    if not items:
        return {"matches": 0, "minutes": 0, "goals": 0, "assists": 0}
    # Try total row first
    for it in items:
        comp = it.get("competition") or it.get("competitionGroup") or it.get("league") or {}
        name = (_as_text(comp.get("name")) if isinstance(comp, dict) else "").strip().lower()
        if name in ("total", "overall", "all", "all competitions"):
            return {
                "matches": _extract_int(it, "stats.matchesPlayed", "stats.matches"),
                "minutes": _extract_int(it, "stats.minutesPlayed", "stats.minutes"),
                "goals": _extract_int(it, "stats.goal", "stats.goals"),
                "assists": _extract_int(it, "stats.assist", "stats.assists"),
            }
    # Sum per competition
    totals = {"matches": 0, "minutes": 0, "goals": 0, "assists": 0}
    for it in items:
        totals["matches"] += _extract_int(it, "stats.matchesPlayed", "stats.matches")
        totals["minutes"] += _extract_int(it, "stats.minutesPlayed", "stats.minutes")
        totals["goals"] += _extract_int(it, "stats.goal", "stats.goals")
        totals["assists"] += _extract_int(it, "stats.assist", "stats.assists")
    return totals


def get_season_stats(token: str, player_id: int) -> dict[str, int]:
    seasons = get_seasons(token, player_id)
    sids = _season_ids_for(seasons, TARGET_SEASON_LABEL)
    items = _fetch_all(token, "/v2/metrics/career-stats/players",
        {"offset": 0, "limit": 200, "playerIds": player_id, "seasonIds": sids})
    return _aggregate_stats(items)


def get_career_stats(token: str, player_id: int) -> dict[str, int]:
    items = _fetch_all(token, "/v2/metrics/career-stats/players",
        {"offset": 0, "limit": 200, "playerIds": player_id})
    by_season: dict[int, list[dict]] = {}
    for it in items:
        sid = it.get("seasonId") or (it.get("season") or {}).get("id")
        if isinstance(sid, int):
            by_season.setdefault(sid, []).append(it)
    totals = {"matches": 0, "minutes": 0, "goals": 0, "assists": 0}
    for season_items in by_season.values():
        s = _aggregate_stats(season_items)
        for k in totals: totals[k] += s[k]
    return totals


# ─── Build player data dict ─────────────────────────────────────────────────

def fetch_player_data(token: str, player_id: int) -> dict[str, str]:
    """Fetch all player info and return a flat dict of display values."""
    player = get_player(token, player_id)
    transfer_fee = get_transfer_fee(token, player_id)
    season_stats = get_season_stats(token, player_id)
    career_stats = get_career_stats(token, player_id)

    info = player.get("info") or {}
    team = player.get("team") or {}
    league = player.get("league") or {}
    contract = player.get("contract") or {}

    nats = info.get("nationalities") or []
    nat_str = ", ".join(str(n.get("name", "")).strip() for n in nats if isinstance(n, dict) and n.get("name"))

    agency = (_as_text(contract.get("agencyName")) or
              _as_text((contract.get("agency") or {}).get("name") if isinstance(contract.get("agency"), dict) else ""))
    agent = (_as_text(contract.get("agentName")) or
             _as_text((contract.get("agent") or {}).get("name") if isinstance(contract.get("agent"), dict) else ""))

    raw_pos = _first_position(info)
    positions = info.get("positions") or []

    return {
        "name": _as_text(info.get("footballName") or info.get("name") or ""),
        "date_of_birth": _parse_date(_as_text(info.get("birthDate"))),
        "city_of_birth": _as_text(info.get("birthPlace") or ""),
        "nationality": nat_str,
        "height": _fmt_height(info.get("height")),
        "preferred_foot": _as_text(info.get("preferredFoot") or ""),
        "club": _as_text(team.get("name") or ""),
        "league": _as_text(league.get("name") or ""),
        "agency": agency.strip(),
        "agent": agent.strip(),
        "position_raw": raw_pos,
        "position_abbrev": _position_abbrev(raw_pos),
        "positions": [_as_text(p) for p in positions if p],
        "template_position": SCISPORTS_TO_TEMPLATE.get(raw_pos, ""),
        "contract_end": _parse_date(_as_text(contract.get("contractEnd"))),
        "market_value": _fmt_money(contract.get("marketValue")),
        "transfer_value": _fmt_money(transfer_fee.get("valueEstimateEur")) if transfer_fee else "",
        "season_matches": _fmt_int(season_stats.get("matches")),
        "season_minutes": _fmt_int(season_stats.get("minutes")),
        "season_goals": _fmt_int(season_stats.get("goals")),
        "season_assists": _fmt_int(season_stats.get("assists")),
        "career_matches": _fmt_int(career_stats.get("matches")),
        "career_minutes": _fmt_int(career_stats.get("minutes")),
        "career_goals": _fmt_int(career_stats.get("goals")),
        "career_assists": _fmt_int(career_stats.get("assists")),
    }
