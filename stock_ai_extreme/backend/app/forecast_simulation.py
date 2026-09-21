"""
Phase 14.3 — Monte-Carlo probability forecasting for forecast markets.

Replaces the frontend's `Math.sin` "simulated" curve with an actual stochastic
simulation over the market's *real* traded probability history.

Method
------
1. Convert the YES probability series to **log-odds** `x = log(p / (1 - p))`.
   Log-odds is the natural scale for a bounded probability: it is unbounded,
   roughly symmetric, and differences are meaningfully additive.
2. Fit two candidate dynamics to `x`:
   * **OU (Ornstein–Uhlenbeck / AR(1))** — mean-reverting. `x_{t+1} = x_t +
     theta * (mu - x_t) + sigma * e`, with `theta = -ln(phi)` from the AR(1)
     coefficient. Used when the fitted `phi` is a stable `(0, 1)`, which is the
     normal case for a probability that noisily hovers around a level.
   * **GBM (random walk on log-odds)** — `x_{t+1} = x_t + sigma * e`. Fallback
     for short/trending series where mean reversion is not identifiable.
3. Innovations `e` are **bootstrapped from the fitted residuals** (standardized,
   then rescaled), preserving the empirical fat tails instead of assuming
   Gaussianity.
4. Simulate `N` paths `H` steps ahead, where `H` is derived from the real
   observation spacing of the history and the requested horizon in days.
5. Report the median path plus 5/25/75/95 percentile bands, the terminal
   probability distribution, and `P(YES)` = share of paths that end above 50%.

Honesty rules
-------------
* Fewer than 3 usable observations -> `None` (caller shows UNAVAILABLE). A
  simulation cannot be estimated from nothing, and inventing a volatility would
  be fabrication.
* Every output is labelled with the model actually used, the sample size and the
  number of paths, so the UI can mark it clearly SIMULATED.
* Outputs are probabilities in `[0, 100]`, never prices or wagers.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .config import settings
from .logging_config import get_logger

logger = get_logger("neural_market.forecast_simulation")

#: Probability clamp so `log(p/(1-p))` stays finite. 0.01% / 99.99%.
_EPS = 1e-4

#: Minimum usable observations for a simulation to be meaningful.
MIN_OBSERVATIONS = 3

#: A |phi| at or above this is not a stable AR(1) process.
_PHI_MAX = 0.999


def logit(p: np.ndarray) -> np.ndarray:
    """Vectorized log-odds with the probability clamped away from 0/1."""
    clipped = np.clip(p, _EPS, 1.0 - _EPS)
    return np.log(clipped / (1.0 - clipped))


def sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable logistic function."""
    out = np.empty_like(x, dtype=float)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


def extract_series(history: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """Probability series (0..1) and epoch-seconds timestamps, sorted, deduped."""
    parsed: list[tuple[float, float]] = []
    for point in history or []:
        if not isinstance(point, dict):
            continue
        try:
            ts = datetime.fromisoformat(str(point.get("timestamp")).replace("Z", "+00:00")).timestamp()
            prob = float(point.get("yesProbability"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ts) or not math.isfinite(prob):
            continue
        if not 0.0 <= prob <= 100.0:
            continue
        parsed.append((ts, prob / 100.0))
    parsed.sort(key=lambda row: row[0])
    deduped: list[tuple[float, float]] = []
    for ts, prob in parsed:
        if deduped and deduped[-1][0] == ts:
            deduped[-1] = (ts, prob)
        else:
            deduped.append((ts, prob))
    if not deduped:
        return np.empty(0), np.empty(0)
    timestamps = np.array([row[0] for row in deduped], dtype=float)
    probabilities = np.array([row[1] for row in deduped], dtype=float)
    return timestamps, probabilities


def _normalize(values: np.ndarray) -> np.ndarray:
    """Standardize to zero mean / unit stdev; robust to a constant series."""
    if values.size == 0:
        return values
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    if std <= 1e-12:
        return values - mean
    return (values - mean) / std


def _fit_ar1(x: np.ndarray) -> tuple[float, float, np.ndarray] | None:
    """Least-squares AR(1) fit. Returns (phi, mu, residuals) or None.

    `x_t = c + phi * x_{t-1} + e`, so `mu = c / (1 - phi)`.
    """
    if x.size < 3:
        return None
    lagged = x[:-1]
    current = x[1:]
    design = np.column_stack([np.ones_like(lagged), lagged])
    try:
        coeffs, *_ = np.linalg.lstsq(design, current, rcond=None)
    except np.linalg.LinAlgError:
        return None
    intercept, phi = float(coeffs[0]), float(coeffs[1])
    if not math.isfinite(phi) or abs(phi) >= _PHI_MAX:
        return None
    residuals = current - (intercept + phi * lagged)
    if float(np.std(residuals, ddof=1)) <= 1e-12:
        return None
    mu = intercept / (1.0 - phi) if abs(1.0 - phi) > 1e-9 else float(np.mean(x))
    return phi, mu, residuals


def _simulate(
    x0: float,
    steps: int,
    paths: int,
    residuals: np.ndarray,
    *,
    phi: float | None,
    mu: float | None,
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate paths by bootstrapping standardized residuals.

    `phi`/`mu` set -> mean-reverting OU on log-odds; `None` -> random walk.
    Returns an array of shape `(paths, steps)` of log-odds values.
    """
    standardized = _normalize(residuals)
    if standardized.size == 0:
        standardized = np.array([0.0])
    scale = float(np.std(residuals, ddof=1)) if residuals.size > 1 else 0.0

    draws = rng.integers(0, standardized.size, size=(paths, steps))
    shocks = standardized[draws] * scale

    out = np.empty((paths, steps), dtype=float)
    state = np.full(paths, x0, dtype=float)
    if phi is not None and mu is not None:
        theta = -math.log(phi) if 0.0 < phi < 1.0 else 0.0
        for step in range(steps):
            state = state + theta * (mu - state) + shocks[:, step]
            out[:, step] = state
    else:
        for step in range(steps):
            state = state + shocks[:, step]
            out[:, step] = state
    return out


def _summarize_terminals(terminal: np.ndarray) -> dict[str, Any]:
    """Terminal probability distribution summary from the path endpoints."""
    p_yes = float(np.mean(terminal > 50.0))
    n = terminal.size
    se = math.sqrt(max(p_yes * (1.0 - p_yes), 0.0) / n) if n else 0.0
    counts, edges = np.histogram(terminal, bins=20, range=(0.0, 100.0))
    return {
        "pYes": round(p_yes * 100.0, 2),
        "pNo": round((1.0 - p_yes) * 100.0, 2),
        "pYesStdError": round(se * 100.0, 3),
        "pYesConfidenceInterval95": [
            round(max(p_yes - 1.96 * se, 0.0) * 100.0, 2),
            round(min(p_yes + 1.96 * se, 1.0) * 100.0, 2),
        ],
        "mean": round(float(np.mean(terminal)), 2),
        "median": round(float(np.median(terminal)), 2),
        "stdDev": round(float(np.std(terminal, ddof=1)) if n > 1 else 0.0, 2),
        "percentiles": {
            "p5": round(float(np.percentile(terminal, 5)), 2),
            "p25": round(float(np.percentile(terminal, 25)), 2),
            "p50": round(float(np.percentile(terminal, 50)), 2),
            "p75": round(float(np.percentile(terminal, 75)), 2),
            "p95": round(float(np.percentile(terminal, 95)), 2),
        },
        "histogram": {
            "binEdges": [round(float(edge), 2) for edge in edges.tolist()],
            "counts": [int(count) for count in counts.tolist()],
        },
    }


def simulate_probability(
    *,
    history: list[dict[str, Any]],
    current_probability: float | None,
    horizon_days: float,
    paths: int | None = None,
    model: str = "auto",
    seed: int | None = None,
) -> dict[str, Any] | None:
    """Run the simulation. Returns a serializable payload, or None if it cannot
    be estimated from the supplied history."""
    timestamps, probabilities = extract_series(history)
    if probabilities.size < MIN_OBSERVATIONS:
        return None

    x = logit(probabilities)
    median_dt_days = float(np.median(np.diff(timestamps))) / 86_400.0 if timestamps.size > 1 else 1.0
    if not math.isfinite(median_dt_days) or median_dt_days <= 0:
        median_dt_days = 1.0

    if current_probability is None:
        current_probability = float(probabilities[-1] * 100.0)
    x0 = float(logit(np.array([current_probability / 100.0]))[0])

    horizon = max(1e-6, float(horizon_days or 1.0))
    steps = int(round(horizon / median_dt_days))
    steps = max(1, min(steps, settings.forecast_simulation_max_steps))

    n_paths = int(paths or settings.forecast_simulation_paths)
    n_paths = max(500, min(n_paths, 100000))
    rng = np.random.default_rng(seed)

    ar1 = _fit_ar1(x)
    requested = (model or "auto").lower()

    if requested == "ensemble" and ar1 is not None:
        half = n_paths // 2
        ou_paths = _simulate(x0, steps, max(half, 1), ar1[2], phi=ar1[0], mu=ar1[1], rng=rng)
        gbm_paths = _simulate(x0, steps, max(n_paths - half, 1), np.diff(x), phi=None, mu=None, rng=rng)
        path_matrix = np.vstack([ou_paths, gbm_paths])
        used_model = "ENSEMBLE_OU_GBM"
    elif requested == "ou" and ar1 is not None:
        path_matrix = _simulate(x0, steps, n_paths, ar1[2], phi=ar1[0], mu=ar1[1], rng=rng)
        used_model = "OU_MEAN_REVERTING"
    elif requested == "gbm" or ar1 is None:
        path_matrix = _simulate(x0, steps, n_paths, np.diff(x), phi=None, mu=None, rng=rng)
        used_model = "GBM_RANDOM_WALK"
    else:
        # auto: prefer the mean-reverting fit when it is stable
        path_matrix = _simulate(x0, steps, n_paths, ar1[2], phi=ar1[0], mu=ar1[1], rng=rng)
        used_model = "OU_MEAN_REVERTING"

    probability_paths = sigmoid(path_matrix) * 100.0
    terminal = probability_paths[:, -1]

    percentiles = {
        "p5": np.percentile(probability_paths, 5, axis=0),
        "p25": np.percentile(probability_paths, 25, axis=0),
        "p50": np.percentile(probability_paths, 50, axis=0),
        "p75": np.percentile(probability_paths, 75, axis=0),
        "p95": np.percentile(probability_paths, 95, axis=0),
    }
    generated_at = datetime.now(timezone.utc).isoformat()
    future_ts = timestamps[-1] + np.arange(1, steps + 1) * median_dt_days * 86_400.0

    return {
        "model": used_model,
        "requestedModel": requested,
        "paths": int(path_matrix.shape[0]),
        "steps": int(steps),
        "stepDays": round(median_dt_days, 6),
        "horizonDays": round(horizon, 4),
        "sampleSize": int(probabilities.size),
        "startProbability": round(current_probability, 4),
        "path": {
            "timestamps": [datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat() for ts in future_ts],
            "median": [round(float(v), 4) for v in percentiles["p50"]],
            "p5": [round(float(v), 4) for v in percentiles["p5"]],
            "p25": [round(float(v), 4) for v in percentiles["p25"]],
            "p75": [round(float(v), 4) for v in percentiles["p75"]],
            "p95": [round(float(v), 4) for v in percentiles["p95"]],
        },
        "terminal": _summarize_terminals(terminal),
        "generatedAt": generated_at,
        "disclaimer": "Monte-Carlo estimate from this market's real traded history; a model output, not a certainty or advice.",
    }
