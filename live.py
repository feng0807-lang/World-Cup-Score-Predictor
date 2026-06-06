"""Live team-rating updates during the tournament.

After each finished 2026 match you enter the result; an online Elo update bumps
both teams. The change is stored as a per-team *delta* (in Elo points) on top of
the trained baseline, and fed into predictions and the simulation through the
same strength-adjustment path used by lineups and weather — so later forecasts
reflect tournament form.

Persisted to data/live_ratings.json so it survives restarts.
"""

from __future__ import annotations

import json
import math
import os
import threading

import secure

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FILE = os.path.join(DATA_DIR, "live_ratings.json")

K = 30.0            # update step per match (a touch gentler than the historical fit)
HOME_ADV = 65.0     # Elo home edge applied only for non-neutral matches

_lock = threading.Lock()


def _load() -> dict:
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(d: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def get_delta(team: str) -> float:
    return float(_load().get(team, 0.0))


def all_deltas() -> dict:
    return {t: float(v) for t, v in _load().items()}


def effective_elo(team: str) -> float:
    return secure.trained_elo(team) + get_delta(team)


def update_result(home: str, away: str, gh: int, ga: int,
                  neutral: bool = True) -> dict:
    """Apply one finished result; returns the updated deltas + ratings."""
    deltas = _load()
    dh = float(deltas.get(home, 0.0))
    da = float(deltas.get(away, 0.0))
    rh = secure.trained_elo(home) + dh
    ra = secure.trained_elo(away) + da
    ha = 0.0 if neutral else HOME_ADV

    exp_h = 1.0 / (1.0 + 10 ** (-((rh + ha) - ra) / 400.0))
    if gh > ga:
        score_h = 1.0
    elif gh < ga:
        score_h = 0.0
    else:
        score_h = 0.5
    margin = math.log(max(abs(gh - ga), 1) + 1)   # bigger wins move ratings more

    change = K * margin * (score_h - exp_h)
    deltas[home] = round(dh + change, 2)
    deltas[away] = round(da - change, 2)
    with _lock:
        _save(deltas)
    return {
        "home": home, "away": away, "score": f"{gh}-{ga}", "neutral": neutral,
        "change": round(change, 2),
        "home_delta": deltas[home], "away_delta": deltas[away],
        "home_elo": round(secure.trained_elo(home) + deltas[home], 1),
        "away_elo": round(secure.trained_elo(away) + deltas[away], 1),
    }


def reset() -> None:
    with _lock:
        _save({})


def table() -> list[dict]:
    """Every team that has played, with its tournament delta + effective Elo."""
    d = _load()
    rows = [{"team": t, "delta": round(v, 1),
             "elo": round(secure.trained_elo(t) + v, 1)} for t, v in d.items()]
    rows.sort(key=lambda r: r["delta"], reverse=True)
    return rows
