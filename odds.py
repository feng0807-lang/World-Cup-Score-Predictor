"""Bookmaker odds: live via The Odds API, plus manual entry.

Live odds aggregate the world's biggest books (Pinnacle, Bet365, William Hill,
etc.) across the uk/eu/us/au regions in a single API call, which is cached so
many match look-ups cost only one request. Decimal odds are converted to
implied probabilities and "de-vigged" (the bookmaker margin removed).

Set a key via the ODDS_API_KEY env var or an odds_api.key file
(get a free key at https://the-odds-api.com). With no key you can still type
odds in manually; they're stored in manual_odds.json.
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "odds_api.key")
MANUAL_FILE = os.path.join(HERE, "manual_odds.json")
API_BASE = "https://api.the-odds-api.com/v4"
REGIONS = "uk,eu,us,au"
CACHE_TTL = 600  # seconds

# Name aliases: our team name -> alternatives a bookmaker feed might use.
ALIASES = {
    "United States": ["USA", "United States of America"],
    "South Korea": ["Korea Republic", "Korea"],
    "Turkey": ["Türkiye", "Turkiye"],
    "Czechia": ["Czech Republic"],
    "DR Congo": ["Congo DR", "Democratic Republic of the Congo", "Congo"],
    "Ivory Coast": ["Cote d'Ivoire", "Côte d'Ivoire"],
    "Cape Verde": ["Cabo Verde"],
    "Curacao": ["Curaçao"],
}

_cache: dict[str, tuple[float, list, dict]] = {}   # sport_key -> (ts, events, headers)
_sport_key_cache: list = []
_outright_key_cache: list = []
_outright_cache: dict[str, tuple[float, list, dict]] = {}


# ---------------------------------------------------------------- helpers ---
def get_api_key() -> str | None:
    env = os.environ.get("ODDS_API_KEY")
    if env:
        return env.strip()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def save_api_key(key: str) -> None:
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key.strip())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())


def _names_for(team: str) -> list[str]:
    return [team] + ALIASES.get(team, [])


def _same_team(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() > 0.85


def _matches(team: str, candidate: str) -> bool:
    return any(_same_team(n, candidate) for n in _names_for(team))


def _http_get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "wc-predictor"})
    with urllib.request.urlopen(req, timeout=15) as r:
        headers = {k.lower(): v for k, v in r.headers.items()}
        return json.loads(r.read().decode("utf-8")), headers


# ------------------------------------------------------------- live odds ---
def discover_sport_key(key: str) -> str | None:
    """Find the active FIFA World Cup soccer sport key."""
    global _sport_key_cache
    if _sport_key_cache:
        return _sport_key_cache[0]
    data, _ = _http_get(f"{API_BASE}/sports/?apiKey={key}")
    wc = [s for s in data if s.get("group", "").lower().startswith("soccer")
          and "world cup" in s.get("title", "").lower()
          and "women" not in s.get("title", "").lower()]
    # Prefer the men's FIFA World Cup (not qualifiers).
    wc.sort(key=lambda s: ("qualif" in s["title"].lower(), s["key"]))
    if wc:
        _sport_key_cache = [wc[0]["key"]]
        return wc[0]["key"]
    return None


def _fetch_events(key: str):
    sk = discover_sport_key(key)
    if not sk:
        raise RuntimeError("No active FIFA World Cup odds market found.")
    now = time.time()
    if sk in _cache and now - _cache[sk][0] < CACHE_TTL:
        _, events, headers = _cache[sk]
        return events, headers, True
    url = (f"{API_BASE}/sports/{sk}/odds/?apiKey={key}"
           f"&regions={REGIONS}&markets=h2h&oddsFormat=decimal")
    events, headers = _http_get(url)
    _cache[sk] = (now, events, headers)
    return events, headers, False


def _devig(prices: dict[str, float]) -> dict[str, float]:
    """Decimal odds -> de-vigged implied probabilities for home/draw/away."""
    imp = {k: 1.0 / v for k, v in prices.items() if v and v > 1.0}
    s = sum(imp.values())
    return {k: v / s for k, v in imp.items()} if s else {}


def _parse_event(ev: dict, home: str, away: str) -> dict | None:
    eh, ea = ev.get("home_team", ""), ev.get("away_team", "")
    # Allow either orientation.
    if _matches(home, eh) and _matches(away, ea):
        flip = False
    elif _matches(home, ea) and _matches(away, eh):
        flip = True
    else:
        return None

    books = []
    for bk in ev.get("bookmakers", []):
        for mkt in bk.get("markets", []):
            if mkt.get("key") != "h2h":
                continue
            prices = {}
            for o in mkt["outcomes"]:
                nm = o["name"]
                if nm.lower() == "draw":
                    prices["draw"] = o["price"]
                elif _matches(home if not flip else away, nm):
                    prices["home" if not flip else "away"] = o["price"]
                elif _matches(away if not flip else home, nm):
                    prices["away" if not flip else "home"] = o["price"]
            if {"home", "draw", "away"} <= set(prices):
                books.append({"key": bk["key"], "title": bk["title"],
                              "odds": {k: prices[k] for k in ("home", "draw", "away")},
                              "implied": _devig(prices)})
    return books or None


def live_market(home: str, away: str) -> dict:
    key = get_api_key()
    if not key:
        return {"available": False, "reason": "no_api_key"}
    try:
        events, headers, cached = _fetch_events(key)
    except urllib.error.HTTPError as e:
        reason = "bad_api_key" if e.code in (401, 403) else f"api_error_{e.code}"
        return {"available": False, "reason": reason}
    except Exception as e:  # network/timeout/parse — fall back to manual
        return {"available": False, "reason": "api_unreachable", "detail": str(e)}
    books = None
    for ev in events:
        books = _parse_event(ev, home, away)
        if books:
            break
    remaining = headers.get("x-requests-remaining")
    if not books:
        return {"available": False, "reason": "match_not_listed",
                "requestsRemaining": remaining, "cached": cached}
    return {"available": True, "source": "the-odds-api",
            "bookmakers": books, **_consensus(books),
            "requestsRemaining": remaining, "cached": cached}


# --------------------------------------------------------- manual entry ---
def _load_manual() -> dict:
    if os.path.exists(MANUAL_FILE):
        with open(MANUAL_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _mkey(home: str, away: str) -> str:
    return f"{home}|{away}"


def set_manual(home: str, away: str, odds: dict, bookmaker: str = "manual") -> None:
    data = _load_manual()
    data[_mkey(home, away)] = {"bookmaker": bookmaker,
                               "odds": {k: float(odds[k]) for k in ("home", "draw", "away")}}
    with open(MANUAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def manual_market(home: str, away: str) -> dict | None:
    rec = _load_manual().get(_mkey(home, away))
    if not rec:
        return None
    book = {"key": "manual", "title": rec.get("bookmaker", "manual"),
            "odds": rec["odds"], "implied": _devig(rec["odds"])}
    return {"available": True, "source": "manual", "bookmakers": [book],
            **_consensus([book])}


# ------------------------------------------------------------ aggregate ---
def _consensus(books: list[dict]) -> dict:
    """Average de-vigged probabilities + best (highest) decimal odds per outcome."""
    outs = ("home", "draw", "away")
    cons = {}
    for o in outs:
        vals = [b["implied"].get(o) for b in books if b["implied"].get(o)]
        cons[o] = sum(vals) / len(vals) if vals else None
    best = {}
    for o in outs:
        prices = [(b["odds"][o], b["title"]) for b in books if b["odds"].get(o)]
        best[o] = max(prices) if prices else None  # (odds, bookmaker)
    return {"consensus": cons, "bestOdds": best, "bookmakerCount": len(books)}


# ----------------------------------------------------- outright (winner) ---
def discover_outright_key(key: str) -> str | None:
    """Find the FIFA World Cup *winner* (outright) sport key."""
    global _outright_key_cache
    if _outright_key_cache:
        return _outright_key_cache[0]
    data, _ = _http_get(f"{API_BASE}/sports/?apiKey={key}")
    soccer_wc = [s for s in data if s.get("group", "").lower().startswith("soccer")
                 and "world cup" in s.get("title", "").lower()
                 and "women" not in s.get("title", "").lower()]
    # Prefer an explicit "winner" market, then anything flagged has_outrights.
    soccer_wc.sort(key=lambda s: (not s.get("key", "").endswith("_winner"),
                                  not s.get("has_outrights", False)))
    for s in soccer_wc:
        if s["key"].endswith("_winner") or s.get("has_outrights"):
            _outright_key_cache = [s["key"]]
            return s["key"]
    return None


def _fetch_outrights(key: str):
    sk = discover_outright_key(key)
    if not sk:
        raise RuntimeError("No World Cup winner market found.")
    now = time.time()
    if sk in _outright_cache and now - _outright_cache[sk][0] < CACHE_TTL:
        _, events, headers = _outright_cache[sk]
        return events, headers, True
    url = (f"{API_BASE}/sports/{sk}/odds/?apiKey={key}"
           f"&regions={REGIONS}&markets=outrights&oddsFormat=decimal")
    events, headers = _http_get(url)
    _outright_cache[sk] = (now, events, headers)
    return events, headers, False


def _map_outcome(name: str, teams: list[str]) -> str | None:
    for t in teams:
        if _matches(t, name):
            return t
    return None


def _outright_consensus(events: list, teams: list[str]) -> dict:
    """Average de-vigged win probability per team across bookmakers + best odds."""
    per_team_probs: dict[str, list] = {}
    best_odds: dict[str, tuple] = {}
    n_books = 0
    for ev in events:
        for bk in ev.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt.get("key") != "outrights":
                    continue
                n_books += 1
                prices = {}
                for o in mkt["outcomes"]:
                    tm = _map_outcome(o["name"], teams)
                    if tm and o.get("price", 0) > 1:
                        prices[tm] = o["price"]
                        if tm not in best_odds or o["price"] > best_odds[tm][0]:
                            best_odds[tm] = (o["price"], bk["title"])
                # De-vig this book's whole field, then record per-team prob.
                inv = {t: 1.0 / p for t, p in prices.items()}
                s = sum(inv.values())
                if s:
                    for t, v in inv.items():
                        per_team_probs.setdefault(t, []).append(v / s)
    consensus = {t: sum(v) / len(v) for t, v in per_team_probs.items()}
    return {"consensus": consensus, "bestOdds": best_odds, "bookmakerCount": n_books}


def live_outrights(teams: list[str]) -> dict:
    key = get_api_key()
    if not key:
        return {"available": False, "reason": "no_api_key"}
    try:
        events, headers, cached = _fetch_outrights(key)
    except urllib.error.HTTPError as e:
        reason = "bad_api_key" if e.code in (401, 403) else f"api_error_{e.code}"
        return {"available": False, "reason": reason}
    except Exception as e:
        return {"available": False, "reason": "api_unreachable", "detail": str(e)}
    agg = _outright_consensus(events, teams)
    if not agg["consensus"]:
        return {"available": False, "reason": "no_outrights",
                "requestsRemaining": headers.get("x-requests-remaining")}
    return {"available": True, "source": "the-odds-api", **agg,
            "requestsRemaining": headers.get("x-requests-remaining"), "cached": cached}


def set_manual_outrights(odds_map: dict) -> None:
    """odds_map: {team: decimal_odds}. Stored under a reserved key."""
    data = _load_manual()
    data["__outrights__"] = {t: float(v) for t, v in odds_map.items()}
    with open(MANUAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def manual_outrights(teams: list[str]) -> dict | None:
    rec = _load_manual().get("__outrights__")
    if not rec:
        return None
    prices = {t: rec[t] for t in rec if t in teams}
    # Raw implied (1/odds). We don't normalize: a manually-entered partial field
    # can't be de-vigged reliably, so this keeps the bookie's stated chance.
    consensus = {t: 1.0 / p for t, p in prices.items() if p > 1}
    best = {t: (prices[t], "manual") for t in prices}
    return {"available": True, "source": "manual", "consensus": consensus,
            "bestOdds": best, "bookmakerCount": 1}


def get_outrights(teams: list[str]) -> dict:
    live = live_outrights(teams)
    if live.get("available"):
        return live
    manual = manual_outrights(teams)
    if manual:
        manual["requestsRemaining"] = live.get("requestsRemaining")
        return manual
    return {"available": False, "reason": live.get("reason", "no_data"),
            "requestsRemaining": live.get("requestsRemaining")}


def fetch_scores(days: int = 3) -> dict:
    """Recent finished match scores from The Odds API (free with a key).

    Returns {"available": bool, "matches": [{home, away, gh, ga, id, completed}]}
    for the active World Cup sport. Used to auto-update live ratings.
    """
    key = get_api_key()
    if not key:
        return {"available": False, "reason": "no_api_key"}
    try:
        sk = discover_sport_key(key)
        if not sk:
            return {"available": False, "reason": "no_market"}
        url = f"{API_BASE}/sports/{sk}/scores/?apiKey={key}&daysFrom={days}"
        data, headers = _http_get(url)
    except urllib.error.HTTPError as e:
        return {"available": False,
                "reason": "bad_api_key" if e.code in (401, 403) else f"api_error_{e.code}"}
    except Exception as e:
        return {"available": False, "reason": "api_unreachable", "detail": str(e)}

    matches = []
    for ev in data:
        if not ev.get("completed"):
            continue
        sc = {s["name"]: s.get("score") for s in (ev.get("scores") or [])}
        eh, ea = ev.get("home_team"), ev.get("away_team")
        try:
            gh, ga = int(sc.get(eh)), int(sc.get(ea))
        except (TypeError, ValueError):
            continue
        matches.append({"id": ev.get("id"), "home": eh, "away": ea,
                        "gh": gh, "ga": ga, "completed": True})
    return {"available": True, "matches": matches,
            "requestsRemaining": headers.get("x-requests-remaining")}


def to_known_team(name: str, known: list[str]) -> str | None:
    """Map a bookmaker team name to one of our canonical team names."""
    for t in known:
        if _matches(t, name):
            return t
    return None


def get_market(home: str, away: str) -> dict:
    """Prefer live odds; fall back to manual entry; else unavailable."""
    live = live_market(home, away)
    if live.get("available"):
        return live
    manual = manual_market(home, away)
    if manual:
        manual["requestsRemaining"] = live.get("requestsRemaining")
        return manual
    return {"available": False, "reason": live.get("reason", "no_data"),
            "requestsRemaining": live.get("requestsRemaining")}
