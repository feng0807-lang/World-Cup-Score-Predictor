"""Coach / manager factor.

A registry of each team's coach (name, appointment timing, and an Elo-point
adjustment). The adjustment feeds the rating mix like lineup/weather. Defaults
are 0 — it's a structured judgement knob + a record of who's in charge — but a
coach appointed right before the tournament can be flagged for a small
"new-manager" effect. Persisted to data/coaches.json so edits survive.

Honest note: manager effect on match outcomes is a small, noisy signal; treat
adjustments as opinion, not a validated accuracy boost.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FILE = os.path.join(DATA_DIR, "coaches.json")

# Seed: known 2026 coaches ("since": pre = long-serving, new = appointed close
# to the tournament). adj in Elo points (default 0; edit to taste).
SEED: dict[str, dict] = {
    "Argentina": {"name": "Lionel Scaloni", "since": "pre"},
    "Brazil": {"name": "Carlo Ancelotti", "since": "new"},
    "France": {"name": "Didier Deschamps", "since": "pre"},
    "Spain": {"name": "Luis de la Fuente", "since": "pre"},
    "England": {"name": "Thomas Tuchel", "since": "new"},
    "Portugal": {"name": "Roberto Martínez", "since": "pre"},
    "Germany": {"name": "Julian Nagelsmann", "since": "pre"},
    "Netherlands": {"name": "Ronald Koeman", "since": "pre"},
    "Belgium": {"name": "Rudi Garcia", "since": "pre"},
    "Croatia": {"name": "Zlatko Dalić", "since": "pre"},
    "Morocco": {"name": "Walid Regragui", "since": "pre"},
    "Uruguay": {"name": "Marcelo Bielsa", "since": "pre"},
    "Colombia": {"name": "Néstor Lorenzo", "since": "pre"},
    "United States": {"name": "Mauricio Pochettino", "since": "new"},
    "Mexico": {"name": "Javier Aguirre", "since": "pre"},
    "Canada": {"name": "Jesse Marsch", "since": "pre"},
    "Switzerland": {"name": "Murat Yakin", "since": "pre"},
    "Japan": {"name": "Hajime Moriyasu", "since": "pre"},
    "South Korea": {"name": "Hong Myung-bo", "since": "pre"},
    "Senegal": {"name": "Pape Thiaw", "since": "new"},
    "Egypt": {"name": "Hossam Hassan", "since": "pre"},
    "Iran": {"name": "Amir Ghalenoei", "since": "pre"},
    "Australia": {"name": "Tony Popovic", "since": "new"},
    "Ghana": {"name": "Otto Addo", "since": "pre"},
    "Norway": {"name": "Ståle Solbakken", "since": "pre"},
    "Ecuador": {"name": "Sebastián Beccacece", "since": "pre"},
    "Austria": {"name": "Ralf Rangnick", "since": "pre"},
    "Turkey": {"name": "Vincenzo Montella", "since": "pre"},
}

# Default Elo nudge for a brand-new appointment (small; tunable). 0 by default —
# enable by setting NEW_COACH_ADJ if you believe in the new-manager bounce.
NEW_COACH_ADJ = 0.0


def _load() -> dict:
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(d: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def _entry(team: str) -> dict:
    saved = _load()
    if team in saved:
        return saved[team]
    seed = SEED.get(team, {"name": "—", "since": "pre"})
    return {"name": seed.get("name", "—"), "since": seed.get("since", "pre"),
            "adj": float(seed.get("adj", 0.0))}


def get_delta(team: str) -> float:
    e = _entry(team)
    adj = float(e.get("adj", 0.0))
    if e.get("since") == "new":
        adj += NEW_COACH_ADJ
    return adj


def get(team: str) -> dict:
    return _entry(team)


def all_coaches(teams: list[str]) -> list[dict]:
    return [{"team": t, **_entry(t)} for t in teams]


def update(team: str, name: str | None = None, since: str | None = None,
           adj: float | None = None) -> dict:
    d = _load()
    e = dict(_entry(team))
    if name is not None:
        e["name"] = name
    if since is not None:
        e["since"] = since
    if adj is not None:
        e["adj"] = float(adj)
    d[team] = e
    _save(d)
    return {"team": team, **e}
