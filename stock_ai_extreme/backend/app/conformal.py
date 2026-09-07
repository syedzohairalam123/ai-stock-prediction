"""
Phase 8 — probabilistic forecasting via split-conformal prediction.

The original interval was `prediction ± 1.96 * validation RMSE`, which
silently assumes the errors are Gaussian and stationary — often wrong for
financial returns, which have fat tails and change character over time.

Split conformal prediction instead measures how wrong the model actually was
on a held-out calibration slice and uses THAT empirical error distribution
(no Gaussian assumption) to size the interval. It targets roughly
`confidence`-level coverage under the standard conformal-prediction
assumption of exchangeable errors — a real, current technique, but still an
approximation for time series (markets aren't perfectly exchangeable
either); it's a genuine improvement over the flat 1.96x-RMSE band, not a
guarantee. Say so wherever this is surfaced.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


@dataclass
class ConformalResult:
    half_width: float          # calibrated 1-step-ahead half-width
    confidence: float          # target coverage level, e.g. 0.9
    calibration_size: int      # how many held-out points this was calibrated on
    method: str = "split_conformal"

    def half_width_for_step(self, step: int, scale: str = "sqrt") -> float:
        """Widen the interval for later horizon steps — uncertainty compounds
        the further out you forecast. `sqrt` scaling is a standard, simple
        heuristic (not itself conformally guaranteed beyond step 1)."""
        if scale == "sqrt":
            return self.half_width * math.sqrt(step)
        if scale == "linear":
            return self.half_width * step
        return self.half_width


def calibrate_split_conformal(
    model_factory: Callable[[], object],
    X: pd.DataFrame,
    y: pd.Series,
    confidence: float = 0.9,
    calibration_frac: float = 0.2,
    min_calibration_points: int = 15,
) -> ConformalResult:
    """Chronological split: train on the earlier slice, calibrate residual
    quantile on the later (still real, still historical) slice. Never
    shuffled — shuffling a time series for this would leak information."""
    n = len(X)
    n_cal = max(min_calibration_points, int(n * calibration_frac))
    if n_cal >= n:
        raise ValueError("Not enough rows to hold out a calibration split — need a longer date range.")

    X_train, y_train = X.iloc[:-n_cal], y.iloc[:-n_cal]
    X_cal, y_cal = X.iloc[-n_cal:], y.iloc[-n_cal:]

    model = model_factory()
    model.fit(X_train, y_train)
    cal_preds = np.asarray(model.predict(X_cal), dtype=float)
    residuals = np.abs(y_cal.to_numpy(dtype=float) - cal_preds)

    # Finite-sample conformal correction: use the ceil((n+1)*confidence)/n quantile,
    # not the naive `confidence` quantile — this is what gives the (approximate)
    # coverage guarantee instead of just "a percentile that sounds about right".
    q_level = min(1.0, math.ceil((n_cal + 1) * confidence) / n_cal)
    half_width = float(np.quantile(residuals, q_level))

    return ConformalResult(half_width=half_width, confidence=confidence, calibration_size=n_cal)
