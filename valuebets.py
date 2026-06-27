"""Value-bet engine + track-record ledger.

A high win rate doesn't mean profit — profit needs the model's probability to
beat the bookmaker's price. This module:

  * compares the model's 1X2 probabilities against bookmaker decimal odds,
  * computes the de-vigged market view and the EV (edge) of each outcome,
  * flags genuine value (model prob > the raw price-implied prob),
  * logs the bets you take to a ledger, settles them against real results, and
    reports your true win rate, ROI and P/L.

Odds come from the odds API when a match is listed, or you enter them manually.
Ledger: data/valuebets.jsonl (runtime data, gitignored).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import live as live_mod

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
LEDGER = os.path.join(DATA_DIR, "valuebets.jsonl")

EDGE_THRESHOLD = 0.03   # only flag value when EV >= +3% (filters noise)
_OUTCOMES = ("home", "draw", "away")


def devig(oh: float, od: float, oa: float) -> dict:
    """Bookmaker decimal odds -> de-vigged implied probabilities + overround."""
    raw = {"home": 1.0 / oh, "draw": 1.0 / od, "away": 1.0 / oa}
    over = sum(raw.values())
    return {"implied": {k: v / over for k, v in raw.items()},
            "rawImplied": raw, "overround": over}


def evaluate(model_probs: dict, odds: dict) -> dict:
    """model_probs {home,draw,away}; odds {home,draw,away} decimal.
    Returns per-outcome edge analysis and the best value pick."""
    dv = devig(odds["home"], odds["draw"], odds["away"])
    rows = []
    for k in _OUTCOMES:
        p = model_probs[k]
        o = odds[k]
        ev = p * o - 1.0                       # profit per 1 unit staked
        rows.append({
            "outcome": k,
            "modelProb": round(p, 4),
            "marketProb": round(dv["implied"][k], 4),
            "odds": o,
            "ev": round(ev, 4),
            "edge": round(p - 1.0 / o, 4),     # model prob vs raw price-implied
            "value": ev >= EDGE_THRESHOLD,
        })
    value = [r for r in rows if r["value"]]
    best = max(value, key=lambda r: r["ev"]) if value else None
    return {"rows": rows, "best": best, "overround": round(dv["overround"], 4)}


# ------------------------------------------------------------------ ledger --

def _read() -> list:
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _write(rows: list) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def log_bet(home: str, away: str, pick: str, odds: float, stake: float = 1.0,
            model_prob: float | None = None, note: str = "") -> dict:
    """Record a bet taken. pick in {home,draw,away}."""
    rows = _read()
    rec = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
        "home": home, "away": away, "pick": pick,
        "odds": float(odds), "stake": float(stake),
        "modelProb": model_prob, "note": note,
        "placed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "pending", "pnl": None,
    }
    rows.append(rec)
    _write(rows)
    return rec


def remove_bet(bet_id: str) -> None:
    _write([r for r in _read() if r.get("id") != bet_id])


def settle() -> dict:
    """Settle pending bets against recorded results. 1X2 has no push."""
    rows = _read()
    res = {(r["home"], r["away"]): r for r in live_mod.results()}
    settled = 0
    for b in rows:
        if b.get("status") != "pending":
            continue
        m = res.get((b["home"], b["away"])) or res.get((b["away"], b["home"]))
        if not m:
            continue
        # outcome from the bet's home/away orientation
        gh, ga = m["gh"], m["ga"]
        if (m["home"], m["away"]) != (b["home"], b["away"]):
            gh, ga = ga, gh   # stored result is reversed vs the bet
        outcome = "home" if gh > ga else ("away" if ga > gh else "draw")
        won = (b["pick"] == outcome)
        b["status"] = "won" if won else "lost"
        b["result"] = f"{gh}-{ga}"
        b["pnl"] = round(b["stake"] * (b["odds"] - 1.0) if won else -b["stake"], 3)
        settled += 1
    _write(rows)
    return {"settled": settled}


def summary() -> dict:
    rows = _read()
    done = [r for r in rows if r.get("status") in ("won", "lost")]
    staked = sum(r["stake"] for r in done)
    pnl = sum(r["pnl"] for r in done if r["pnl"] is not None)
    wins = sum(1 for r in done if r["status"] == "won")
    return {
        "bets": rows,
        "pending": sum(1 for r in rows if r.get("status") == "pending"),
        "settled": len(done),
        "wins": wins,
        "winRate": round(wins / len(done) * 100, 1) if done else None,
        "staked": round(staked, 2),
        "pnl": round(pnl, 2),
        "roi": round(pnl / staked * 100, 1) if staked else None,
    }
