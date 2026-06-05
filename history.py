"""Archive of your inputs and simulation runs, for reference and backtracking.

Everything lives in the data/ folder (human-readable JSON):

  data/history.jsonl          append-only log of every input you make
                              (manual match odds, outright odds, lineup saves),
                              each stamped with an ISO timestamp + date.
  data/simulations/*.json     full simulation snapshots — the results PLUS the
                              lineup state (Elo deltas) used, so a run can be
                              reloaded or recomputed later (backtracking).

Snapshot ids are timestamps like 20260605-143012, so files sort by date and you
can browse them straight from the folder.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SIM_DIR = os.path.join(DATA_DIR, "simulations")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")

_lock = threading.Lock()


def _ensure_dirs():
    os.makedirs(SIM_DIR, exist_ok=True)


def _now():
    return datetime.now()


def log_input(kind: str, data: dict) -> dict:
    """Append a timestamped record of something the user entered."""
    _ensure_dirs()
    now = _now()
    rec = {"ts": now.isoformat(timespec="seconds"),
           "date": now.strftime("%Y-%m-%d"),
           "time": now.strftime("%H:%M:%S"),
           "type": kind, "data": data}
    with _lock:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_history(date: str | None = None, kind: str | None = None,
                 limit: int = 200) -> list[dict]:
    """Most-recent-first journal, optionally filtered by date (YYYY-MM-DD)/type."""
    _ensure_dirs()
    if not os.path.exists(HISTORY_FILE):
        return []
    out = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if date and rec.get("date") != date:
                continue
            if kind and rec.get("type") != kind:
                continue
            out.append(rec)
    out.reverse()
    return out[:limit]


def save_simulation(rows: list[dict], runs: int, deltas: dict,
                    label: str = "", market: dict | None = None) -> dict:
    """Persist a full simulation snapshot (results + the lineup state used)."""
    _ensure_dirs()
    now = _now()
    sim_id = now.strftime("%Y%m%d-%H%M%S")
    top = rows[0]["team"] if rows else None
    snapshot = {
        "id": sim_id,
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "label": label or f"Run {now.strftime('%Y-%m-%d %H:%M')}",
        "runs": runs,
        "topPick": top,
        "deltas": {t: round(d, 2) for t, d in deltas.items() if abs(d) > 1e-6},
        "rows": rows,
        "market": market,
    }
    path = os.path.join(SIM_DIR, f"sim_{sim_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    log_input("simulation", {"id": sim_id, "label": snapshot["label"],
                             "runs": runs, "topPick": top})
    return snapshot


def list_simulations() -> list[dict]:
    """Lightweight metadata for every saved snapshot, newest first."""
    _ensure_dirs()
    metas = []
    for fn in os.listdir(SIM_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(SIM_DIR, fn), encoding="utf-8") as f:
                s = json.load(f)
            metas.append({"id": s["id"], "ts": s["ts"], "date": s["date"],
                          "label": s["label"], "runs": s["runs"],
                          "topPick": s.get("topPick"),
                          "lineupChanges": len(s.get("deltas", {}))})
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    metas.sort(key=lambda m: m["ts"], reverse=True)
    return metas


def load_simulation(sim_id: str) -> dict | None:
    path = os.path.join(SIM_DIR, f"sim_{sim_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
