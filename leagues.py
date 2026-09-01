"""Club-league support: ratings, tables and fixtures for the major leagues.

The World Cup side of this app leans on the encrypted engine's trained
international ratings. Club teams aren't in that model — `secure.trained_elo`
returns the 1500 default and `expected_goals` falls back to a symmetric
league-average baseline. That fallback is exactly what we want as a
*total-goals prior*: for club matches we supply the supremacy ourselves from
Elo ratings built here, and override the total with the league's own measured
scoring rate.

Per league we replay every completed match through online Elo:

    exp_home = 1 / (1 + 10^(-((R_home + HA) - R_away)/400))
    R += K * log(|GD| + 1 clamped) * (result - exp_home)

and measure two calibration constants from the same results:

    homeAdv  = mean(home goals - away goals) / GOALS_PER_ELO   (Elo points)
    avgGoals = mean(total goals per match)                     (total prior)

Both differ by league (Bundesliga outscores Serie A; La Liga's home edge is
not the Premier League's), which is the point of measuring rather than
assuming. Ratings are seeded at 1500 and converge over the replay window, so
give it a full prior season plus the current one.

Cache: data/leagues/<slug>.json — rebuild via POST /api/league_refresh.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

import form

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data", "leagues")
WEB_BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
CACHE_TTL = 3600 * 6

# ESPN slug -> display metadata. Order is the dashboard order.
LEAGUES: dict[str, dict] = {
    "eng.1":          {"name": "Premier League",   "country": "England"},
    "esp.1":          {"name": "La Liga",          "country": "Spain"},
    "ita.1":          {"name": "Serie A",          "country": "Italy"},
    "ger.1":          {"name": "Bundesliga",       "country": "Germany"},
    "fra.1":          {"name": "Ligue 1",          "country": "France"},
    "por.1":          {"name": "Primeira Liga",    "country": "Portugal"},
    "ned.1":          {"name": "Eredivisie",       "country": "Netherlands"},
    "eng.2":          {"name": "Championship",     "country": "England"},
    "usa.1":          {"name": "MLS",              "country": "USA"},
    "mex.1":          {"name": "Liga MX",          "country": "Mexico"},
    "bra.1":          {"name": "Brasileirão",      "country": "Brazil"},
    "arg.1":          {"name": "Liga Profesional", "country": "Argentina"},
    "uefa.champions": {"name": "Champions League", "country": "Europe"},
    "uefa.europa":    {"name": "Europa League",    "country": "Europe"},
}

# Elo replay parameters (club football: more matches, so a gentler K than the
# K=30 used for the sparse international calendar).
K_FACTOR = 20.0
GOALS_PER_ELO = 0.0036      # shared with model.py — keeps units consistent
GD_CLAMP = 4                # cap the goal-difference multiplier's input
SEED_ELO = 1500.0
DEFAULT_HOME_ADV = 65.0     # fallback if a league has too few matches to measure
DEFAULT_AVG_GOALS = 2.75

_mem: dict[str, dict] = {}
_mem_ts: dict[str, float] = {}


# ------------------------------------------------------------------ fetch --

def _season_windows(seasons: int) -> list[str]:
    """Date ranges covering the current season plus `seasons-1` prior ones.

    European seasons run Aug->May; a window of Jul 1 -> Jun 30 captures one
    season cleanly and also works for calendar-year leagues (MLS, Brazil) by
    simply spanning their season instead.
    """
    today = datetime.now(timezone.utc).date()
    start_year = today.year if today.month >= 7 else today.year - 1
    out = []
    for back in range(seasons):
        y = start_year - back
        out.append(f"{y}0701-{y+1}0630")
    return list(reversed(out))


def fetch_events(slug: str, seasons: int = 2) -> list[dict]:
    """All events (completed and scheduled) for a league over the window."""
    sess = form._session()
    seen: set[str] = set()
    out: list[dict] = []
    for rng in _season_windows(seasons):
        try:
            r = sess.get(f"{WEB_BASE}/{slug}/scoreboard?dates={rng}&limit=1000",
                         timeout=30)
            r.raise_for_status()
            events = r.json().get("events", [])
        except Exception:
            continue
        for ev in events:
            eid = str(ev.get("id", ""))
            if not eid or eid in seen:
                continue
            seen.add(eid)
            comp = (ev.get("competitions") or [{}])[0]
            cs = comp.get("competitors", [])
            home = next((c for c in cs if c.get("homeAway") == "home"), {})
            away = next((c for c in cs if c.get("homeAway") == "away"), {})
            h = home.get("team", {}).get("displayName", "")
            a = away.get("team", {}).get("displayName", "")
            if not h or not a:
                continue
            stype = ev.get("status", {}).get("type", {})
            out.append({
                "id": eid,
                "date": str(ev.get("date", ""))[:10],
                "home": h, "away": a,
                "gh": int(home.get("score") or 0),
                "ga": int(away.get("score") or 0),
                "state": stype.get("state", "pre"),
                "venue": (comp.get("venue", {}) or {}).get("fullName", ""),
            })
        time.sleep(0.05)
    out.sort(key=lambda e: (e["date"], e["id"]))
    return out


# ------------------------------------------------------------------- Elo --

def _replay(results: list[dict], home_adv: float) -> dict[str, float]:
    elo: dict[str, float] = defaultdict(lambda: SEED_ELO)
    for m in results:
        h, a = m["home"], m["away"]
        rh, ra = elo[h], elo[a]
        exp_h = 1.0 / (1.0 + 10 ** (-((rh + home_adv) - ra) / 400.0))
        gd = m["gh"] - m["ga"]
        score = 1.0 if gd > 0 else (0.5 if gd == 0 else 0.0)
        mult = math.log(min(abs(gd), GD_CLAMP) + 1)
        delta = K_FACTOR * mult * (score - exp_h)
        elo[h] = rh + delta
        elo[a] = ra - delta
    return dict(elo)


def build(slug: str, seasons: int = 2, force: bool = False) -> dict:
    """Fetch, replay and calibrate one league. Cached to data/leagues/<slug>."""
    if not force:
        cached = load(slug)
        if cached:
            return cached

    events = fetch_events(slug, seasons)
    played = [e for e in events if e["state"] == "post"]
    upcoming = [e for e in events if e["state"] != "post"]

    # Calibration measured from this league's own results.
    if played:
        home_adv = round(
            (sum(e["gh"] - e["ga"] for e in played) / len(played)) / GOALS_PER_ELO, 1)
        avg_goals = round(sum(e["gh"] + e["ga"] for e in played) / len(played), 3)
        hw = sum(1 for e in played if e["gh"] > e["ga"])
        dr = sum(1 for e in played if e["gh"] == e["ga"])
    else:
        home_adv, avg_goals, hw, dr = DEFAULT_HOME_ADV, DEFAULT_AVG_GOALS, 0, 0
    home_adv = max(0.0, min(150.0, home_adv))

    elo = _replay(played, home_adv)

    # Current-season table (from the latest season window only).
    cur_start = _season_windows(1)[0][:4]
    tab: dict[str, dict] = defaultdict(
        lambda: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "Pts": 0})
    for e in played:
        if e["date"][:4] < cur_start and e["date"][5:7] < "07":
            pass
        if e["date"] < f"{cur_start}-07-01":
            continue
        for team, gf, ga in ((e["home"], e["gh"], e["ga"]), (e["away"], e["ga"], e["gh"])):
            t = tab[team]
            t["P"] += 1; t["GF"] += gf; t["GA"] += ga
            if gf > ga:   t["W"] += 1; t["Pts"] += 3
            elif gf == ga: t["D"] += 1; t["Pts"] += 1
            else:          t["L"] += 1
    table = [{"team": k, **v, "GD": v["GF"] - v["GA"], "elo": round(elo.get(k, SEED_ELO), 1)}
             for k, v in tab.items()]
    table.sort(key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))

    data = {
        "slug": slug,
        "name": LEAGUES.get(slug, {}).get("name", slug),
        "country": LEAGUES.get(slug, {}).get("country", ""),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "matchesPlayed": len(played),
        "homeAdv": home_adv,
        "avgGoals": avg_goals,
        "homeWinPct": round(hw / len(played) * 100, 1) if played else None,
        "drawPct": round(dr / len(played) * 100, 1) if played else None,
        "elo": {k: round(v, 1) for k, v in
                sorted(elo.items(), key=lambda kv: -kv[1])},
        "table": table,
        "upcoming": upcoming[:60],
        "recent": played[-15:],
    }
    save(data)
    return data


# ------------------------------------------------------------------ cache --

def _path(slug: str) -> str:
    return os.path.join(DATA_DIR, f"{slug}.json")


def save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(_path(data["slug"]), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _mem[data["slug"]] = data
    _mem_ts[data["slug"]] = time.time()


def load(slug: str) -> dict:
    """Cached league data (served even when stale — staleness only decides
    whether a rebuild is worthwhile)."""
    now = time.time()
    if slug in _mem and now - _mem_ts.get(slug, 0) < CACHE_TTL:
        return _mem[slug]
    p = _path(slug)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                _mem[slug] = json.load(f)
            _mem_ts[slug] = now
            return _mem[slug]
        except Exception:
            pass
    return {}


def available() -> list[dict]:
    """Registry with a built/not-built flag for each league."""
    out = []
    for slug, meta in LEAGUES.items():
        d = load(slug)
        out.append({"slug": slug, **meta,
                    "built": bool(d),
                    "teams": len(d.get("elo", {})),
                    "matchesPlayed": d.get("matchesPlayed", 0),
                    "ts": d.get("ts")})
    return out


def team_elo(slug: str, team: str) -> float:
    return load(slug).get("elo", {}).get(team, SEED_ELO)


if __name__ == "__main__":
    import sys
    slugs = sys.argv[1:] or list(LEAGUES)
    for s in slugs:
        d = build(s, force=True)
        top = list(d["elo"].items())[:5]
        print(f"{d['name']:<18} {d['matchesPlayed']:>4} matches | "
              f"HA {d['homeAdv']:>5} | goals {d['avgGoals']} | "
              f"home {d['homeWinPct']}% draw {d['drawPct']}%")
        print("    top:", ", ".join(f"{t} {r:.0f}" for t, r in top))
