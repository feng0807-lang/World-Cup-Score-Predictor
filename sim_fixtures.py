"""Simulate every unplayed group-stage fixture N times and derive expected
Elo deltas from the results.

Each unplayed fixture is sampled N times from the Poisson scoreline
distribution. The probability-weighted Elo change for each simulation is
averaged to give an *expected* delta per match, which is then summed per team
and stored in data/sim_ratings.json.

This is a separate rating layer — it never mixes with data/results.json (actual
results). Both are included in effective ratings so Match Predictor and
Tournament simulation automatically reflect simulated form.

Usage:
    from sim_fixtures import simulate_all, get_delta, reset
"""

from __future__ import annotations

import json
import math
import os
import random
import threading
from collections import defaultdict
from datetime import datetime

import secure
import fixtures as fixtures_mod
import live as live_mod

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SIM_FILE = os.path.join(DATA_DIR, "sim_ratings.json")

K = 30.0
_lock = threading.Lock()


def _poisson_sample(lam: float, rng: random.Random) -> int:
    l = pow(2.718281828459045, -lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l:
            return k - 1


def _load_store() -> dict:
    if os.path.exists(SIM_FILE):
        with open(SIM_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_store(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SIM_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_delta(team: str) -> float:
    return _load_store().get("deltas", {}).get(team, 0.0)


def all_deltas() -> dict:
    return _load_store().get("deltas", {})


def meta() -> dict:
    store = _load_store()
    return {k: v for k, v in store.items() if k != "deltas"}


def reset() -> None:
    with _lock:
        _save_store({})


def simulate_all(n: int = 1000, elos: dict | None = None) -> dict:
    """Simulate all unplayed fixtures n times each.

    elos: per-team calibrated Elo (squads.json base + lineup + live + coach +
    form). Sim deltas are deliberately EXCLUDED by the caller to avoid circular
    feedback. If None, falls back to the engine's trained Elo.

    Returns per-fixture stats and writes expected team Elo deltas to
    data/sim_ratings.json.
    """
    from model import expected_goals_calibrated, home_advantage

    if not elos:
        elos = {}

    def _elo(team):
        return elos.get(team) if elos.get(team) is not None else secure.trained_elo(team)

    played: set[str] = set()
    for r in live_mod.results():
        played.add(f"{r['home']}|{r['away']}")
        played.add(f"{r['away']}|{r['home']}")

    unplayed = [f for f in fixtures_mod.all_fixtures()
                if f"{f['home']}|{f['away']}" not in played]

    rng = random.Random()
    team_sum: dict[str, float] = defaultdict(float)
    matches = []

    for fix in unplayed:
        h, a = fix["home"], fix["away"]
        rh, ra = _elo(h), _elo(a)
        ha = home_advantage(h)
        lam_h, lam_a = expected_goals_calibrated(h, a, rh, ra, home_adv=ha)

        exp_h = 1.0 / (1.0 + 10 ** (-((rh + ha) - ra) / 400.0))

        wins_h = draws = wins_a = 0
        gh_total = ga_total = 0
        elo_sum = 0.0

        for _ in range(n):
            gh = _poisson_sample(lam_h, rng)
            ga = _poisson_sample(lam_a, rng)
            gh_total += gh
            ga_total += ga
            if gh > ga:
                wins_h += 1
                sc = 1.0
            elif gh == ga:
                draws += 1
                sc = 0.5
            else:
                wins_a += 1
                sc = 0.0
            mult = math.log(max(abs(gh - ga), 1) + 1)
            elo_sum += K * mult * (sc - exp_h)

        exp_dh = elo_sum / n
        team_sum[h] += exp_dh
        team_sum[a] -= exp_dh

        matches.append({
            "group": fix["group"],
            "date": fix["date"],
            "home": h,
            "away": a,
            "pHome": round(wins_h / n, 3),
            "pDraw": round(draws / n, 3),
            "pAway": round(wins_a / n, 3),
            "xHome": round(gh_total / n, 2),
            "xAway": round(ga_total / n, 2),
            "expEloDeltaHome": round(exp_dh, 2),
        })

    deltas = {t: round(v, 2) for t, v in team_sum.items()}

    with _lock:
        _save_store({
            "deltas": deltas,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "runs": n,
            "matchCount": len(unplayed),
        })

    return {
        "matches": matches,
        "teamDeltas": deltas,
        "unplayedCount": len(unplayed),
        "runs": n,
    }
