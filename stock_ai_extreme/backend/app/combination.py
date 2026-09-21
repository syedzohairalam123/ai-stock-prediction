"""
Phase 15.1/15.2 — correlation-adjusted multi-event combination analysis.

The frontend's `CombinationCalculator` multiplies decimal probabilities, which
is exactly correct only when the events are independent. For real forecast
markets they usually are not: two elections share a national mood, two rate
decisions share an inflation print, two crypto markets share BTC. Multiplying
them then silently overstates the joint probability.

This module estimates the *empirical* dependence from the markets' real traded
probability histories (Phase 14.1) and combines them accordingly.

Method
------
1. **Align** each selected event's YES/NO probability series onto their common
   observation window (union of timestamps, forward-filled).
2. **Dependence** is measured on log-odds *returns* (first differences), which
   are closer to stationary than the raw probability level:
   * Pearson correlation (linear co-movement),
   * Spearman rank correlation (monotone, robust to outliers),
   * lead-lag cross-correlation over `±MAX_LAG` steps (who moves first).
3. The Pearson matrix is **projected to the nearest positive-definite matrix**
   (eigenvalue clipping) so it can be used as a Gaussian-copula correlation.
4. **Combination** uses a Gaussian copula: draw correlated latent normals
   `z ~ N(0, R)` via Cholesky, map to uniforms `u = Phi(z)`, and treat event `i`
   as YES when `u_i <= p_i`. Monte-Carlo then yields `P(all YES)`, an exact
   `exactly-k` distribution, a confidence interval, and `P(at least one)`.
5. **Sensitivity**: one-at-a-time ±Δ perturbation of each input produces a
   tornado chart; the same engine produces the all-events scenario grid.

Honesty rules
-------------
* If two markets share too few overlapping observations, their correlation is
  not identifiable and is set to **0** for that pair, with the reason surfaced.
  The result is then flagged `correlationApplied: false` only when *no* pair
  could be estimated; partial identification is reported per pair.
* The independence result is always returned alongside the adjusted one, never
  hidden.
* No historical data -> the engine falls back to the independence product and
  says so.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy import stats as scipy_stats

from .config import settings
from .logging_config import get_logger

logger = get_logger("neural_market.combination")

#: How many steps of lead/lag to scan for cross-correlation.
MAX_LAG = 3

#: Probability clamp for log-odds.
_EPS = 1e-4


def _logit(p: np.ndarray) -> np.ndarray:
    clipped = np.clip(p, _EPS, 1.0 - _EPS)
    return np.log(clipped / (1.0 - clipped))


def _parse_point(point: dict[str, Any]) -> tuple[float, float] | None:
    try:
        ts = datetime.fromisoformat(str(point.get("timestamp")).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None
    for key in ("yesProbability", "probability", "yes_probability"):
        if key in point:
            try:
                probability = float(point[key])
            except (TypeError, ValueError):
                continue
            if math.isfinite(probability) and 0.0 <= probability <= 100.0:
                return ts, probability
    return None


def selected_probability_point(point: dict[str, Any], outcome: str) -> float | None:
    """The probability of the *selected outcome* at one history point."""
    yes = point.get("yesProbability")
    no = point.get("noProbability")
    if outcome == "NO":
        if no is not None:
            try:
                return float(no)
            except (TypeError, ValueError):
                pass
        if yes is not None:
            try:
                return 100.0 - float(yes)
            except (TypeError, ValueError):
                return None
        return None
    if yes is None:
        return None
    try:
        return float(yes)
    except (TypeError, ValueError):
        return None


def _series_for_event(event: dict[str, Any]) -> list[tuple[float, float]]:
    outcome = str(event.get("outcome") or "YES").upper()
    out: list[tuple[float, float]] = []
    for point in event.get("history") or []:
        if not isinstance(point, dict):
            continue
        parsed = _parse_point(point)
        if parsed is None:
            continue
        ts, _ = parsed
        probability = selected_probability_point(point, outcome)
        if probability is None or not math.isfinite(probability):
            continue
        if not 0.0 < probability < 100.0:
            # 0/100 has infinite log-odds; skip rather than fabricate a level.
            continue
        out.append((ts, probability))
    out.sort(key=lambda row: row[0])
    return out


def align_series(events: list[dict[str, Any]]) -> np.ndarray | None:
    """Forward-fill each event's series onto their shared observation window.

    Returns an array of shape `(n_events, n_observations)` in probability units
    (0..100), or `None` when there is no usable overlap.
    """
    series = [_series_for_event(event) for event in events]
    if any(len(s) < 2 for s in series):
        return None

    union = sorted({ts for s in series for ts, _ in s})
    if len(union) < 2:
        return None

    matrix = np.full((len(series), len(union)), np.nan)
    for i, s in enumerate(series):
        index = {ts: p for ts, p in s}
        last: float | None = None
        for j, ts in enumerate(union):
            if ts in index:
                last = index[ts]
            matrix[i, j] = last

    # Drop leading columns where any series has not started yet, and any column
    # that a series never covered at all.
    valid_columns = ~np.isnan(matrix).any(axis=0)
    matrix = matrix[:, valid_columns]
    if matrix.shape[1] < 2:
        return None
    return matrix


def log_odds_returns(probability_matrix: np.ndarray) -> np.ndarray:
    """First differences of log-odds, one row per event."""
    log_odds = _logit(probability_matrix / 100.0)
    return np.diff(log_odds, axis=1)


def _clean_correlation(raw: np.ndarray) -> np.ndarray:
    """Replace NaN/inf off-diagonals with 0 and force a unit diagonal."""
    m = raw.shape[0]
    clean = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
    clean = np.clip(clean, -1.0, 1.0)
    np.fill_diagonal(clean, 1.0)
    return clean


def nearest_positive_definite(corr: np.ndarray) -> np.ndarray:
    """Nearest correlation matrix that is positive definite (eigenvalue clip)."""
    sym = (corr + corr.T) / 2.0
    values, vectors = np.linalg.eigh(sym)
    values = np.clip(values, 1e-8, None)
    reconstructed = vectors @ np.diag(values) @ vectors.T
    diag = np.sqrt(np.clip(np.diag(reconstructed), 1e-12, None))
    fixed = reconstructed / np.outer(diag, diag)
    np.fill_diagonal(fixed, 1.0)
    return fixed


def lead_lag_matrix(returns: np.ndarray, max_lag: int = MAX_LAG) -> list[list[dict[str, float]]]:
    """Best cross-correlation and its lag for every ordered pair.

    Positive lag means row *i* leads row *j* (i's change at t correlates with
    j's change at t+lag).
    """
    n = returns.shape[0]
    out: list[list[dict[str, float]]] = [[{"correlation": 0.0, "lag": 0} for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                out[i][j] = {"correlation": 1.0, "lag": 0}
                continue
            best_corr = 0.0
            best_lag = 0
            for lag in range(-max_lag, max_lag + 1):
                if lag > 0:
                    a = returns[i, :-lag] if lag < returns.shape[1] else np.empty(0)
                    b = returns[j, lag:]
                elif lag < 0:
                    a = returns[i, -lag:]
                    b = returns[j, :lag]
                else:
                    a, b = returns[i], returns[j]
                if a.size < 3 or a.size != b.size:
                    continue
                if np.std(a) < 1e-12 or np.std(b) < 1e-12:
                    continue
                corr = float(np.corrcoef(a, b)[0, 1])
                if math.isfinite(corr) and abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag
            out[i][j] = {"correlation": round(best_corr, 4), "lag": int(best_lag)}
    return out


def build_correlation(
    events: list[dict[str, Any]],
    *,
    min_overlap: int | None = None,
) -> dict[str, Any]:
    """Full correlation report for the selected events."""
    min_overlap = min_overlap if min_overlap is not None else settings.combination_min_overlap_points
    n = len(events)
    if n < 2:
        return {
            "method": "LOG_ODDS_RETURNS",
            "matrix": [[1.0]],
            "spearman": [[1.0]],
            "pearson": [[1.0]],
            "leadLag": [[{"correlation": 1.0, "lag": 0}]],
            "observations": 1,
            "pairwiseOverlap": {},
            "applied": False,
            "reason": "At least two events are required for correlation analysis.",
        }

    matrix = align_series(events)
    if matrix is None:
        return {
            "method": "LOG_ODDS_RETURNS",
            "matrix": _clean_correlation(np.eye(n)),
            "spearman": _clean_correlation(np.eye(n)),
            "pearson": _clean_correlation(np.eye(n)),
            "leadLag": lead_lag_matrix(np.zeros((n, 2))),
            "observations": 0,
            "pairwiseOverlap": {},
            "applied": False,
            "reason": "Not enough overlapping real probability history; combined probability falls back to independence.",
        }

    returns = log_odds_returns(matrix)
    observations = int(returns.shape[1])

    if observations < 2:
        return {
            "method": "LOG_ODDS_RETURNS",
            "matrix": _clean_correlation(np.eye(n)),
            "spearman": _clean_correlation(np.eye(n)),
            "pearson": _clean_correlation(np.eye(n)),
            "leadLag": lead_lag_matrix(returns),
            "observations": observations,
            "pairwiseOverlap": {},
            "applied": False,
            "reason": "Overlapping history is too short to estimate dependence; independence assumed.",
        }

    with np.errstate(invalid="ignore", divide="ignore"):
        pearson = _clean_correlation(np.corrcoef(returns))
    try:
        spearman = _clean_correlation(scipy_stats.spearmanr(returns, axis=1).correlation)
    except Exception:
        spearman = _clean_correlation(np.eye(n))

    # Pairwise overlap counts: how many of the aligned observations both series
    # actually observed (not forward-filled in one of them).
    pairwise: dict[str, int] = {}
    raw_series = [_series_for_event(event) for event in events]
    for i in range(n):
        for j in range(i + 1, n):
            set_i = {ts for ts, _ in raw_series[i]}
            set_j = {ts for ts, _ in raw_series[j]}
            pairwise[f"{i}-{j}"] = len(set_i & set_j)

    applied = observations >= min_overlap
    reason = None
    if not applied:
        reason = (
            f"Only {observations} overlapping log-odds observations (< {min_overlap}); "
            "dependence is not identifiable, independence assumed."
        )

    corr = pearson if applied else np.eye(n)
    corr = _clean_correlation(corr)
    try:
        corr = nearest_positive_definite(corr)
    except np.linalg.LinAlgError:
        corr = _clean_correlation(np.eye(n))

    return {
        "method": "LOG_ODDS_RETURNS",
        "matrix": [[round(float(v), 4) for v in row] for row in corr],
        "pearson": [[round(float(v), 4) for v in row] for row in (pearson if applied else np.eye(n))],
        "spearman": [[round(float(v), 4) for v in row] for row in (spearman if applied else np.eye(n))],
        "leadLag": lead_lag_matrix(returns),
        "observations": observations,
        "pairwiseOverlap": pairwise,
        "applied": bool(applied),
        "reason": reason,
    }


def copula_draws(probabilities: np.ndarray, corr: np.ndarray, draws: int, rng: np.random.Generator) -> np.ndarray:
    """Boolean `(draws, n)` matrix of correlated Bernoulli outcomes via Gaussian copula."""
    m = probabilities.size
    if m == 0:
        return np.zeros((draws, 0), dtype=bool)
    try:
        chol = np.linalg.cholesky(nearest_positive_definite(corr))
    except np.linalg.LinAlgError:
        chol = np.eye(m)
    z = rng.standard_normal((draws, m)) @ chol.T
    uniforms = scipy_stats.norm.cdf(z)
    return uniforms <= (probabilities / 100.0)


def combined_from_draws(draws_matrix: np.ndarray) -> dict[str, Any]:
    """Summaries derivable from one set of correlated draws."""
    if draws_matrix.size == 0:
        return {"combinedProbability": 0.0, "atLeastOne": 0.0, "exactlyK": {}}
    all_yes = draws_matrix.all(axis=1)
    count = draws_matrix.sum(axis=1)
    m = draws_matrix.shape[1]
    return {
        "combinedProbability": round(float(all_yes.mean()) * 100.0, 2),
        "atLeastOne": round(float((count >= 1).mean()) * 100.0, 2),
        "exactlyK": {str(k): round(float((count == k).mean()) * 100.0, 2) for k in range(m + 1)},
    }


def combine_events(
    events: list[dict[str, Any]],
    *,
    draws: int | None = None,
    delta_pp: float | None = None,
    seed: int | None = None,
    include_sensitivity: bool = True,
) -> dict[str, Any]:
    """Combine selected events with correlation adjustment and sensitivity.

    `events`: list of `{id, marketId?, label?, outcome, probability, history?}`.
    """
    if not events:
        raise ValueError("At least one event is required.")

    n = len(events)
    probabilities = np.array([float(e.get("probability") or 0.0) for e in events], dtype=float)
    if np.any(~np.isfinite(probabilities)) or np.any(probabilities < 0) or np.any(probabilities > 100):
        raise ValueError("Every event probability must be a number between 0 and 100.")

    correlation = build_correlation(events)
    corr_matrix = np.array(correlation["matrix"], dtype=float)
    if corr_matrix.shape != (n, n):
        corr_matrix = np.eye(n)
    corr_matrix = nearest_positive_definite(corr_matrix)

    draws = int(draws or settings.combination_monte_carlo_draws)
    draws = max(1000, min(draws, 200000))
    rng = np.random.default_rng(seed)

    base_draws = copula_draws(probabilities, corr_matrix, draws, rng)
    adjusted = combined_from_draws(base_draws)

    independence_product = float(np.prod(probabilities / 100.0) * 100.0)

    p = adjusted["combinedProbability"] / 100.0
    se = math.sqrt(max(p * (1.0 - p), 0.0) / draws)

    result: dict[str, Any] = {
        "count": n,
        "draws": draws,
        "eventLabels": [str(e.get("label") or e.get("marketId") or e.get("id") or f"Event {i + 1}") for i, e in enumerate(events)],
        "inputProbabilities": [round(float(v), 4) for v in probabilities],
        "independenceProbability": round(independence_product, 2),
        "correlationAdjustedProbability": adjusted["combinedProbability"],
        "correlationAdjustmentPp": round(adjusted["combinedProbability"] - independence_product, 2),
        "confidenceInterval95": [
            round(max(p - 1.96 * se, 0.0) * 100.0, 2),
            round(min(p + 1.96 * se, 1.0) * 100.0, 2),
        ],
        "atLeastOneProbability": adjusted["atLeastOne"],
        "exactlyKProbability": adjusted["exactlyK"],
        "correlation": correlation,
        "correlationApplied": correlation.get("applied", False),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Combined probability for educational analysis only; not advice, a price, or a wager.",
    }

    if include_sensitivity:
        delta = float(delta_pp if delta_pp is not None else settings.combination_sensitivity_delta_pp)
        result["sensitivity"] = _sensitivity(events, probabilities, corr_matrix, delta, draws, seed)

    return result


def _sensitivity(
    events: list[dict[str, Any]],
    probabilities: np.ndarray,
    corr_matrix: np.ndarray,
    delta: float,
    draws: int,
    seed: int | None,
) -> dict[str, Any]:
    """Tornado (one-at-a-time ±Δ) plus cumulative scenario grid."""
    n = probabilities.size
    rng = np.random.default_rng(seed if seed is None else seed + 1)
    base = float(np.prod(probabilities / 100.0) * 100.0)

    def combined_for(values: np.ndarray) -> float:
        matrix = copula_draws(values, corr_matrix, draws, rng)
        return combined_from_draws(matrix)["combinedProbability"]

    tornado: list[dict[str, Any]] = []
    for i, event in enumerate(events):
        low_values = probabilities.copy()
        high_values = probabilities.copy()
        low_values[i] = max(0.0, probabilities[i] - delta)
        high_values[i] = min(100.0, probabilities[i] + delta)
        low = combined_for(low_values)
        high = combined_for(high_values)
        tornado.append(
            {
                "index": i,
                "label": str(event.get("label") or event.get("marketId") or event.get("id") or f"Event {i + 1}"),
                "baseProbability": round(float(probabilities[i]), 4),
                "low": low,
                "high": high,
                "deltaLow": round(low - base, 2),
                "deltaHigh": round(high - base, 2),
                "swing": round(abs(high - low), 2),
            }
        )
    tornado.sort(key=lambda row: row["swing"], reverse=True)

    all_low = np.clip(probabilities - delta, 0.0, 100.0)
    all_high = np.clip(probabilities + delta, 0.0, 100.0)
    scenarios = [
        {"name": f"All events −{delta:g}pp", "probability": combined_for(all_low)},
        {"name": "Base case", "probability": base},
        {"name": f"All events +{delta:g}pp", "probability": combined_for(all_high)},
    ]

    return {
        "deltaPp": delta,
        "baseIndependence": round(base, 2),
        "tornado": tornado,
        "scenarios": scenarios,
    }


def correlation_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Correlation-only report (no combination) for the correlate endpoint."""
    correlation = build_correlation(events)
    return {
        "eventLabels": [str(e.get("label") or e.get("marketId") or e.get("id") or f"Event {i + 1}") for i, e in enumerate(events)],
        **correlation,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
