"""Live tournament state: recorded results + online rating updates.

Actual results are stored in data/results.json. Live team-rating deltas are
computed by *replaying* those results through an online Elo update on top of the
trained baseline — so recording, editing, removing, or auto-syncing results is
idempotent (no double-counting). Standings are derived from the same store.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections import defaultdict
from datetime import datetime

import secure

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
RESULTS_FILE = os.path.join(DATA_DIR, "results.json")

K = 30.0            # online Elo step per match
HOME_ADV = 65.0     # Elo home edge for non-neutral matches

_lock = threading.Lock()


def _load() -> list:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save(rows: list) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


def record_result(home: str, away: str, gh: int, ga: int, neutral: bool = True,
                  source: str = "manual", ext_id: str | None = None) -> dict:
    """Add or overwrite a result (keyed by ext_id, else the home|away fixture)."""
    rows = _load()
    key = ext_id or f"{home}|{away}"
    rec = {"key": key, "home": home, "away": away, "gh": int(gh), "ga": int(ga),
           "neutral": bool(neutral), "source": source,
           "ts": datetime.now().isoformat(timespec="seconds")}
    with _lock:
        rows = [r for r in rows if r.get("key") != key]
        rows.append(rec)
        rows.sort(key=lambda r: r["ts"])
        _save(rows)
    return rec


def results() -> list:
    return sorted(_load(), key=lambda r: r.get("ts", ""))


def remove(key: str) -> None:
    with _lock:
        _save([r for r in _load() if r.get("key") != key])


def reset() -> None:
    with _lock:
        _save([])


def deltas() -> dict:
    """Replay all stored results through online Elo -> per-team delta."""
    d: dict = defaultdict(float)
    for r in results():
        h, a = r["home"], r["away"]
        rh = secure.trained_elo(h) + d[h]
        ra = secure.trained_elo(a) + d[a]
        ha = 0.0 if r.get("neutral", True) else HOME_ADV
        exp_h = 1.0 / (1.0 + 10 ** (-((rh + ha) - ra) / 400.0))
        gh, ga = r["gh"], r["ga"]
        sc = 1.0 if gh > ga else (0.5 if gh == ga else 0.0)
        mult = math.log(max(abs(gh - ga), 1) + 1)
        ch = K * mult * (sc - exp_h)
        d[h] += ch
        d[a] -= ch
    return {t: round(v, 2) for t, v in d.items()}


def get_delta(team: str) -> float:
    return deltas().get(team, 0.0)


def effective_elo_disp(team: str) -> float:
    return secure.trained_elo(team) + deltas().get(team, 0.0)


def all_deltas() -> dict:
    return deltas()


def table() -> list:
    """Every team that has played, with its tournament delta + effective Elo."""
    d = deltas()
    rows = [{"team": t, "delta": round(v, 1),
             "elo": round(secure.trained_elo(t) + v, 1)} for t, v in d.items()]
    rows.sort(key=lambda r: r["delta"], reverse=True)
    return rows
