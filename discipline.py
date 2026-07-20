"""Fouls x cards discipline analysis — the "referee favour" index.

Some teams foul freely and rarely get booked while their opponents are carded
for less; others get whistled tight both ways. Per team, across every played
WC match, this module aggregates:

    foulsCommitted / own cards  (yellow + 2x red)
    opponent fouls / opponent cards

and turns them into cards-per-10-fouls rates. The favour index is

    favour = oppCardsPer10Fouls - ownCardsPer10Fouls

(positive = referees punish their opponents more readily than them, per foul —
the team is "protected"). A small Elo bonus is granted in proportion, capped:
protected teams keep 11 men on the pitch and their opponents accumulate
suspensions.

Cache: data/discipline.json (one ESPN summary pass over all played matches;
refresh via POST /api/refresh_discipline or python discipline.py).
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

import form

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CACHE_FILE = os.path.join(DATA_DIR, "discipline.json")
CACHE_TTL = 3600 * 6

RED_WEIGHT = 2.0          # a red counts as this many yellows in the card rate
REF_ELO_PER_RATE = 4.0    # Elo per (cards/10 fouls) of favour differential
REF_ELO_CAP = 8.0         # max discipline Elo adjustment either way

_mem: dict = {}
_mem_ts: float = 0.0


def _load() -> dict:
    global _mem, _mem_ts
    now = time.time()
    if _mem and now - _mem_ts < CACHE_TTL:
        return _mem
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _mem, _mem_ts = json.load(f), now
                return _mem
        except Exception:
            pass
    return {}


def analyze(force: bool = False) -> dict:
    """One pass over every completed WC match: per-team fouls/cards for and
    against, rates, favour index, and the resulting Elo adjustment."""
    if not force:
        cached = _load()
        if cached:
            return cached

    sess = form._session()
    WEB = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
    API = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"
    today = datetime.utcnow().strftime("%Y%m%d") if hasattr(datetime, "utcnow") else "20260731"
    agg = defaultdict(lambda: defaultdict(float))

    r = sess.get(f"{WEB}?dates=20260611-{today}&limit=250", timeout=20)
    for ev in r.json().get("events", []):
        if ev.get("status", {}).get("type", {}).get("state") != "post":
            continue
        try:
            dj = sess.get(f"{API}?event={ev['id']}", timeout=12).json()
        except Exception:
            continue
        sides = {}
        for tb in dj.get("boxscore", {}).get("teams", []):
            team = form._canonical_team(tb.get("team", {}).get("displayName", ""))
            st = {}
            for s in tb.get("statistics", []):
                if not isinstance(s, dict) or not s.get("name"):
                    continue
                try:
                    st[s["name"]] = float(s.get("value") if s.get("value") is not None
                                          else s.get("displayValue") or 0)
                except (ValueError, TypeError):
                    pass
            sides[tb.get("homeAway", "")] = (team, st)
        if len(sides) != 2:
            continue
        for side, (team, st) in sides.items():
            other = sides["away" if side == "home" else "home"][1]
            a = agg[team]
            a["matches"] += 1
            a["fouls"] += st.get("foulsCommitted", 0)
            a["yc"] += st.get("yellowCards", 0)
            a["rc"] += st.get("redCards", 0)
            a["oppFouls"] += other.get("foulsCommitted", 0)
            a["oppYc"] += other.get("yellowCards", 0)
            a["oppRc"] += other.get("redCards", 0)
        time.sleep(0.03)

    teams = {}
    for team, a in agg.items():
        own_cards = a["yc"] + RED_WEIGHT * a["rc"]
        opp_cards = a["oppYc"] + RED_WEIGHT * a["oppRc"]
        own_rate = own_cards / a["fouls"] * 10 if a["fouls"] else 0.0
        opp_rate = opp_cards / a["oppFouls"] * 10 if a["oppFouls"] else 0.0
        favour = opp_rate - own_rate
        delta = max(-REF_ELO_CAP, min(REF_ELO_CAP, favour * REF_ELO_PER_RATE))
        teams[team] = {
            "matches": int(a["matches"]),
            "fouls": int(a["fouls"]), "yellow": int(a["yc"]), "red": int(a["rc"]),
            "oppFouls": int(a["oppFouls"]), "oppYellow": int(a["oppYc"]),
            "oppRed": int(a["oppRc"]),
            "ownCardsPer10Fouls": round(own_rate, 2),
            "oppCardsPer10Fouls": round(opp_rate, 2),
            "favour": round(favour, 2),
            "refDelta": round(delta, 1),
        }

    out = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "teams": teams, "teamCount": len(teams)}
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    global _mem, _mem_ts
    _mem, _mem_ts = out, time.time()
    return out


def get_delta(team: str) -> float:
    """Discipline (referee-favour) Elo adjustment for a team; 0 if unknown."""
    t = _load().get("teams", {}).get(team)
    return t["refDelta"] if t else 0.0


def table() -> list[dict]:
    d = _load()
    rows = [{"team": t, **v} for t, v in d.get("teams", {}).items()]
    rows.sort(key=lambda r: -r["favour"])
    return rows


if __name__ == "__main__":
    d = analyze(force=True)
    print(f"Analyzed {d['teamCount']} teams\n")
    rows = sorted(d["teams"].items(), key=lambda kv: -kv[1]["favour"])
    print(f"{'Team':<20}{'own c/10f':>10}{'opp c/10f':>10}{'favour':>8}{'Elo':>6}")
    for t, v in rows[:12] + [("...", None)] + rows[-6:]:
        if v is None:
            print("   ...")
            continue
        print(f"{t:<20}{v['ownCardsPer10Fouls']:>10}{v['oppCardsPer10Fouls']:>10}"
              f"{v['favour']:>8}{v['refDelta']:>6}")
