"""Official 2026 World Cup knockout bracket, per the published FIFA/FOX
broadcast bracket graphic. R32 is ordered left-half-then-right-half, top to
bottom, so every later round is just consecutive pairs of the previous
round's winners: R16 pairs (1,2)(3,4).., QF pairs the R16 winners the same
way, and so on. This mirrors how the bracket actually branches.

Team names are normalised to teams.py / squads.json.
"""

from __future__ import annotations

import time

import form

# Round of 32 — left half (1-8), then right half (9-16), top to bottom.
R32 = [
    ("Germany", "Paraguay"),                     # 1
    ("France", "Sweden"),                        # 2
    ("South Africa", "Canada"),                  # 3
    ("Netherlands", "Morocco"),                  # 4
    ("Portugal", "Croatia"),                      # 5
    ("Spain", "Austria"),                        # 6
    ("United States", "Bosnia and Herzegovina"), # 7
    ("Belgium", "Senegal"),                      # 8
    ("Brazil", "Japan"),                         # 9
    ("Ivory Coast", "Norway"),                   # 10
    ("Mexico", "Ecuador"),                       # 11
    ("England", "DR Congo"),                     # 12
    ("Argentina", "Cape Verde"),                 # 13
    ("Australia", "Egypt"),                      # 14
    ("Switzerland", "Algeria"),                  # 15
    ("Colombia", "Ghana"),                       # 16
]

# Every later round pairs consecutive winners of the previous round:
# tie 1&2 -> next tie 1, tie 3&4 -> next tie 2, etc. Matches the bracket tree.
R16_MAP = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16)]
QF_MAP = [(1, 2), (3, 4), (5, 6), (7, 8)]
SF_MAP = [(1, 2), (3, 4)]
FINAL_MAP = [(1, 2)]

ROUNDS = [
    ("Round of 16", R16_MAP),
    ("Quarter-finals", QF_MAP),
    ("Semi-finals", SF_MAP),
    ("Final", FINAL_MAP),
]

_KO_CACHE: dict = {"ts": 0.0, "data": {}}
_KO_TTL = 60.0


def live_results() -> dict:
    """Played/live knockout ties from ESPN, keyed both team-orderings ->
    {gh, ga, winner, state, id}. The winner comes from ESPN's flag, so
    penalty shootouts (a 1-1 that one side advances from) resolve correctly.
    Cached ~60s so the bracket can be refreshed freely."""
    now = time.time()
    if _KO_CACHE["data"] and now - _KO_CACHE["ts"] < _KO_TTL:
        return _KO_CACHE["data"]
    out: dict = {}
    try:
        sess = form._session()
        r = sess.get(f"{form.ESPN_BOARD}?dates=20260628-20260720&limit=90", timeout=12)
        for ev in r.json().get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            cs = comp.get("competitors", [])
            home = next((c for c in cs if c.get("homeAway") == "home"), {})
            away = next((c for c in cs if c.get("homeAway") == "away"), {})
            h = form._canonical_team(home.get("team", {}).get("displayName", ""))
            a = form._canonical_team(away.get("team", {}).get("displayName", ""))
            if not h or not a or "Winner" in h or "Winner" in a:
                continue
            stype = ev.get("status", {}).get("type", {})
            state = stype.get("state", "pre")
            winner = h if home.get("winner") else (a if away.get("winner") else None)
            gh = int(home.get("score") or 0)
            ga = int(away.get("score") or 0)
            venue = (comp.get("venue", {}) or {}).get("fullName", "")
            date = str(ev.get("date", ""))[:10]
            rec = {"gh": gh, "ga": ga, "winner": winner, "state": state,
                   "status": stype.get("name", ""),
                   "id": str(ev.get("id", "")), "venue": venue, "date": date}
            out[(h, a)] = rec
            out[(a, h)] = {**rec, "gh": ga, "ga": gh}
    except Exception:
        pass
    if out:
        _KO_CACHE["ts"], _KO_CACHE["data"] = now, out
    return out
