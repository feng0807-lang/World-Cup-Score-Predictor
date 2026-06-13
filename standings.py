"""Live group standings + projected knockout bracket from recorded results."""

from __future__ import annotations

import teams as teams_mod
import fixtures as fixtures_mod
import live as live_mod
import secure

_GROUP_OF = {t: g for g, ts in teams_mod.GROUPS.items() for t in ts}
_FIXTURE_PAIRS = {frozenset((h, a)) for (_, _, h, a, _) in fixtures_mod.FIXTURES}


def _blank(team: str) -> dict:
    return {"team": team, "P": 0, "W": 0, "D": 0, "L": 0,
            "GF": 0, "GA": 0, "GD": 0, "Pts": 0}


def standings() -> dict:
    """Per-group table sorted by Pts, GD, GF (group-stage results only)."""
    tab = {t: _blank(t) for t in _GROUP_OF}
    for r in live_mod.results():
        h, a = r["home"], r["away"]
        if frozenset((h, a)) not in _FIXTURE_PAIRS:
            continue  # only count real group fixtures
        if _GROUP_OF.get(h) != _GROUP_OF.get(a):
            continue
        gh, ga = r["gh"], r["ga"]
        for t, gf, gaa in ((h, gh, ga), (a, ga, gh)):
            row = tab[t]
            row["P"] += 1; row["GF"] += gf; row["GA"] += gaa; row["GD"] += gf - gaa
        if gh > ga:
            tab[h]["W"] += 1; tab[h]["Pts"] += 3; tab[a]["L"] += 1
        elif gh < ga:
            tab[a]["W"] += 1; tab[a]["Pts"] += 3; tab[h]["L"] += 1
        else:
            tab[h]["D"] += 1; tab[a]["D"] += 1; tab[h]["Pts"] += 1; tab[a]["Pts"] += 1

    out = {}
    for g, members in teams_mod.GROUPS.items():
        rows = sorted((tab[t] for t in members),
                      key=lambda r: (r["Pts"], r["GD"], r["GF"]), reverse=True)
        out[g] = rows
    return out


def bracket() -> dict:
    """Projected Round of 32 from current standings: 12 winners + 12 runners-up
    + 8 best third-placed, seeded by effective Elo (model projection)."""
    tab = standings()
    winners, runners, thirds = [], [], []
    for g, rows in tab.items():
        winners.append(rows[0]["team"])
        runners.append(rows[1]["team"])
        thirds.append(rows[2])
    thirds.sort(key=lambda r: (r["Pts"], r["GD"], r["GF"]), reverse=True)
    best_thirds = [r["team"] for r in thirds[:8]]

    qualifiers = winners + runners + best_thirds
    eff = {t: secure.trained_elo(t) + live_mod.get_delta(t) for t in qualifiers}
    seeded = sorted(qualifiers, key=lambda t: eff[t], reverse=True)
    pairs = [{"a": seeded[i], "b": seeded[31 - i]} for i in range(16)]

    played = sum(r["P"] for rows in tab.values() for r in rows) // 2
    return {"qualifiers": qualifiers, "r32": pairs,
            "winners": winners, "runners": runners, "bestThirds": best_thirds,
            "matchesPlayed": played, "projected": played < 72}
