"""Prediction interface.

Thin wrapper over the encrypted prediction engine (see secure.py / engine.enc).
The heavy lifting — trained Dixon-Coles attack/defense, gradient-boosting goals
model, low-score correction and lineup adjustment — lives in the encrypted
engine. This module just exposes a stable interface to the rest of the app.

`delta_home` / `delta_away` are the Elo change induced by the chosen starting XI
(effective Elo minus the squad's baseline Elo); 0 means "as-is".
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import secure

# --- Calibration: anchor supremacy to our calibrated Elo ----------------------
# The encrypted engine's trained Dixon-Coles attack/defense coefficients inflate
# CONMEBOL/CAF/AFC sides and under-rate some UEFA teams (they were fit on
# qualifying results across confederations of very different strength). That bias
# lives in the *supremacy* (lambda_home - lambda_away), not the total goals.
#
# So we keep the encrypted model's TOTAL-goals estimate (its form/GBM/matchup
# intelligence) but replace most of the supremacy with one derived from our
# hand-calibrated team Elo (squads.json base + lineup/live/coach/sim/form). The
# rating->goals slope is the value backtested in backtest.py.
GOALS_PER_ELO = 0.0036          # goals of supremacy per Elo point of difference
SUPREMACY_ELO_WEIGHT = 0.85     # 85% calibrated-Elo supremacy, 15% encrypted
_LAMBDA_CAP = 6.5

# Total-goals calibration. The encrypted engine's total (lambda_home + lambda_away)
# ran ~29% low vs WC2026 group-stage scoring (~3.0 goals/match observed over the
# first 44 matches; model expected ~2.36). The 48-team format packs in mismatches,
# lifting goal volume. We scale the TOTAL up to close ~80% of that gap (damped to
# avoid over-fitting early-tournament variance; knockout matches run tighter). The
# supremacy is left untouched — its 1X2 calibration was already good (~60% top-pick
# accuracy). Tune this one number as more results land.
TOTAL_GOALS_SCALE = 1.23

# Home / first-listed advantage. Even at neutral WC venues the designated-home
# team has won far more than a symmetric model expects: over the first 66 group
# matches home/draw/away was 48/27/24, but the neutral model predicted ~42/24/34.
# Backtest (grid search on RPS + accuracy) put the optimum near +50 Elo for the
# designated home, with a large extra edge for the three host nations playing an
# actual home game (they went 5W-1D-0L at home). Adding this lifted top-pick
# accuracy 64% -> ~68% and cut RPS 0.160 -> 0.153. Host extra is kept moderate
# since it rests on only 6 matches.
HOME_ADV_ELO = 50.0
HOST_HOME_EXTRA = 45.0
HOST_NATIONS = {"United States", "Mexico", "Canada"}

# 1X2 calibration corrections (see _calibrate_1x2). Backtested on the group stage:
# the draw boost lifts top-pick accuracy ~67% -> ~70% (catching tight-game draws),
# and the mild temperature offsets its small RPS cost, leaving RPS better than
# baseline (0.154 -> ~0.150). Kept conservative to limit over-fitting.
DRAW_BOOST = 0.20            # max draw uplift in a dead-even match
DRAW_CLOSENESS_SCALE = 0.7   # boost fades to 0 once |lambda diff| reaches this
PROB_TEMPERATURE = 0.90      # <1 sharpens toward the favourite (gentle)


def home_advantage(home_team: str) -> float:
    """Elo bonus for the designated-home team (extra for host nations)."""
    adv = HOME_ADV_ELO
    if home_team in HOST_NATIONS:
        adv += HOST_HOME_EXTRA
    return adv


@dataclass
class MatchPrediction:
    home: str
    away: str
    lambda_home: float
    lambda_away: float
    p_home_win: float
    p_draw: float
    p_away_win: float
    scoreline_probs: dict[tuple[int, int], float]

    @property
    def expected_score(self) -> tuple[float, float]:
        return round(self.lambda_home, 2), round(self.lambda_away, 2)

    @property
    def most_likely_score(self) -> tuple[int, int]:
        return max(self.scoreline_probs, key=self.scoreline_probs.get)

    def top_scorelines(self, n: int = 5):
        return sorted(self.scoreline_probs.items(), key=lambda kv: kv[1], reverse=True)[:n]


def expected_goals(home: str, away: str, delta_home: float = 0.0,
                   delta_away: float = 0.0, neutral: bool = True) -> tuple[float, float]:
    return secure.expected_goals(home, away, delta_home, delta_away, neutral)


def predict_match(home: str, away: str, delta_home: float = 0.0,
                  delta_away: float = 0.0, neutral: bool = True) -> MatchPrediction:
    g = secure.scoreline_grid(home, away, delta_home, delta_away, neutral)
    return MatchPrediction(
        home=home, away=away,
        lambda_home=g["lambda_home"], lambda_away=g["lambda_away"],
        p_home_win=g["p_home_win"], p_draw=g["p_draw"], p_away_win=g["p_away_win"],
        scoreline_probs=g["grid"],
    )


# --- Calibrated-Elo prediction path ------------------------------------------

def _reanchor(lh_e: float, la_e: float, elo_home: float, elo_away: float) -> tuple[float, float]:
    """Recombine the (scaled) encrypted total-goals with calibrated-Elo supremacy."""
    total = (lh_e + la_e) * TOTAL_GOALS_SCALE
    sup = (SUPREMACY_ELO_WEIGHT * GOALS_PER_ELO * (elo_home - elo_away)
           + (1.0 - SUPREMACY_ELO_WEIGHT) * (lh_e - la_e))
    lh = max(0.05, min((total + sup) / 2.0, _LAMBDA_CAP))
    la = max(0.05, min((total - sup) / 2.0, _LAMBDA_CAP))
    return lh, la


def expected_goals_calibrated(home: str, away: str, elo_home: float, elo_away: float,
                              neutral: bool = True, home_adv: float = 0.0) -> tuple[float, float]:
    """Expected goals with supremacy anchored to calibrated Elo (+ home advantage)."""
    lh_e, la_e = secure.expected_goals(home, away, 0.0, 0.0, neutral)
    return _reanchor(lh_e, la_e, elo_home + home_adv, elo_away)


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _tau(h: int, a: int, lh: float, la: float, rho: float) -> float:
    if h == 0 and a == 0:
        return 1 - lh * la * rho
    if h == 0 and a == 1:
        return 1 + lh * rho
    if h == 1 and a == 0:
        return 1 + la * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def predict_calibrated(home: str, away: str, elo_home: float, elo_away: float,
                       neutral: bool = True, home_adv: float = 0.0) -> MatchPrediction:
    """Full prediction with supremacy anchored to calibrated Elo, Dixon-Coles
    low-score correction (rho) applied just like the encrypted engine."""
    lh, la = expected_goals_calibrated(home, away, elo_home, elo_away, neutral, home_adv)
    rho = secure.rho()
    mg = secure.max_goals()
    ph = [_poisson_pmf(i, lh) for i in range(mg + 1)]
    pa = [_poisson_pmf(j, la) for j in range(mg + 1)]
    grid = {}
    p_home = p_draw = p_away = 0.0
    for i in range(mg + 1):
        for j in range(mg + 1):
            p = ph[i] * pa[j] * _tau(i, j, lh, la, rho)
            if p < 0:
                p = 0.0
            grid[(i, j)] = p
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    grid = {k: v / total for k, v in grid.items()}
    p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    # 1X2 calibration (applied to the headline result probs only; the scoreline
    # grid above stays the raw model, for AH/OU/correct-score markets):
    p_home, p_draw, p_away = _calibrate_1x2(p_home, p_draw, p_away, abs(lh - la))

    return MatchPrediction(
        home=home, away=away, lambda_home=lh, lambda_away=la,
        p_home_win=p_home, p_draw=p_draw, p_away_win=p_away,
        scoreline_probs=grid,
    )


def _calibrate_1x2(ph: float, pd: float, pa: float, supremacy: float) -> tuple[float, float, float]:
    """Two empirical corrections found by backtesting the group stage:

    1. Tight-game draw uplift. Evenly-matched games end level far more often than
       independent Poisson (even with Dixon-Coles rho) predicts: in matches with
       |lambda diff| < ~0.4 the actual draw rate was 40% vs 27% modelled, and draw
       was in fact the single most likely outcome there. Boost the draw, fading to
       zero as the match gets one-sided.
    2. Mild confidence sharpening. Favourites won slightly more than their stated
       probability (model was a touch under-confident), so sharpen toward the
       leader. Kept gentle (T just under 1) to avoid over-fitting the sample.
    """
    b = DRAW_BOOST * max(0.0, 1.0 - supremacy / DRAW_CLOSENESS_SCALE)
    pd = pd + b * (ph + pa)
    ph *= (1.0 - b)
    pa *= (1.0 - b)
    # temperature sharpen
    inv = 1.0 / PROB_TEMPERATURE
    ph, pd, pa = ph ** inv, pd ** inv, pa ** inv
    s = ph + pd + pa
    return ph / s, pd / s, pa / s
