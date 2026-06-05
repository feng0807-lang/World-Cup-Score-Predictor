# World Cup 2026 Football Predictor

Predicts football match scores and simulates the **2026 FIFA World Cup**
(48 teams, 12 groups of four) using a **trained, encrypted prediction model**,
with real squads you can pick a starting XI from before each match.

**Data:** all 48 qualified teams, the official 12-group draw, and full 26-man
squads (player names + positions) fetched from the Wikipedia
"2026 FIFA World Cup squads" article. The model is trained on **49,000+
historical international matches (1872–2026)**.

## Setup

```bash
pip install -r requirements.txt
python server.py          # then open http://localhost:8000
```

> **⚠ The prediction model is not included in this public repo.** The algorithm
> (`engine_source.py`), trained parameters (`model_params.pkl`) and encrypted
> artifacts (`engine.enc`, `params.enc`) plus the key are kept private
> (gitignored). A fresh clone runs the **dashboard** — squad/lineup editing,
> manual odds entry and history — but **match predictions and the simulation
> require the model**, and will show a "model not included" notice until you
> add your own model files locally (see the encryption section below).

## The prediction model

The engine blends three trained components (all fit on the historical dataset
via `train_model.py`):

1. **Dixon-Coles attack/defense** — each team gets separate attacking and
   defending strengths plus a home-advantage term, fit by **Poisson
   regression** with recency weighting (recent matches count more).
2. **Gradient-boosting goals model** (scikit-learn) — predicts goals from each
   team's recent rolling form (goals for/against), blended 65/35 with the
   Dixon-Coles output.
3. **Dixon-Coles low-score correction (ρ)** — fixes the classic Poisson
   under-/over-estimation of 0-0, 1-0, 0-1 and 1-1 scorelines (ρ fit by MLE).

On top of that, the **starting XI you pick** shifts each team's effective Elo,
which nudges the predicted goals up or down.

For a tournament, expected goals for every pairing are precomputed once, then
sampled thousands of times in a **Monte Carlo simulation** of the group stage
+ 32-team knockout bracket (`tournament.run_simulation`).

## The model is encrypted

The algorithm (`engine_source.py`) and the trained parameters
(`model_params.pkl`) are **AES-encrypted** into `engine.enc` and `params.enc`
by `secure_build.py`, and loaded + decrypted at runtime by `secure.py` using a
key from the `WORLDCUP_KEY` env var or the `model.key` file.

```bash
python train_model.py        # 1. train -> model_params.pkl
python secure_build.py       # 2. encrypt -> engine.enc + params.enc + model.key
python secure_build.py --purge   # (optional) also delete the plaintext sources
```

> ⚠️ **Keep `model.key` secret** (it's in `.gitignore`). Runtime decryption is
> obfuscation, not unbreakable DRM — anyone who can run the app can in
> principle recover the key. It deters casual copying of your model and keeps
> the algorithm/tuning out of plain sight in the shipped files. Without the
> correct key, the `.enc` files are useless and the app refuses to run.

Requires: `scikit-learn`, `scipy`, `pandas`, `numpy`, `cryptography`.

## Bookmaker odds & value

The **Match Predictor** tab compares the model against the betting market.

- **Live odds** via [The Odds API](https://the-odds-api.com) (free tier ~500
  req/mo) aggregate the biggest books — **Pinnacle, Bet365, William Hill** and
  more — across uk/eu/us/au in one cached call. Set the key in the dashboard,
  or via the `ODDS_API_KEY` env var / `odds_api.key` file.
- **Manual entry** — no key needed: type the decimal odds (home/draw/away) you
  see at your bookie and the app converts + compares them.
- Odds are **de-vigged** (bookmaker margin removed) to true implied
  probabilities, then shown next to the model's, with the **edge** highlighted
  where the model rates an outcome higher than the market (potential value).
- An optional **blend** slider mixes market consensus into the model's
  prediction (markets are highly efficient, so this often sharpens accuracy).

### Title odds: model vs market (Tournament tab)

The Tournament tab can compare each team's **Monte-Carlo title chance** against
the bookmakers' **outright winner** market:

- **Compare to winner odds** runs the simulation and pulls live outright odds
  (de-vigged across the whole field) for every team, showing model % vs market
  % and the **edge** — teams your model rates higher than the market are
  flagged as potential value.
- **Manual**: paste lines like `Brazil 5.5` (team + decimal odds) to compare
  without a key. Manual outrights use the raw implied probability (a partial
  field can't be de-vigged reliably).

The `odds_api.key` is gitignored alongside `model.key`.

## History & backtracking (the `data/` folder)

Everything you enter is archived so you can reference it later and reproduce
past runs. See the **History & Backtrack** tab.

- `data/history.jsonl` — an append-only, timestamped **journal** of every input:
  manual match odds, outright odds and lineup saves. Filter it by date/type in
  the dashboard.
- `data/simulations/sim_<timestamp>.json` — full **simulation snapshots**. Each
  one stores the results *and* the exact lineup state (Elo deltas) used.
  - **💾 Save run** (Tournament tab) saves the current simulation.
  - **↻ Recalc** (History tab) re-runs a saved snapshot from its stored lineup
    state — so you can **backtrack**: reproduce an old run, or extend it with
    more iterations. The recompute is saved as a new snapshot, preserving the
    original.

Files are plain JSON named by timestamp, so you can also browse/diff them
straight from the `data/` folder.

## Web dashboard (recommended)

```bash
python server.py
# then open http://localhost:8000
```

Three tabs:

- **Match Predictor** — pick two teams, see win/draw/loss %, expected score,
  most likely scoreline, and a probability table of scorelines.
- **Tournament Table** — run a Monte-Carlo simulation and rank every team's
  chance of reaching each round (R32 → R16 → QF → SF → Final → Champion)
  and winning the title. (Format: top 2 of each group + 8 best third-placed
  teams = 32-team knockout.)
- **Starting XI Editor** — for each of the 48 teams, tick the starting 11
  from the real 26-man squad and tweak player ratings. The chosen XI's
  average rating shifts the team's *effective Elo*, which immediately changes
  the predictions. Lineups persist to `squads.json`.

> `squads.json` ships pre-built with real 26-man squads. To regenerate it from
> the roster data, run `python build_squads.py`. Edit lineups/ratings through
> the dashboard, or by hand.

## Command line usage

```bash
# Predict one match
python predict.py match Argentina France

# Override the ratings manually
python predict.py match Brazil Spain --elo-home 2055 --elo-away 2050

# Simulate the whole tournament (10,000 runs) and rank title chances
python predict.py simulate --runs 10000 --seed 1

# Use your own data file (ratings + groups)
python predict.py simulate --data data_sample.json
```

## Customising

- Edit `ELO` and `GROUPS` in `teams.py`, **or**
- Pass `--data yourfile.json` with the shape shown in `data_sample.json`.

## Tuning the model

Constants in `model.py`:

| Constant          | Meaning                                            |
|-------------------|----------------------------------------------------|
| `BASE_TOTAL_GOALS`| Avg combined goals per match (~2.65)               |
| `GOALS_PER_ELO`   | Goal advantage per Elo point (~0.0036)             |
| `MIN_LAMBDA`      | Floor on a team's expected goals                   |
| `MAX_GOALS`       | Grid size for the scoreline probability matrix     |

## Files

- `model.py` — Poisson scoreline engine
- `teams.py` — ratings + group data
- `tournament.py` — Monte Carlo simulator
- `predict.py` — command-line interface
- `data_sample.json` — example custom dataset
