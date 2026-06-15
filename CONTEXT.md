# World Cup 2026 Predictor — Dev Context

## What it is
Python prediction app for the 2026 FIFA World Cup (48 teams, 12 groups).
Model: Dixon-Coles Poisson + Gradient-Boosting blend, trained on 49k+ historical matches (1872–2026).
Model files are AES-encrypted and gitignored; dashboard still runs (read-only) without them.

## Run locally
```bash
python server.py
# open http://localhost:8000
```

## Architecture
- **server.py** — stdlib `http.server` (ThreadingHTTPServer, port 8000); all API endpoints
- **dashboard.html** — single-page frontend; tabs: Match Predictor, Tournament, Starting XI, Fixtures, History & Backtrack, Standings & Bracket
- **engine_source.py** — GITIGNORED, proprietary model (Dixon-Coles + GBM)
- **secure.py** — decrypts + loads engine.enc / params.enc at runtime (key from `WORLDCUP_KEY` env or `model.key`)
- **model.py** — Poisson scoreline engine (tunable constants)
- **tournament.py** — Monte Carlo simulation (group stage + 32-team knockout bracket)

## Key module summary
| File | Role |
|------|------|
| teams.py | Base Elo ratings + group data for all 48 teams |
| squads.py | 26-man squad loader, starting XI, effective Elo |
| build_squads.py | Regenerates squads.json from Wikipedia roster data |
| coach.py | Coach-quality Elo delta |
| handicap.py | Asian handicap cover probabilities from scoreline distribution |
| odds.py | Live odds via The Odds API + de-vig + blend slider |
| live.py | Online Elo updates from recorded tournament results |
| fixtures.py | All 72 group-stage matches with date + stadium |
| standings.py | Live group tables from recorded results |
| climate.py | Weather/acclimatization delta (Open-Meteo, no key) |
| history.py | Append-only journal (data/history.jsonl) |
| backtest.py | Walk-forward backtest (uses results.csv); gitignored with model |
| train_model.py | Trains model → model_params.pkl |
| secure_build.py | Encrypts engine+params → engine.enc / params.enc + model.key |
| make_deploy_env.py | Prints base64 env vars for Render/Fly.io deploy |

## Data files
- `results.csv` — 49k+ historical international match results (training + backtest)
- `squads.json` — 48 teams × 26-man squads with positions, ratings, starting XI state
- `data/history.jsonl` — append-only journal of manual inputs
- `data/results.json` — recorded live tournament results (feeds online Elo)
- `data/simulations/` — saved Monte Carlo snapshots (sim_<timestamp>.json)
- `manual_odds.json` — persisted manual bookmaker odds
- `model.key`, `odds_api.key` — gitignored secrets

## Effective rating formula
```
effective rating = trained base Elo
                 + lineup delta   (chosen XI vs squad default)
                 + live form delta (online Elo from recorded results)
                 + coach delta
                 + weather delta  (acclimatization vs match-day temp)
```

## Deploy path
1. `python make_deploy_env.py` — generates `WORLDCUP_KEY`, `ENGINE_ENC_B64`, `PARAMS_ENC_B64`
2. Push repo to GitHub; deploy on Render via `render.yaml` (blueprint) or Docker anywhere
3. Set env vars as secrets — model never leaves the host

## Pending / known missing features
- **Calibration reliability chart** — probability bins vs actual frequency from backtest data; add to dashboard
- **xG ratings** — needs a paid data source
- **Calibrate to market odds** — needs historical closing odds dataset
