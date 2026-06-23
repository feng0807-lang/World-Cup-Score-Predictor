"""Key-player (talisman) analysis and impact model.

Beyond the flat "average of 11 starters" lineup model, some teams lean heavily
on one or two players. This module:

  * aggregates per-player stats from ESPN across the World Cup AND the lead-up
    (pre-WC friendlies + the latest World Cup qualifiers), so the talisman read
    isn't hostage to a 2-match sample. Recent / higher-level matches are weighted
    more (WC > friendly > qualifier),
  * picks each team's CORE GROUP — the top 1-3 attacking contributors by
    weighted goal involvement (goalkeepers and bench-only players excluded so we
    don't mistake a one-off sub goal or a busy keeper for a talisman),
  * gives each a *dependency* share (how concentrated the team's output is on
    them), shrunk toward neutral for small samples,
  * tracks discipline (yellow-card suspension) and minutes/fatigue from the WC
    ONLY (qualifier/friendly cards don't carry into the tournament),
  * folds an optional off-field profile (age, role, status note, manual Elo
    nudge) from keyplayer_profiles.json,
  * exposes a per-team Elo delta: for every core-group member who is
    suspended/injured/absent, the team is penalised in proportion to that
    player's dependency share.

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
import teams as teams_mod

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CACHE_FILE = os.path.join(DATA_DIR, "keyplayers.json")
PROFILES_FILE = os.path.join(HERE, "keyplayer_profiles.json")
CACHE_TTL = 3600 * 4

WEB_BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"

# Competitions feeding the talisman read: (league slug, date range, weight).
# WC form counts most; pre-WC friendlies next; the final qualifying year least.
COMPETITIONS = [
    ("fifa.world", None, 1.0),                       # WC2026 (window set at runtime)
    ("fifa.friendly", "20260101-20260610", 0.5),     # pre-WC friendlies
    ("fifa.worldq.uefa", "20250101-20251231", 0.6),
    ("fifa.worldq.conmebol", "20250101-20251231", 0.6),
    ("fifa.worldq.concacaf", "20250101-20251231", 0.6),
    ("fifa.worldq.afc", "20250101-20251231", 0.6),
    ("fifa.worldq.caf", "20250101-20251231", 0.6),
    ("fifa.worldq.ofc", "20250101-20251231", 0.6),
]

# --- impact tuning -----------------------------------------------------------
DEP_PRIOR_GOALS = 4.0     # pseudo "other-player" goals; shrinks small-sample share
DEP_CAP = 0.65            # max dependency a single player can carry
GROUP_DEP_CAP = 0.85      # max combined dependency of the whole core group
KEYPLAYER_MAX_PENALTY = 60.0   # Elo lost if a 100%-dependency talisman is absent
CORE_GROUP_MAX = 3        # at most this many key players per team
CORE_MIN_SHARE = 0.10     # include beyond the top one only if share >= this
FATIGUE_FLAG_APPS = 3     # WC appearances at/above this with no rest = fatigue flag
_GK_POS = ("G", "GK")

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

def _events_in_range(sess, league: str, rng: str) -> list[dict]:
    """Completed events for a league over a date range (single scoreboard call)."""
    try:
        r = sess.get(f"{WEB_BASE}/{league}/scoreboard?dates={rng}&limit=900", timeout=20)
        r.raise_for_status()
        out = []
        for ev in r.json().get("events", []):
            status = ev.get("status", {}).get("type", {}).get("name", "")
            if status != "STATUS_FULL_TIME":
                continue
            out.append({"id": str(ev.get("id", "")), "league": league})
        return out
    except Exception:
        return []


def _accumulate(sess, league: str, event_id: str, weight: float,
                broad: dict, wc: dict, known: set) -> None:
    """Add one event's per-player stats into the broad (weighted) and, for the
    World Cup, the wc (discipline/fatigue) aggregations."""
    api = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event_id}"
    try:
        dj = sess.get(api, timeout=12).json()
    except Exception:
        return
    is_wc = league == "fifa.world"
    for roster in dj.get("rosters", []):
        team = form._canonical_team(roster.get("team", {}).get("displayName", ""))
        if team not in known:
            continue
        for entry in roster.get("roster", []):
            name = entry.get("athlete", {}).get("displayName", "")
            if not name:
                continue
            st = {s["name"]: float(s.get("value") or 0) for s in entry.get("stats", [])}
            pos = entry.get("position") or {}
            pos_abbr = pos.get("abbreviation", "")
            started = bool(entry.get("starter"))
            b = broad[(team, name)]
            # Dependency is share of goal CONTRIBUTIONS (G + A) so creators count,
            # not just finishers. Ranking adds shots-on-target as a threat proxy.
            contrib = st.get("totalGoals", 0) + st.get("goalAssists", 0)
            b["wcontrib"] += contrib * weight
            b["wgi"] += (contrib + st.get("shotsOnTarget", 0) * 0.25) * weight
            b["goals"] += st.get("totalGoals", 0)
            b["assists"] += st.get("goalAssists", 0)
            b["sot"] += st.get("shotsOnTarget", 0)
            b["saves"] += st.get("saves", 0)
            b["matches"] += 1
            if started:
                b["starts"] += 1
            # Prefer a real position over a "SUB" / blank label.
            if pos_abbr and (not b.get("_pos") or b.get("_pos") == "SUB"):
                b["_pos"] = pos_abbr
            if is_wc:
                w = wc[(team, name)]
                w["yellowCards"] += st.get("yellowCards", 0)
                w["redCards"] += st.get("redCards", 0)
                w["apps"] += 1 if (started or st.get("appearances")) else 0


def _is_attacker(pos: str) -> bool:
    return bool(pos) and pos.upper() not in _GK_POS


def analyze(force: bool = False, verbose: bool = False) -> dict:
    """Build (or return cached) per-team key-player analysis from ESPN, across
    the WC plus pre-WC friendlies and the latest qualifiers."""
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    sess = form._session()
    known = set(teams_mod.ELO)
    today = datetime.utcnow()
    wc_range = f"{form.WC_START.strftime('%Y%m%d')}-{today.strftime('%Y%m%d')}"

    broad: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    wc: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for league, rng, weight in COMPETITIONS:
        rng = rng or wc_range
        events = _events_in_range(sess, league, rng)
        if verbose:
            print(f"  {league:<24} {rng}: {len(events)} completed events")
        for ev in events:
            _accumulate(sess, league, ev["id"], weight, broad, wc, known)
            time.sleep(0.03)

    # Per-team total goal contributions (G+A) for dependency shares
    team_contrib: dict[str, float] = defaultdict(float)
    for (team, name), s in broad.items():
        team_contrib[team] += s["wcontrib"]

    by_team: dict[str, list] = defaultdict(list)
    for (team, name), s in broad.items():
        by_team[team].append((name, s))

    all_profiles = load_profiles()
    teams: dict[str, dict] = {}
    for team, roster in by_team.items():
        tc = team_contrib[team]
        prof = all_profiles.get(team, {})
        rows = []
        for name, s in roster:
            w = wc.get((team, name), {})
            yc, rc = int(w.get("yellowCards", 0)), int(w.get("redCards", 0))
            apps = int(w.get("apps", 0))
            # dependency = shrunk share of team goal contributions (G+A)
            dep = min(DEP_CAP, s["wcontrib"] / (tc + DEP_PRIOR_GOALS)) if tc else 0.0
            rows.append({
                "name": name,
                "pos": s.get("_pos", ""),
                "goals": int(s["goals"]),
                "assists": int(s["assists"]),
                "sot": int(s["sot"]),
                "saves": int(s["saves"]),
                "matches": int(s["matches"]),
                "starts": int(s["starts"]),
                "yellowCards": yc,
                "redCards": rc,
                "apps": apps,
                "dependency": round(dep, 3),
                "suspended": rc >= 1 or yc >= 2,
                "suspensionRisk": not (rc >= 1 or yc >= 2) and yc == 1,
                "fatigue": apps >= FATIGUE_FLAG_APPS,
                "designated": False,
                "_score": s["wgi"],
            })
        rows.sort(key=lambda r: -r["_score"])
        by_name = {r["name"]: r for r in rows}

        # Data-driven core: top attacking contributors (exclude GKs and pure subs)
        candidates = [r for r in rows
                      if _is_attacker(r["pos"]) and r["starts"] >= 1 and r["_score"] > 0]
        group = []
        for r in candidates:
            if not group or (r["dependency"] >= CORE_MIN_SHARE and len(group) < CORE_GROUP_MAX):
                group.append(r)
            if len(group) >= CORE_GROUP_MAX:
                break

        # Designated key players (profile "key": true) — eye-test talismen the
        # box score under-credits (e.g. a creator playing few minutes). Force them
        # into the group with their profile dependency (or their data share).
        for pname, pinfo in prof.items():
            if not isinstance(pinfo, dict) or not pinfo.get("key"):
                continue
            r = by_name.get(pname)
            if r is None:
                r = {"name": pname, "pos": pinfo.get("role", ""), "goals": 0,
                     "assists": 0, "sot": 0, "saves": 0, "matches": 0, "starts": 0,
                     "yellowCards": 0, "redCards": 0, "apps": 0, "dependency": 0.0,
                     "suspended": False, "suspensionRisk": False, "fatigue": False,
                     "designated": True}
            r["designated"] = True
            r["dependency"] = round(max(r["dependency"], float(pinfo.get("dependency", 0) or 0)), 3)
            if r not in group:
                group.append(r)

        # Keep the strongest CORE_GROUP_MAX, but never drop a designated player.
        group.sort(key=lambda r: (r["designated"], r["dependency"]), reverse=True)
        keep = [r for r in group if r["designated"]]
        for r in group:
            if r not in keep and len(keep) < CORE_GROUP_MAX:
                keep.append(r)
        group = sorted(keep, key=lambda r: -r["dependency"])

        # Cap combined dependency
        gsum = sum(r["dependency"] for r in group)
        if gsum > GROUP_DEP_CAP and gsum > 0:
            scale = GROUP_DEP_CAP / gsum
            for r in group:
                r["dependency"] = round(r["dependency"] * scale, 3)
        for r in rows:
            r.pop("_score", None)
        for r in group:
            r.pop("_score", None)
        teams[team] = {
            "coreGroup": group,
            "core": group[0] if group else None,
            "players": rows[:8],
            "teamGoals": round(tc, 1),
        }

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": teams,
        "teamCount": len(teams),
        "competitions": [c[0] for c in COMPETITIONS],
    }
    _save_cache(out)
    return out


# ----------------------------------------------------------------- impact --

def _is_available(player_name: str, squad: dict) -> bool:
    """A core player counts as available if present in the squad and not flagged
    unavailable (manual toggle) — used to detect injuries/rotation."""
    for p in squad.get("players", []):
        if form._name_sim(p["name"], player_name) >= 0.6:
            return p.get("available", True)
    # Not in squad at all -> treat as unavailable
    return False


def _core_group(team: str, cache: dict | None = None) -> list:
    cache = cache or _load_cache()
    t = cache.get("teams", {}).get(team)
    return t.get("coreGroup", []) if t else []


def team_keyplayer_delta(team: str, squad: dict, cache: dict | None = None) -> float:
    """Elo delta from key-player effects, summed over the core group:
      - each member who is suspended/injured/absent costs the team
        (their dependency share x KEYPLAYER_MAX_PENALTY),
      - each available member contributes any off-field manual nudge.
    Returns 0 for teams with no identifiable core group.
    """
    cache = cache or _load_cache()
    group = _core_group(team, cache)
    if not group:
        return 0.0
    profiles = load_profiles().get(team, {})
    delta = 0.0
    for member in group:
        available = _is_available(member["name"], squad) and not member["suspended"]
        if not available:
            delta -= member["dependency"] * KEYPLAYER_MAX_PENALTY
        else:
            delta += float(profiles.get(member["name"], {}).get("adj", 0) or 0)
    return round(delta, 1)


def detail(team: str, squad: dict | None = None, cache: dict | None = None) -> dict:
    """Full key-player breakdown for the dashboard."""
    cache = cache or _load_cache()
    t = cache.get("teams", {}).get(team, {})
    profiles = load_profiles().get(team, {})
    group = []
    for member in t.get("coreGroup", []):
        m = dict(member)
        m["available"] = (_is_available(m["name"], squad) if squad else True) and not m["suspended"]
        m["offField"] = profiles.get(m["name"], {})
        group.append(m)
    return {
        "team": team,
        "coreGroup": group,
        "core": group[0] if group else None,
        "keyPlayerDelta": team_keyplayer_delta(team, squad, cache) if squad else 0.0,
        "watchlist": [p for p in t.get("players", [])
                      if p["suspended"] or p["suspensionRisk"]][:6],
        "topContributors": t.get("players", [])[:5],
    }


def meta() -> dict:
    cache = _load_cache()
    return {"ts": cache.get("ts"), "teamCount": cache.get("teamCount", 0)}


if __name__ == "__main__":
    import sys
    data = analyze(force=True, verbose=True)
    print(f"\nAnalyzed {data['teamCount']} teams across {len(data['competitions'])} competitions.\n")
    rows = sorted(data["teams"].items(),
                  key=lambda kv: -(kv[1]["core"]["dependency"] if kv[1].get("core") else 0))
    for team, t in rows:
        group = t.get("coreGroup", [])
        if not group:
            continue
        names = []
        for m in group:
            flag = " (SUSP)" if m["suspended"] else (" (1YC)" if m["suspensionRisk"] else "")
            names.append(f"{m['name']} {int(m['dependency']*100)}%{flag}")
        print(f"{team:<22} {' | '.join(names)}")
