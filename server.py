"""Zero-dependency web dashboard server (Python stdlib http.server).

Run:  python server.py     then open  http://localhost:8000

Endpoints
---------
  GET  /                          -> dashboard HTML
  GET  /api/teams                 -> teams + effective Elo
  GET  /api/predict?home=&away=   -> single-match prediction
  GET  /api/simulate?runs=        -> tournament simulation table
  GET  /api/squad?team=           -> a team's squad / starting XI
  POST /api/squad?team=           -> save lineup + ratings, returns new Elo
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import teams as teams_mod
import squads as squads_mod
import secure
import odds as odds_mod
import history as history_mod
import climate as climate_mod
import live as live_mod
import fixtures as fixtures_mod
import standings as standings_mod
import handicap as handicap_mod
import coach as coach_mod
import sim_fixtures as sim_mod
import form as form_mod
import keyplayers as kp_mod
import context as ctx_mod
from model import predict_calibrated, home_advantage
from tournament import run_simulation

HERE = os.path.dirname(__file__)
SQUADS = squads_mod.load_squads()


def _lineup_delta(team: str) -> float:
    """Elo change from the chosen starting XI vs the squad baseline."""
    if team in SQUADS:
        return squads_mod.effective_elo(SQUADS[team]) - SQUADS[team]["base_elo"]
    return 0.0


def _strength_delta(team: str, include_sim: bool = True) -> float:
    """Combined non-weather strength shift vs base Elo: lineup + live + coach + form
    + key-player availability (+ sim, unless excluded to avoid circular feedback
    in the fixture forecaster)."""
    d = (_lineup_delta(team) + live_mod.get_delta(team) + coach_mod.get_delta(team)
         + form_mod.team_form_delta(SQUADS.get(team, {}), team)
         + kp_mod.team_keyplayer_delta(team, SQUADS.get(team, {})))
    if include_sim:
        d += sim_mod.get_delta(team)
    return d


def _calibrated_elo(team: str, include_sim: bool = True) -> float:
    """Team strength on our hand-calibrated scale: squads.json base_elo plus all
    real-world adjustments. This is the single supremacy signal feeding the model
    (the encrypted engine's trained Elo is confederation-biased and used only for
    total-goals shape)."""
    if team not in SQUADS:
        return teams_mod.ELO.get(team, 1500.0)
    return SQUADS[team]["base_elo"] + _strength_delta(team, include_sim)


def _all_deltas() -> dict[str, float]:
    return {t: _strength_delta(t) for t in SQUADS}


def _all_calibrated_elos() -> dict[str, float]:
    return {t: _calibrated_elo(t) for t in SQUADS}


def _elos_from_deltas(deltas: dict) -> dict[str, float]:
    """Reconstruct calibrated Elos from a stored strength-delta snapshot."""
    return {t: SQUADS[t]["base_elo"] + deltas.get(t, 0.0) for t in SQUADS}


def _odds_payload(home: str, away: str, blend: float | None):
    """Model probs vs market consensus, value edges, and optional blend."""
    p = predict_calibrated(home, away, _calibrated_elo(home), _calibrated_elo(away),
                           home_adv=home_advantage(home))
    model = {"home": p.p_home_win, "draw": p.p_draw, "away": p.p_away_win}
    market = odds_mod.get_market(home, away)

    out = {"home": home, "away": away, "model": model, "market": market}
    cons = market.get("consensus") if market.get("available") else None
    if cons and all(cons.get(k) for k in ("home", "draw", "away")):
        out["value"] = {k: round(model[k] - cons[k], 4) for k in model}
        if blend is not None:
            w = max(0.0, min(1.0, blend))
            mix = {k: w * model[k] + (1 - w) * cons[k] for k in model}
            s = sum(mix.values())
            out["blended"] = {k: v / s for k, v in mix.items()}
            out["blendWeight"] = w
    return out


def _sim_rows(runs: int, elos: dict) -> list:
    """Sorted per-team stage probabilities (R32..champion) as percentages."""
    res = run_simulation(teams_mod.GROUPS, elos, n=runs, seed=None)
    ranked = sorted(res.items(), key=lambda kv: kv[1]["champion"], reverse=True)
    return [{"team": t, **{k: round(v * 100, 1) for k, v in probs.items()}}
            for t, probs in ranked]


_sim_cache: dict = {}


def _champion_probs(runs: int) -> dict[str, float]:
    """Monte-Carlo champion probability per team (cached by runs + lineup state)."""
    elos = _all_calibrated_elos()
    key = (runs, tuple(sorted((t, round(e, 1)) for t, e in elos.items())))
    if _sim_cache.get("key") == key:
        return _sim_cache["champ"]
    res = run_simulation(teams_mod.GROUPS, elos, n=runs, seed=None)
    champ = {t: p["champion"] for t, p in res.items()}
    _sim_cache.clear()
    _sim_cache["key"] = key
    _sim_cache["champ"] = champ
    return champ


def _outrights_payload(runs: int) -> dict:
    """Each team's simulated title chance vs the bookmakers' outright market."""
    teams = [t for grp in teams_mod.GROUPS.values() for t in grp]
    champ = _champion_probs(runs)
    market = odds_mod.get_outrights(teams)
    cons = market.get("consensus", {}) if market.get("available") else {}
    rows = []
    for t in teams:
        mp = champ.get(t, 0.0)
        mk = cons.get(t)
        rows.append({
            "team": t,
            "model": round(mp * 100, 2),
            "market": round(mk * 100, 2) if mk is not None else None,
            "edge": round((mp - mk) * 100, 2) if mk is not None else None,
            "best": market.get("bestOdds", {}).get(t),
        })
    rows.sort(key=lambda r: r["model"], reverse=True)
    return {"runs": runs, "rows": rows,
            "marketAvailable": market.get("available", False),
            "marketSource": market.get("source"),
            "reason": market.get("reason"),
            "bookmakerCount": market.get("bookmakerCount"),
            "requestsRemaining": market.get("requestsRemaining")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quieter console
        pass

    def _send(self, obj, status=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- GET --------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        path = url.path

        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "dashboard.html"), "rb") as f:
                return self._send(f.read(), ctype="text/html; charset=utf-8")

        if path in ("/api/predict", "/api/simulate", "/api/odds", "/api/outrights") \
                and not secure.available():
            return self._send({"error": "model_unavailable", "modelAvailable": False}, 503)

        if path == "/api/venues":
            return self._send({"venues": climate_mod.list_venues()})

        if path == "/api/fixtures":
            return self._send({"fixtures": fixtures_mod.all_fixtures()})

        if path == "/api/coaches":
            teams_all = sorted({t for grp in teams_mod.GROUPS.values() for t in grp})
            return self._send({"coaches": coach_mod.all_coaches(teams_all)})

        if path == "/api/weather":
            return self._send(climate_mod.live_weather(q.get("venue", [""])[0]))

        if path == "/api/spreads":
            return self._send(odds_mod.spreads_market(q.get("home", [""])[0],
                                                      q.get("away", [""])[0]))

        if path == "/api/teams":
            elos = squads_mod.effective_elo_map(SQUADS)
            data = sorted(({"team": t, "elo": e} for t, e in elos.items()),
                          key=lambda d: d["elo"], reverse=True)
            return self._send({"teams": data})

        if path == "/api/predict":
            home, away = q.get("home", [""])[0], q.get("away", [""])[0]
            if not home or not away:
                return self._send({"error": "home and away required"}, 400)
            base_h = SQUADS[home]["base_elo"] if home in SQUADS else teams_mod.ELO.get(home, 1500.0)
            base_a = SQUADS[away]["base_elo"] if away in SQUADS else teams_mod.ELO.get(away, 1500.0)
            lin_h, lin_a = _lineup_delta(home), _lineup_delta(away)
            live_h, live_a = live_mod.get_delta(home), live_mod.get_delta(away)
            coach_h, coach_a = coach_mod.get_delta(home), coach_mod.get_delta(away)
            frm_h = form_mod.team_form_delta(SQUADS.get(home, {}), home)
            frm_a = form_mod.team_form_delta(SQUADS.get(away, {}), away)
            sim_h, sim_a = sim_mod.get_delta(home), sim_mod.get_delta(away)
            kp_h = kp_mod.team_keyplayer_delta(home, SQUADS.get(home, {}))
            kp_a = kp_mod.team_keyplayer_delta(away, SQUADS.get(away, {}))
            wx_h = wx_a = 0.0
            climate_info = None
            venue = q.get("venue", [""])[0]
            if venue:
                weather = climate_mod.live_weather(venue)
                assess = climate_mod.climate_assessment(home, away, weather)
                wx_h, wx_a = assess["deltaHome"], assess["deltaAway"]
                climate_info = {"venue": venue, "weather": weather, "assessment": assess}
            # Match-context: rest days (needs a date) + venue altitude.
            ctx = ctx_mod.context_delta(home, away, venue=venue or None,
                                        match_date=q.get("date", [""])[0] or None)
            # Calibrated Elo drives supremacy (weather + context are add-ons).
            elo_h = _calibrated_elo(home) + wx_h + ctx["home"]
            elo_a = _calibrated_elo(away) + wx_a + ctx["away"]
            # Designated-home advantage (extra for host nations); skip if neutral asked.
            ha = 0.0 if q.get("neutral", [""])[0] in ("1", "true") else home_advantage(home)
            p = predict_calibrated(home, away, elo_h, elo_a, home_adv=ha)
            breakdown = {
                "home": {"base": round(base_h, 1), "lineup": round(lin_h, 1),
                         "liveForm": round(live_h, 1), "weather": round(wx_h, 1),
                         "coach": round(coach_h, 1), "coachName": coach_mod.get(home)["name"],
                         "playerForm": round(frm_h, 1), "sim": round(sim_h, 1),
                         "keyPlayer": round(kp_h, 1), "homeAdv": round(ha, 1),
                         "context": round(ctx["home"], 1), "effective": round(elo_h + ha, 1)},
                "away": {"base": round(base_a, 1), "lineup": round(lin_a, 1),
                         "liveForm": round(live_a, 1), "weather": round(wx_a, 1),
                         "coach": round(coach_a, 1), "coachName": coach_mod.get(away)["name"],
                         "playerForm": round(frm_a, 1), "sim": round(sim_a, 1),
                         "keyPlayer": round(kp_a, 1), "homeAdv": 0.0,
                         "context": round(ctx["away"], 1), "effective": round(elo_a, 1)},
            }
            pH, pD, pA = p.p_home_win, p.p_draw, p.p_away_win
            market_info = None
            # Optional market blend: ?mblend=0.0-1.0 (share of market). The single
            # strongest external signal in football. No-op without an odds key.
            try:
                mblend = float(q.get("mblend", ["0"])[0])
            except ValueError:
                mblend = 0.0
            if mblend > 0:
                mkt = odds_mod.get_market(home, away)
                cons = mkt.get("consensus") if mkt.get("available") else None
                if cons and all(cons.get(k) for k in ("home", "draw", "away")):
                    w = max(0.0, min(1.0, mblend))
                    mix = {"H": (1 - w) * pH + w * cons["home"],
                           "D": (1 - w) * pD + w * cons["draw"],
                           "A": (1 - w) * pA + w * cons["away"]}
                    s = sum(mix.values()) or 1.0
                    pH, pD, pA = mix["H"] / s, mix["D"] / s, mix["A"] / s
                    market_info = {"applied": True, "weight": w, "consensus": cons}
                else:
                    market_info = {"applied": False, "reason": mkt.get("reason", "unavailable")}
            return self._send({
                "home": home, "away": away,
                "eloHome": round(elo_h + ha, 1), "eloAway": round(elo_a, 1),
                "expected": list(p.expected_score),
                "mostLikely": list(p.most_likely_score),
                "pHome": pH, "pDraw": pD, "pAway": pA,
                "scorelines": [{"score": f"{i}-{j}", "p": pr}
                               for (i, j), pr in p.top_scorelines(8)],
                "climate": climate_info, "ratings": breakdown, "market": market_info,
                "handicap": handicap_mod.cover_table(p.scoreline_probs),
            })

        if path == "/api/simulate":
            runs = int(q.get("runs", ["5000"])[0])
            return self._send({"runs": runs, "rows": _sim_rows(runs, _all_calibrated_elos())})

        if path == "/api/history":
            date = q.get("date", [None])[0]
            kind = q.get("type", [None])[0]
            return self._send({"entries": history_mod.read_history(date, kind)})

        if path == "/api/liveratings":
            return self._send({"ratings": live_mod.table(), "results": live_mod.results()})

        if path == "/api/standings":
            return self._send({"standings": standings_mod.standings()})

        if path == "/api/bracket":
            if not secure.available():
                return self._send({"error": "model_unavailable"}, 503)
            return self._send(standings_mod.bracket())

        if path == "/api/sims":
            return self._send({"simulations": history_mod.list_simulations()})

        if path == "/api/sim":
            snap = history_mod.load_simulation(q.get("id", [""])[0])
            return self._send(snap or {"error": "not found"}, 200 if snap else 404)

        if path == "/api/modelinfo":
            info = secure.model_info()
            info["modelAvailable"] = info.get("available", False)
            info["oddsApiKey"] = bool(odds_mod.get_api_key())
            return self._send(info)

        if path == "/api/odds":
            home, away = q.get("home", [""])[0], q.get("away", [""])[0]
            if not home or not away:
                return self._send({"error": "home and away required"}, 400)
            blend = q.get("blend", [None])[0]
            blend = float(blend) if blend is not None else None
            try:
                return self._send(_odds_payload(home, away, blend))
            except Exception as e:
                return self._send({"home": home, "away": away,
                                   "market": {"available": False, "reason": "error",
                                              "detail": str(e)}})

        if path == "/api/outrights":
            runs = int(q.get("runs", ["4000"])[0])
            try:
                return self._send(_outrights_payload(runs))
            except Exception as e:
                return self._send({"rows": [], "marketAvailable": False,
                                   "reason": "error", "detail": str(e)})

        if path == "/api/squad":
            team = q.get("team", [""])[0]
            if team not in SQUADS:
                return self._send({"error": "unknown team"}, 404)
            sq = SQUADS[team]
            return self._send({
                "team": team, "effectiveElo": squads_mod.effective_elo(sq),
                "baseElo": sq["base_elo"], "players": sq["players"],
            })

        if path == "/api/sim_fixtures":
            if not secure.available():
                return self._send({"error": "model_unavailable", "modelAvailable": False}, 503)
            runs = int(q.get("runs", ["1000"])[0])
            # Calibrated Elos WITHOUT the sim delta (avoids circular feedback).
            elos = {t: _calibrated_elo(t, include_sim=False) for t in SQUADS}
            return self._send(sim_mod.simulate_all(runs, elos))

        if path == "/api/sim_meta":
            return self._send(sim_mod.meta())

        if path == "/api/form":
            team = q.get("team", [""])[0]
            if not team or team not in SQUADS:
                return self._send({"error": "unknown team"}, 404)
            cache = form_mod._load_cache()
            detail = form_mod.squad_form_detail(SQUADS[team], team, cache)
            delta = form_mod.team_form_delta(SQUADS[team], team, cache)
            return self._send({
                "team": team, "formDelta": delta,
                "hasCacheData": bool(cache),
                "players": detail,
            })

        if path == "/api/keyplayers":
            team = q.get("team", [""])[0]
            cache = kp_mod._load_cache()
            if team:
                if team not in SQUADS:
                    return self._send({"error": "unknown team"}, 404)
                return self._send(kp_mod.detail(team, SQUADS[team], cache))
            # all teams: compact core + delta summary
            rows = []
            for t in SQUADS:
                d = kp_mod.detail(t, SQUADS[t], cache)
                if d.get("core"):
                    rows.append({"team": t, "core": d["core"]["name"],
                                 "pos": d["core"].get("pos", ""),
                                 "dependency": d["core"]["dependency"],
                                 "available": d["core"].get("available", True),
                                 "keyPlayerDelta": d["keyPlayerDelta"]})
            rows.sort(key=lambda r: -r["dependency"])
            return self._send({"teams": rows, "meta": kp_mod.meta()})

        if path == "/api/form_meta":
            return self._send(form_mod.meta())

        if path == "/api/form_deltas":
            return self._send({"deltas": form_mod.all_form_deltas(SQUADS)})

        if path == "/api/live_matches":
            date = q.get("date", [None])[0]
            try:
                return self._send({"matches": form_mod.live_matches(date)})
            except Exception as e:
                return self._send({"error": str(e), "matches": []})

        if path == "/api/live_stats":
            event_id = q.get("id", [""])[0]
            if not event_id:
                return self._send({"error": "id required"}, 400)
            try:
                return self._send({"stats": form_mod.match_stats(event_id)})
            except Exception as e:
                return self._send({"error": str(e), "stats": {}})

        return self._send({"error": "not found"}, 404)

    # --- POST -------------------------------------------------------------
    def do_POST(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}

        if url.path == "/api/oddskey":
            key = (body.get("key") or "").strip()
            if not key:
                return self._send({"error": "key required"}, 400)
            odds_mod.save_api_key(key)
            return self._send({"saved": True})

        if url.path in ("/api/odds", "/api/outrights", "/api/savesim", "/api/recalc") \
                and not secure.available():
            return self._send({"error": "model_unavailable", "modelAvailable": False}, 503)

        if url.path == "/api/result":
            try:
                home, away = body["home"], body["away"]
                gh, ga = int(body["homeGoals"]), int(body["awayGoals"])
            except (KeyError, ValueError, TypeError):
                return self._send({"error": "home/away/homeGoals/awayGoals required"}, 400)
            if not secure.available():
                return self._send({"error": "model_unavailable"}, 503)
            neutral = bool(body.get("neutral", True))
            # Surprise: the model's pre-result prediction vs what happened.
            p = predict_calibrated(home, away, _calibrated_elo(home), _calibrated_elo(away),
                                   neutral=neutral)
            outcome = "home" if gh > ga else ("away" if ga > gh else "draw")
            p_out = {"home": p.p_home_win, "draw": p.p_draw, "away": p.p_away_win}[outcome]
            surprise = ("as expected" if p_out >= 0.5 else "plausible" if p_out >= 0.33
                        else "mild upset" if p_out >= 0.18 else "big upset")
            live_mod.record_result(home, away, gh, ga, neutral, source="manual")
            history_mod.log_input("result", {"home": home, "away": away,
                                  "score": f"{gh}-{ga}", "outcome": outcome,
                                  "modelProb": round(p_out, 3), "surprise": surprise})
            return self._send({
                "home": home, "away": away, "score": f"{gh}-{ga}", "outcome": outcome,
                "model": {"pHome": p.p_home_win, "pDraw": p.p_draw, "pAway": p.p_away_win,
                          "expected": list(p.expected_score)},
                "outcomeProb": round(p_out, 3), "surprise": surprise,
                "homeElo": round(live_mod.effective_elo_disp(home), 1),
                "awayElo": round(live_mod.effective_elo_disp(away), 1),
                "homeDelta": live_mod.get_delta(home), "awayDelta": live_mod.get_delta(away),
            })

        if url.path == "/api/syncresults":
            if not secure.available():
                return self._send({"error": "model_unavailable"}, 503)
            sc = odds_mod.fetch_scores(int(body.get("days", 3)))
            if not sc.get("available"):
                return self._send({"applied": 0, "reason": sc.get("reason"),
                                   "requestsRemaining": sc.get("requestsRemaining")})
            known = list(teams_mod.ELO)
            prior = live_mod.results()
            existing = {r["key"] for r in prior}
            # Also dedupe by team pair so a match already recorded from another
            # source (e.g. ESPN) isn't double-counted under a different key.
            existing_pairs = {(r["home"], r["away"]) for r in prior}
            applied = []
            for m in sc["matches"]:
                h = odds_mod.to_known_team(m["home"], known)
                a = odds_mod.to_known_team(m["away"], known)
                if (not h or not a or m["id"] in existing
                        or (h, a) in existing_pairs or (a, h) in existing_pairs):
                    continue
                live_mod.record_result(h, a, m["gh"], m["ga"], neutral=True,
                                       source="odds-api", ext_id=m["id"])
                existing_pairs.add((h, a))
                applied.append({"home": h, "away": a, "score": f"{m['gh']}-{m['ga']}"})
            return self._send({"applied": len(applied), "matches": applied,
                               "requestsRemaining": sc.get("requestsRemaining")})

        if url.path == "/api/resetratings":
            live_mod.reset()
            return self._send({"reset": True})

        if url.path == "/api/reset_sim_ratings":
            sim_mod.reset()
            return self._send({"reset": True})

        if url.path == "/api/refresh_form":
            try:
                cache = form_mod.fetch_form(force=True)
                return self._send({
                    "ok": True,
                    "matchesScanned": cache.get("matchesScanned", 0),
                    "teamsWithData": cache.get("teamsWithData", 0),
                    "ts": cache.get("ts", ""),
                    "errors": cache.get("errors", []),
                })
            except Exception as e:
                return self._send({"ok": False, "error": str(e)}, 500)

        if url.path == "/api/refresh_keyplayers":
            try:
                data = kp_mod.analyze(force=True)
                return self._send({"ok": True, "teamCount": data.get("teamCount", 0),
                                   "ts": data.get("ts", "")})
            except Exception as e:
                return self._send({"ok": False, "error": str(e)}, 500)

        if url.path == "/api/coach":
            team = body.get("team", "")
            if not team:
                return self._send({"error": "team required"}, 400)
            adj = body.get("adj")
            return self._send(coach_mod.update(
                team, name=body.get("name"), since=body.get("since"),
                adj=float(adj) if adj is not None else None))

        if url.path == "/api/savesim":
            runs = int(body.get("runs", 5000))
            deltas = _all_deltas()
            rows = _sim_rows(runs, _all_calibrated_elos())
            snap = history_mod.save_simulation(rows, runs, deltas, body.get("label", ""))
            return self._send({"id": snap["id"], "label": snap["label"],
                               "topPick": snap["topPick"], "saved": True})

        if url.path == "/api/recalc":
            snap = history_mod.load_simulation(body.get("id", ""))
            if not snap:
                return self._send({"error": "snapshot not found"}, 404)
            runs = int(body.get("runs", snap.get("runs", 5000)))
            deltas = snap.get("deltas", {})
            rows = _sim_rows(runs, _elos_from_deltas(deltas))
            new = history_mod.save_simulation(
                rows, runs, deltas, f"Recalc of {snap['id']} ({runs} runs)")
            return self._send({"id": new["id"], "label": new["label"],
                               "runs": runs, "rows": rows,
                               "basedOn": snap["id"]})

        if url.path == "/api/outrights":
            odds_map = body.get("odds") or {}
            if not odds_map:
                return self._send({"error": "odds map required"}, 400)
            odds_mod.set_manual_outrights(odds_map)
            history_mod.log_input("outright_odds", {"odds": odds_map})
            runs = int(body.get("runs", 4000))
            return self._send(_outrights_payload(runs))

        if url.path == "/api/odds":
            home, away = q.get("home", [""])[0], q.get("away", [""])[0]
            try:
                o = {k: float(body[k]) for k in ("home", "draw", "away")}
            except (KeyError, ValueError, TypeError):
                return self._send({"error": "home/draw/away decimal odds required"}, 400)
            odds_mod.set_manual(home, away, o, body.get("bookmaker", "manual"))
            history_mod.log_input("match_odds", {"home": home, "away": away,
                                  "odds": o, "bookmaker": body.get("bookmaker", "manual")})
            return self._send(_odds_payload(home, away, body.get("blend")))

        if url.path != "/api/squad":
            return self._send({"error": "not found"}, 404)
        team = q.get("team", [""])[0]
        if team not in SQUADS:
            return self._send({"error": "unknown team"}, 404)

        payload = body
        incoming = {p["id"]: p for p in payload.get("players", [])}

        for p in SQUADS[team]["players"]:
            if p["id"] in incoming:
                inc = incoming[p["id"]]
                if "available" in inc:
                    p["available"] = bool(inc["available"])
                p["starter"] = bool(inc.get("starter", p["starter"]))
                if not p.get("available", True):
                    p["starter"] = False   # injured players can't start
                if "rating" in inc:
                    p["rating"] = max(1, min(99, int(inc["rating"])))

        squads_mod.save_squads(SQUADS)
        eff = squads_mod.effective_elo(SQUADS[team])
        starters = [p["name"] for p in SQUADS[team]["players"] if p["starter"]]
        history_mod.log_input("lineup", {"team": team, "effectiveElo": eff,
                              "baseElo": SQUADS[team]["base_elo"], "starters": starters})
        return self._send({"team": team, "effectiveElo": eff})


def main(port: int | None = None, host: str | None = None):
    # Hosting platforms (Render/Railway/Fly/…) inject $PORT and need 0.0.0.0;
    # locally we stay on localhost.
    port = port or int(os.environ.get("PORT", 8000))
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = host or os.environ.get("HOST", default_host)
    server = ThreadingHTTPServer((host, port), Handler)
    where = "all interfaces" if host == "0.0.0.0" else f"http://localhost:{port}"
    print(f"Dashboard running on {host}:{port}  ({where})  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    import sys
    cli_port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(cli_port)
