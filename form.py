"""Player form ratings derived from ESPN match stats.

For every completed World Cup 2026 match, fetches per-player stats (goals,
assists, shots on target, saves, cards) from ESPN's unofficial summary API
and computes a form score on a 1-10 scale.

The Elo impact is computed directly per player rather than through the
rating-factor chain (which amplifies via ELO_PER_RATING):

    player_elo_impact = clamp((form_score − 6.5) × ELO_PER_FORM_PT, ±PLAYER_ELO_CAP)
    team_form_delta   = clamp(mean(player_elo_impact, starters), ±TEAM_FORM_CAP)

Typical magnitudes:
    1 goal   → form_score 7.5 → +5 Elo for that player
    1 assist → form_score 7.0 → +2.5 Elo
    yellow   → form_score 6.0 → −2.5 Elo
    red card → form_score 4.5 → −10 Elo (capped)

A team where 3 starters each scored once averages ≈ +1.4 Elo — meaningful
but not dominant relative to the trained base and live-result signals.

Cache: data/form_cache.json — refreshed on POST /api/refresh_form or when
stale (default 4-hour TTL).
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CACHE_FILE = os.path.join(DATA_DIR, "form_cache.json")
CACHE_TTL = 3600 * 4  # seconds

ESPN_BOARD = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"

WC_START = datetime(2026, 6, 11)
FORM_BASELINE = 6.5          # neutral form score; average performer scores this
ELO_PER_FORM_PT = 5.0        # Elo points per form-score point above/below baseline
PLAYER_ELO_CAP = 10.0        # max per-player Elo impact in either direction
TEAM_FORM_CAP = 12.0         # max team-level form delta in either direction

# Weights for computing a form score (1-10 scale) from raw ESPN per-match stats.
# Keep these small enough that one goal → ~7.5 (one point above baseline).
STAT_WEIGHTS: dict[str, float] = {
    "totalGoals":    1.0,    # 1 goal  → 7.5
    "goalAssists":   0.5,    # 1 assist → 7.0
    "shotsOnTarget": 0.15,   # broad contribution signal
    "saves":         0.35,   # GK: 3 saves → 7.6
    "yellowCards":  -0.5,    # yellow → 6.0
    "redCards":     -2.0,    # red    → 4.5
    "ownGoals":     -2.0,    # own goal → 4.5
}

_ESPN_ALIASES: dict[str, str] = {
    "turkey": "Turkey", "turkiye": "Turkey", "türkiye": "Turkey",
    "curacao": "Curacao", "curaçao": "Curacao",
    "usa": "United States", "united states": "United States",
    "united states of america": "United States",
    "korea republic": "South Korea",
    "czech republic": "Czechia",
    "dr congo": "DR Congo", "congo dr": "DR Congo",
    "democratic republic of congo": "DR Congo",
    "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast",
    "cabo verde": "Cape Verde",
    "bosnia & herzegovina": "Bosnia and Herzegovina",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
}

# Module-level in-memory cache to avoid re-reading the file on every request.
_mem_cache: dict = {}
_mem_ts: float = 0.0


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())


def _canonical_team(espn_name: str) -> str:
    low = espn_name.lower().strip()
    if low in _ESPN_ALIASES:
        return _ESPN_ALIASES[low]
    n = _norm(espn_name)
    for k, v in _ESPN_ALIASES.items():
        if _norm(k) == n:
            return v
    return espn_name


def _name_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/125.0 Safari/537.36"),
        "Accept": "application/json",
    })
    return sess


# ----------------------------------------------------------------- cache --

def _load_cache() -> dict:
    global _mem_cache, _mem_ts
    now = time.time()
    if _mem_cache and now - _mem_ts < CACHE_TTL:
        return _mem_cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        ts_str = data.get("ts", "")
        if ts_str:
            ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc).timestamp()
            if now - ts < CACHE_TTL:
                _mem_cache, _mem_ts = data, now
                return data
    return {}


def _save_cache(data: dict) -> None:
    global _mem_cache, _mem_ts
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _mem_cache, _mem_ts = data, time.time()


# -------------------------------------------------------------- ESPN API --

def _events_for_date(sess: requests.Session, date_str: str) -> list[dict]:
    r = sess.get(f"{ESPN_BOARD}?dates={date_str}", timeout=12)
    r.raise_for_status()
    out = []
    for ev in r.json().get("events", []):
        status = ev.get("status", {}).get("type", {}).get("name", "")
        comps = ev.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        home = away = ""
        for c in competitors:
            cname = c.get("team", {}).get("displayName", "")
            if c.get("homeAway") == "home":
                home = cname
            else:
                away = cname
        out.append({"id": ev.get("id"), "home": home, "away": away, "status": status})
    return out


def _player_stats_from_event(sess: requests.Session, event_id: str) -> list[dict]:
    """Fetch per-player form scores for one completed match."""
    r = sess.get(f"{ESPN_SUMMARY}?event={event_id}", timeout=12)
    r.raise_for_status()
    ds = r.json()

    records = []
    for roster in ds.get("rosters", []):
        team = _canonical_team(roster.get("team", {}).get("displayName", ""))
        for entry in roster.get("roster", []):
            athlete = entry.get("athlete", {})
            name = athlete.get("displayName", "")
            if not name:
                continue
            stats = {st["name"]: float(st.get("value") or 0)
                     for st in entry.get("stats", [])}
            if not stats:
                continue
            score = FORM_BASELINE + sum(stats.get(k, 0) * w
                                        for k, w in STAT_WEIGHTS.items())
            score = max(1.0, min(10.0, score))
            records.append({
                "name": name,
                "team": team,
                "form_score": round(score, 3),
                "goals": int(stats.get("totalGoals", 0)),
                "assists": int(stats.get("goalAssists", 0)),
                "starter": entry.get("starter", False),
            })
    return records


# --------------------------------------------------------------- public --

def fetch_form(force: bool = False) -> dict:
    """Fetch (or return cached) WC2026 player form data from ESPN.

    Walks every day from WC kick-off to today, collects per-player stats from
    completed matches, and averages across multiple appearances.
    """
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    sess = _session()
    today = datetime.utcnow()
    all_records: list[dict] = []
    errors: list[str] = []
    events_fetched: int = 0

    current = WC_START
    while current.date() <= today.date():
        date_str = current.strftime("%Y%m%d")
        try:
            events = _events_for_date(sess, date_str)
            for ev in events:
                if ev["status"] != "STATUS_FULL_TIME":
                    continue
                try:
                    records = _player_stats_from_event(sess, ev["id"])
                    all_records.extend(records)
                    events_fetched += 1
                    time.sleep(0.25)
                except Exception as e:
                    errors.append(f"event {ev['id']}: {e}")
        except Exception as e:
            errors.append(f"date {date_str}: {e}")
        current += timedelta(days=1)

    # Aggregate: average form_score per (team, player_name)
    agg: dict[tuple[str, str], list[float]] = {}
    for rec in all_records:
        key = (rec["team"], rec["name"])
        agg.setdefault(key, []).append(rec["form_score"])

    players: dict[str, dict[str, float]] = {}
    for (team, name), scores in agg.items():
        players.setdefault(team, {})[name] = round(sum(scores) / len(scores), 3)

    cache = {
        "ts": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec="seconds"),
        "source": "espn",
        "matchesScanned": events_fetched,
        "teamsWithData": len(players),
        "players": players,
        "errors": errors[:20],
    }
    _save_cache(cache)
    return cache


def get_form_score(player_name: str, team: str, cache: dict | None = None) -> float:
    """Return ESPN-derived form score (1-10) for a player. Baseline 6.5 if unknown."""
    if cache is None:
        cache = _load_cache()
    team_data = cache.get("players", {}).get(team, {})
    if player_name in team_data:
        return team_data[player_name]
    if team_data:
        # Fuzzy match against known player names for this team
        best, best_sim = max(
            ((n, _name_sim(player_name, n)) for n in team_data),
            key=lambda x: x[1], default=("", 0.0)
        )
        if best_sim >= 0.72:
            return team_data[best]
    return FORM_BASELINE


def player_elo_impact(player_name: str, team: str, cache: dict | None = None) -> float:
    """Direct Elo contribution from a player's form. Clamped to ±PLAYER_ELO_CAP."""
    score = get_form_score(player_name, team, cache)
    raw = (score - FORM_BASELINE) * ELO_PER_FORM_PT
    return max(-PLAYER_ELO_CAP, min(PLAYER_ELO_CAP, raw))


def team_form_delta(squad: dict, team_name: str, cache: dict | None = None) -> float:
    """Mean per-player Elo impact across starters, capped at ±TEAM_FORM_CAP."""
    if cache is None:
        cache = _load_cache()
    if not cache:
        return 0.0
    starters = [p for p in squad.get("players", [])
                if p.get("starter") and p.get("available", True)]
    if not starters:
        return 0.0
    impacts = [player_elo_impact(p["name"], team_name, cache) for p in starters]
    mean_impact = sum(impacts) / len(impacts)
    return round(max(-TEAM_FORM_CAP, min(TEAM_FORM_CAP, mean_impact)), 2)


def all_form_deltas(squads: dict) -> dict[str, float]:
    cache = _load_cache()
    return {team: team_form_delta(sq, team, cache) for team, sq in squads.items()}


def squad_form_detail(squad: dict, team_name: str, cache: dict | None = None) -> list[dict]:
    """Per-player form breakdown for the Starting XI editor."""
    if cache is None:
        cache = _load_cache()
    out = []
    for p in squad.get("players", []):
        fs = get_form_score(p["name"], team_name, cache)
        elo = player_elo_impact(p["name"], team_name, cache)
        matched = (team_name in cache.get("players", {})
                   and p["name"] in cache["players"].get(team_name, {}))
        out.append({
            "id": p["id"],
            "formScore": round(fs, 2),
            "eloImpact": round(elo, 1),
            "matched": matched,
        })
    return out


def meta() -> dict:
    cache = _load_cache()
    return {k: v for k, v in cache.items() if k != "players"}


# ----------------------------------------------------------------- live --

def live_matches(date_str: str | None = None) -> list[dict]:
    """Return today's WC matches (live, pre, or recent) from ESPN scoreboard."""
    import re as _re
    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y%m%d")
    sess = _session()
    r = sess.get(f"{ESPN_BOARD}?dates={date_str}", timeout=10)
    r.raise_for_status()
    out = []
    for ev in r.json().get("events", []):
        status = ev.get("status", {})
        state = status.get("type", {}).get("state", "pre")
        comp = (ev.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        clock = status.get("displayClock", "0")
        m = _re.search(r"\d+", str(clock))
        minute = int(m.group()) if m else 0
        out.append({
            "id": ev.get("id", ""),
            "home": _canonical_team(home.get("team", {}).get("displayName", "")),
            "away": _canonical_team(away.get("team", {}).get("displayName", "")),
            "homeScore": int(home.get("score") or 0),
            "awayScore": int(away.get("score") or 0),
            "minute": minute,
            "period": status.get("period", 1),
            "state": state,
            "statusText": status.get("type", {}).get("shortDetail", ""),
        })
    return out


def match_stats(event_id: str) -> dict:
    """Return live boxscore stats for one ESPN event.

    Returns {"home": {...}, "away": {...}} with keys like
    shotsOnTarget, totalShots, possessionPct, wonCorners, yellowCards, redCards.
    """
    sess = _session()
    r = sess.get(f"{ESPN_SUMMARY}?event={event_id}", timeout=10)
    r.raise_for_status()
    result: dict[str, dict[str, float]] = {}
    for team_box in r.json().get("boxscore", {}).get("teams", []):
        side = team_box.get("homeAway", "")
        stats: dict[str, float] = {}
        for st in team_box.get("statistics", []):
            try:
                stats[st["name"]] = float(st.get("value") or st.get("displayValue") or 0)
            except (ValueError, TypeError):
                stats[st["name"]] = 0.0
        result[side] = stats
    return result
