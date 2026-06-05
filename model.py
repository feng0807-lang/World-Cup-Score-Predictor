"""Prediction interface.

Thin wrapper over the encrypted prediction engine (see secure.py / engine.enc).
The heavy lifting — trained Dixon-Coles attack/defense, gradient-boosting goals
model, low-score correction and lineup adjustment — lives in the encrypted
engine. This module just exposes a stable interface to the rest of the app.

`delta_home` / `delta_away` are the Elo change induced by the chosen starting XI
(effective Elo minus the squad's baseline Elo); 0 means "as-is".
"""

from __future__ import annotations

from dataclasses import dataclass

import secure


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
