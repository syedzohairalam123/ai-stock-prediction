"""
Baseline forecasters (spec §21).

Four honest, well-understood reference models, each expressed as a predictor of
the **h-step-ahead log return** so it is directly comparable with the ML models
on the same walk-forward folds:

  * ``naive``               — random-walk: expected return is 0 (prediction = last close)
  * ``moving_average``      — the mean of the last k closes vs the last close
  * ``exp_smoothing``       — simple exponential smoothing (alpha fitted on the
                              training slice only, over a small real grid)
  * ``trend_extrapolation`` — least-squares slope over the last k closes

Spec §21 is explicit that ML must not be used when a baseline performs better;
:mod:`app.crypto.forecasting.engine` enforces that by comparing validation RMSE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

#: Candidate smoothing constants searched when fitting SES (a real, bounded grid).
ALPHA_GRID = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


@dataclass
class BaselinePrediction:
    name: str
    predicted_return: Optional[float]


class BaselineForecaster:
    """A fitted-on-train, predict-on-test baseline."""

    name = "baseline"

    def fit(self, closes: Sequence[float]) -> "BaselineForecaster":
        raise NotImplementedError

    def predict_return(self, closes: Sequence[float]) -> Optional[float]:
        raise NotImplementedError


class NaiveForecaster(BaselineForecaster):
    """Random walk: the best point estimate of the future price is the last one."""

    name = "naive"

    def fit(self, closes: Sequence[float]) -> "NaiveForecaster":
        return self

    def predict_return(self, closes: Sequence[float]) -> Optional[float]:
        return 0.0 if closes else None


class MovingAverageForecaster(BaselineForecaster):
    """The mean of the recent window, expressed as a return from the last close."""

    def __init__(self, window: int = 10) -> None:
        self.window = max(2, window)
        self.name = f"moving_average_{self.window}"

    def fit(self, closes: Sequence[float]) -> "MovingAverageForecaster":
        return self

    def predict_return(self, closes: Sequence[float]) -> Optional[float]:
        if len(closes) < self.window or closes[-1] <= 0:
            return None
        mean = sum(closes[-self.window :]) / self.window
        if mean <= 0:
            return None
        return math.log(mean / closes[-1])


class ExponentialSmoothingForecaster(BaselineForecaster):
    """SES with the smoothing constant fitted on the training slice."""

    name = "exp_smoothing"

    def __init__(self) -> None:
        self.alpha: float = 0.3

    def fit(self, closes: Sequence[float]) -> "ExponentialSmoothingForecaster":
        if len(closes) < 10:
            return self
        best_alpha, best_error = self.alpha, float("inf")
        for alpha in ALPHA_GRID:
            level = closes[0]
            error = 0.0
            for value in closes[1:]:
                error += (value - level) ** 2
                level = alpha * value + (1.0 - alpha) * level
            if error < best_error:
                best_alpha, best_error = alpha, error
        self.alpha = best_alpha
        return self

    def _level(self, closes: Sequence[float]) -> float:
        level = closes[0]
        for value in closes[1:]:
            level = self.alpha * value + (1.0 - self.alpha) * level
        return level

    def predict_return(self, closes: Sequence[float]) -> Optional[float]:
        if len(closes) < 2 or closes[-1] <= 0:
            return None
        level = self._level(closes)
        if level <= 0:
            return None
        return math.log(level / closes[-1])


class TrendExtrapolationForecaster(BaselineForecaster):
    """Least-squares slope over the recent window, extrapolated h steps."""

    def __init__(self, window: int = 20) -> None:
        self.window = max(2, window)
        self.name = f"trend_extrapolation_{self.window}"

    def fit(self, closes: Sequence[float]) -> "TrendExtrapolationForecaster":
        return self

    def predict_return(self, closes: Sequence[float]) -> Optional[float]:
        if len(closes) < self.window or closes[-1] <= 0:
            return None
        window = list(closes[-self.window :])
        n = len(window)
        mean_x = (n - 1) / 2.0
        mean_y = sum(window) / n
        denominator = sum((i - mean_x) ** 2 for i in range(n))
        if denominator == 0:
            return None
        slope = sum((i - mean_x) * (window[i] - mean_y) for i in range(n)) / denominator
        projected = window[-1] + slope
        if projected <= 0:
            return None
        return math.log(projected / window[-1])


def default_baselines(*, horizon: int, short_window: int = 10, trend_window: int = 20) -> List[BaselineForecaster]:
    """The baseline set every ML model must beat to be used."""
    return [
        NaiveForecaster(),
        MovingAverageForecaster(window=short_window),
        ExponentialSmoothingForecaster(),
        TrendExtrapolationForecaster(window=trend_window),
    ]


#: Immutable metadata about the baseline family, surfaced in the API meta.
BASELINE_FAMILY: Dict[str, str] = {
    "naive": "Random-walk reference: expected h-step return is zero.",
    "moving_average": "Mean of the recent closes, expressed as a return.",
    "exp_smoothing": "Simple exponential smoothing; alpha fitted on the training slice only.",
    "trend_extrapolation": "Least-squares trend over the recent window.",
}
