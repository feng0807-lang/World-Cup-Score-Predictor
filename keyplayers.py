"""Key-player (talisman) analysis and impact model.

Beyond the flat "average of 11 starters" lineup model, some teams lean heavily
on one player. This module:

  * aggregates cumulative per-player stats from ESPN across all played matches,
  * picks each team's core player(s) by goal involvement,
  * computes a *dependency* factor (how concentrated the team's output is on
    them), shrunk toward neutral for small samples,
  * tracks discipline (yellow-card suspension risk) and minutes/fatigue load,
  * folds an optional off-field profile (age, role, status note, manual Elo
    nudge) researched separately and stored in keyplayer_profiles.json,
  * exposes a per-team Elo delta: when the talisman is unavailable, the team is
    penalised in proportion to how dependent it is on them.

The on-field stats cache lives in data/keyplayers.json (refreshed like form).
The off-field profiles live in keyplayer_profiles.json (committed, hand/researched).
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import form

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CACHE_FILE = os.path.join(DATA_DIR, "keyplayers.json")
PROFILES_FILE = os.path.join(HERE, "keyplayer_profiles.json")
CACHE_TTL = 3600 * 4

# --- impact tuning -----------------------------------------------------------
DEP_PRIOR_GOALS = 3.0     # pseudo "other-player" goals; shrinks small-sample share
DEP_CAP = 0.75            # max dependency a single player can carry
KEYPLAYER_MAX_PENALTY = 60.0   # Elo lost if a 100%-dependency talisman is absent
FATIGUE_FLAG_APPS = 3     # appearances at/above this with no rest = fatigue flag

_mem: dict = {}
_mem_ts: float = 0.0
_profiles_mem: dict | None = None


# ----------------------------------------------------------------- cache --

def _load_cache() -> dict:
    global _mem, _mem_ts
    now = time.time()
    if _mem and now - _mem_ts < CACHE_TTL:
        return _mem
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            ts = datetime.fromisoformat(data.get("ts", "1970-01-01T00:00:00")).timestamp()
            if now - ts < CACHE_TTL:
                _mem, _mem_ts = data, now
                return data
        except Exception:
            pass
    return {}


def _save_cache(data: dict) -> None:
    global _mem, _mem_ts
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _mem, _mem_ts = data, time.time()


def load_profiles() -> dict:
    """Off-field profiles: {team: {player: {age, role, status, note, adj}}}."""
    global _profiles_mem
    if _profiles_mem is not None:
        return _profiles_mem
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, encoding="utf-8") as f:
                _profiles_mem = json.load(f)
                return _profiles_mem
        except Exception:
            pass
    _profiles_mem = {}
    return _profiles_mem


# -------------------------------------------------------------- analysis --

def analyze(force: bool = False) -> dict:
    """Build (or return cached) per-team key-player analysis from ESPN."""
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    sess = form._session()
    # (team, name) -> aggregated stats
    agg: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float))
    today = datetime.utcnow()
    cur = form.WC_START
    while cur.date() <= today.date():
        ds = cur.strftime("%Y%m%d")
        try:
            events = form._events_for_date(sess, ds)
        except Exception:
            cur += timedelta(days=1)
            continue
        for ev in events:
            if ev["status"] != "STATUS_FULL_TIME":
                continue
            try:
                dj = sess.get(f"{form.ESPN_SUMMARY}?event={ev['id']}", timeout=12).json()
            except Exception:
                continue
            for roster in dj.get("rosters", []):
                team = form._canonical_team(roster.get("team", {}).get("displayName", ""))
                for entry in roster.get("roster", []):
                    name = entry.get("athlete", {}).get("displayName", "")
                    if not name:
                        continue
                    st = {s["name"]: float(s.get("value") or 0)
                          for s in entry.get("stats", [])}
                    rec = agg[(team, name)]
                    for k in ("totalGoals", "goalAssists", "shotsOnTarget", "saves",
                              "yellowCards", "redCards", "foulsSuffered"):
                        rec[k] += st.get(k, 0)
                    pos = entry.get("position") or {}
                    rec["_apps"] += 1 if (entry.get("starter") or st.get("appearances")) else 0
                    rec["_pos"] = pos.get("abbreviation", rec.get("_pos", ""))
            time.sleep(0.05)
        cur += timedelta(days=1)

    # Per-team aggregation
    teams: dict[str, dict] = {}
    team_goals: dict[str, float] = defaultdict(float)
    for (team, name), s in agg.items():
        team_goals[team] += s["totalGoals"]

    by_team: dict[str, list] = defaultdict(list)
    for (team, name), s in agg.items():
        by_team[team].append((name, s))

    for team, roster in by_team.items():
        roster.sort(key=lambda x: -(x[1]["totalGoals"] * 2 + x[1]["goalAssists"]
                                     + x[1]["shotsOnTarget"] * 0.2 + x[1]["saves"] * 0.1))
        tg = team_goals[team]
        players = []
        for name, s in roster:
            goals = s["totalGoals"]
            dependency = min(DEP_CAP, goals / (tg + DEP_PRIOR_GOALS)) if (goals or tg) else 0.0
            yc = int(s["yellowCards"])
            rc = int(s["redCards"])
            apps = int(s["_apps"])
            suspended = rc >= 1 or yc >= 2
            players.append({
                "name": name,
                "pos": s.get("_pos", ""),
                "goals": int(goals),
                "assists": int(s["goalAssists"]),
                "sot": int(s["shotsOnTarget"]),
                "saves": int(s["saves"]),
                "yellowCards": yc,
                "redCards": rc,
                "apps": apps,
                "dependency": round(dependency, 3),
                "suspended": suspended,
                "suspensionRisk": (not suspended) and yc == 1,
                "fatigue": apps >= FATIGUE_FLAG_APPS,
            })
        # Core = the top entry (talisman); secondary if it also has real output
        core = players[0] if players else None
        teams[team] = {
            "core": core,
            "players": players,
            "teamGoals": int(tg),
        }

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": teams,
        "teamCount": len(teams),
    }
    _save_cache(out)
    return out


# ----------------------------------------------------------------- impact --

def _core_for(team: str, cache: dict | None = None) -> dict | None:
    cache = cache or _load_cache()
    t = cache.get("teams", {}).get(team)
    return t.get("core") if t else None


def _is_available(player_name: str, squad: dict) -> bool:
    """A core player counts as available if present in the squad and not flagged
    unavailable (manual toggle) — used to detect injuries/rotation."""
    for p in squad.get("players", []):
        if form._name_sim(p["name"], player_name) >= 0.6:
            return p.get("available", True)
    # Not in squad at all -> treat as unavailable
    return False


def team_keyplayer_delta(team: str, squad: dict, cache: dict | None = None) -> float:
    """Elo delta from key-player effects:
      - if the talisman is suspended/injured/absent, penalise by dependency,
      - plus any off-field manual adjustment for available core players.
    Returns 0 for teams with no identifiable core player.
    """
    cache = cache or _load_cache()
    core = _core_for(team, cache)
    if not core:
        return 0.0
    profiles = load_profiles().get(team, {})
    delta = 0.0

    available = _is_available(core["name"], squad) and not core["suspended"]
    if not available:
        delta -= core["dependency"] * KEYPLAYER_MAX_PENALTY
    else:
        # off-field nudge only applies when the player is actually on the pitch
        prof = profiles.get(core["name"], {})
        delta += float(prof.get("adj", 0) or 0)
    return round(delta, 1)


def detail(team: str, squad: dict | None = None, cache: dict | None = None) -> dict:
    """Full key-player breakdown for the dashboard."""
    cache = cache or _load_cache()
    t = cache.get("teams", {}).get(team, {})
    core = t.get("core")
    profiles = load_profiles().get(team, {})
    if core:
        core = dict(core)
        core["available"] = (_is_available(core["name"], squad) if squad else True) and not core["suspended"]
        core["offField"] = profiles.get(core["name"], {})
    return {
        "team": team,
        "core": core,
        "keyPlayerDelta": team_keyplayer_delta(team, squad, cache) if squad else 0.0,
        "watchlist": [p for p in t.get("players", [])
                      if p["suspended"] or p["suspensionRisk"]][:6],
        "topContributors": t.get("players", [])[:5],
    }


def meta() -> dict:
    cache = _load_cache()
    return {"ts": cache.get("ts"), "teamCount": cache.get("teamCount", 0)}


if __name__ == "__main__":
    data = analyze(force=True)
    print(f"Analyzed {data['teamCount']} teams.\n")
    rows = []
    for team, t in data["teams"].items():
        c = t.get("core")
        if c:
            rows.append((c["dependency"], team, c))
    rows.sort(reverse=True)
    print(f"{'Team':<20}{'Core player':<22}{'G':>2}{'A':>2}{'dep':>6}  flags")
    for dep, team, c in rows[:20]:
        flags = []
        if c["suspended"]:
            flags.append("SUSPENDED")
        elif c["suspensionRisk"]:
            flags.append("1 YC")
        if c["fatigue"]:
            flags.append("fatigue")
        print(f"{team:<20}{c['name']:<22}{c['goals']:>2}{c['assists']:>2}{dep:>6.2f}  {', '.join(flags)}")
