"""Official 2026 World Cup knockout bracket (fetched from ESPN once the group
stage completed). The R32 matchups are the real draw; the *_MAP tables encode
how each round feeds the next (1-indexed slots into the previous round's
winners), taken from ESPN's bracket placeholders
("Round of 32 N Winner vs Round of 32 M Winner").

Team names are normalised to teams.py / squads.json.
"""

from __future__ import annotations

import time

import form

# Round of 32 in official slot order (ESPN match-number / event-id order).
R32 = [
    ("South Africa", "Canada"),                 # 1
    ("Brazil", "Japan"),                         # 2
    ("Netherlands", "Morocco"),                  # 3
    ("Germany", "Paraguay"),                     # 4
    ("Ivory Coast", "Norway"),                   # 5
    ("Mexico", "Ecuador"),                       # 6
    ("France", "Sweden"),                        # 7
    ("Belgium", "Senegal"),                      # 8
    ("United States", "Bosnia and Herzegovina"), # 9
    ("England", "DR Congo"),                     # 10
    ("Portugal", "Croatia"),                     # 11
    ("Spain", "Austria"),                        # 12
    ("Switzerland", "Algeria"),                  # 13
    ("Australia", "Egypt"),                      # 14
    ("Argentina", "Cape Verde"),                 # 15
    ("Colombia", "Ghana"),                       # 16
]

# Each later round: list of (slotA, slotB), 1-indexed into the previous round's
# winners. From ESPN's R16/QF/SF/Final placeholder fixtures.
R16_MAP = [(1, 3), (2, 5), (4, 6), (7, 8), (11, 12), (9, 10), (13, 15), (14, 16)]
QF_MAP = [(1, 2), (5, 6), (3, 4), (7, 8)]
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
            state = ev.get("status", {}).get("type", {}).get("state", "pre")
            winner = h if home.get("winner") else (a if away.get("winner") else None)
            gh = int(home.get("score") or 0)
            ga = int(away.get("score") or 0)
            out[(h, a)] = {"gh": gh, "ga": ga, "winner": winner,
                           "state": state, "id": str(ev.get("id", ""))}
            out[(a, h)] = {"gh": ga, "ga": gh, "winner": winner,
                           "state": state, "id": str(ev.get("id", ""))}
    except Exception:
        pass
    if out:
        _KO_CACHE["ts"], _KO_CACHE["data"] = now, out
    return out
