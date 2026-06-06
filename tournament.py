"""Monte Carlo simulator for the 48-team / 12-group 2026 World Cup format.

Uses the encrypted trained engine (Dixon-Coles + GBM) for every match, by team
name. Optional per-team `deltas` carry the starting-XI Elo adjustment so lineup
choices flow into the simulation.

Format: 12 groups of 4 -> 12 winners + 12 runners-up + 8 best third-placed
teams = 32-team knockout (R32 -> R16 -> QF -> SF -> Final).
"""

from __future__ import annotations

import random
from collections import defaultdict

from model import expected_goals
import secure

STAGES = ["round32", "round16", "quarter", "semi", "final", "champion"]
KNOCKOUT_NAMES = ["round16", "quarter", "semi", "final", "champion"]


def _poisson_sample(lam: float, rng: random.Random) -> int:
    l = pow(2.718281828459045, -lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= l:
            return k - 1


def _build_cache(groups, deltas):
    """Precompute expected goals for every team pairing once (the engine /
    gradient-boosting call is far too slow to run inside the Monte Carlo loop)."""
    all_teams = [t for teams in groups.values() for t in teams]
    cache = {"_deltas": deltas}
    for a in all_teams:
        for b in all_teams:
            if a != b and (a, b) not in cache:
                cache[(a, b)] = expected_goals(a, b, deltas.get(a, 0.0), deltas.get(b, 0.0))
    return cache


def _simulate_goals(a, b, cache, rng):
    lam_a, lam_b = cache[(a, b)]
    return _poisson_sample(lam_a, rng), _poisson_sample(lam_b, rng)


def _knockout_winner(a, b, cache, rng):
    ga, gb = _simulate_goals(a, b, cache, rng)
    if ga > gb:
        return a
    if gb > ga:
        return b
    edge = (secure.trained_elo(a) - secure.trained_elo(b)) * 0.0005
    return a if rng.random() < 0.5 + edge else b


def simulate_group(teams, cache, rng):
    pts = defaultdict(int); gd = defaultdict(int); gf = defaultdict(int)
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            a, b = teams[i], teams[j]
            ga, gb = _simulate_goals(a, b, cache, rng)
            gf[a] += ga; gf[b] += gb
            gd[a] += ga - gb; gd[b] += gb - ga
            if ga > gb:
                pts[a] += 3
            elif gb > ga:
                pts[b] += 3
            else:
                pts[a] += 1; pts[b] += 1
    ranked = sorted(teams, key=lambda t: (pts[t], gd[t], gf[t], rng.random()), reverse=True)
    return ranked, {t: (pts[t], gd[t], gf[t]) for t in teams}


def simulate_once(groups, cache, rng):
    winners, runners, thirds = [], [], []
    for teams in groups.values():
        ranked, stats = simulate_group(teams, cache, rng)
        winners.append(ranked[0]); runners.append(ranked[1])
        thirds.append((ranked[2], stats[ranked[2]]))

    thirds.sort(key=lambda ts: ts[1], reverse=True)
    best_thirds = [t for t, _ in thirds[:8]]

    qualifiers = winners + runners + best_thirds
    seeded = sorted(qualifiers,
                    key=lambda t: secure.trained_elo(t) + cache["_deltas"].get(t, 0.0),
                    reverse=True)
    pairs = [(seeded[i], seeded[31 - i]) for i in range(16)]

    reached = {"round32": list(qualifiers)}
    current = pairs
    for name in KNOCKOUT_NAMES:
        win = [_knockout_winner(a, b, cache, rng) for a, b in current]
        reached[name] = win
        current = list(zip(win[0::2], win[1::2]))
    return reached


def run_simulation(groups, deltas=None, n: int = 10000, seed: int | None = None):
    """Run N tournaments; return each team's probability of reaching each stage."""
    deltas = deltas or {}
    rng = random.Random(seed)
    cache = _build_cache(groups, deltas)
    counts = defaultdict(lambda: defaultdict(int))
    for _ in range(n):
        reached = simulate_once(groups, cache, rng)
        for stage in STAGES:
            for team in reached[stage]:
                counts[team][stage] += 1
    return {team: {s: counts[team][s] / n for s in STAGES} for team in counts}
