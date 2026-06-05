"""Squad / starting-XI layer.

Each team has a squad of players with individual ratings (0-100). The starting
XI you pick determines a *lineup strength*; the team's effective Elo is then
nudged up or down from its base rating depending on how strong (or weak) the
chosen XI is relative to the squad's default first eleven.

Squads are generated deterministically from each team's Elo the first time the
app runs, then persisted to squads.json so your edits (lineups, ratings) stick.
"""

from __future__ import annotations

import json
import os
import random

import teams as teams_mod

SQUAD_FILE = os.path.join(os.path.dirname(__file__), "squads.json")

# How many Elo points one average-rating point of the starting XI is worth.
ELO_PER_RATING = 7.0

# A 4-3-3 template: position label + how many of them start.
FORMATION = [("GK", 1), ("DEF", 4), ("MID", 3), ("FWD", 3)]


def _baseline_rating(elo: int) -> float:
    """Map a team's Elo to a typical player rating for that squad."""
    return max(45.0, min(95.0, 50 + (elo - 1600) / 12))


def _generate_squad(team: str, elo: int) -> dict:
    """Build a deterministic 23-man squad around the team's baseline rating."""
    rng = random.Random(hash(team) & 0xFFFFFFFF)
    base = _baseline_rating(elo)
    players: list[dict] = []
    pid = 0

    def add(pos: str, n_start: int, n_total: int):
        nonlocal pid
        for k in range(n_total):
            # Starters cluster near baseline; bench a touch lower.
            bench_penalty = 0 if k < n_start else rng.uniform(3, 9)
            rating = round(base + rng.uniform(-4, 4) - bench_penalty)
            rating = max(40, min(99, rating))
            players.append({
                "id": pid,
                "name": f"{team[:3].upper()} {pos}{k + 1}",
                "pos": pos,
                "rating": rating,
                "starter": k < n_start,
            })
            pid += 1

    add("GK", 1, 3)
    add("DEF", 4, 7)
    add("MID", 3, 7)
    add("FWD", 3, 6)

    starters = [p for p in players if p["starter"]]
    base_avg = sum(p["rating"] for p in starters) / len(starters)
    return {"base_elo": elo, "base_avg": round(base_avg, 2), "players": players}


def load_squads() -> dict:
    """Load squads.json, generating it from teams.ELO on first run."""
    if os.path.exists(SQUAD_FILE):
        with open(SQUAD_FILE, encoding="utf-8") as f:
            return json.load(f)
    squads = {team: _generate_squad(team, elo) for team, elo in teams_mod.ELO.items()}
    save_squads(squads)
    return squads


def save_squads(squads: dict) -> None:
    with open(SQUAD_FILE, "w", encoding="utf-8") as f:
        json.dump(squads, f, indent=2)


def effective_elo(squad: dict) -> float:
    """Team Elo adjusted for the currently selected starting XI."""
    starters = [p for p in squad["players"] if p["starter"]]
    if not starters:
        return squad["base_elo"]
    avg = sum(p["rating"] for p in starters) / len(starters)
    return round(squad["base_elo"] + (avg - squad["base_avg"]) * ELO_PER_RATING, 1)


def effective_elo_map(squads: dict) -> dict[str, float]:
    return {team: effective_elo(sq) for team, sq in squads.items()}
