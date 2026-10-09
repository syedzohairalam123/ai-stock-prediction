"""Phase 23B — numpy/scipy-backed analytics (spec §17).

The pure direction/market-cap logic in :mod:`direction` and :mod:`companies`
deliberately stays dependency-free, because a one-line return or a price×shares
product does not need a data-science stack. This module is the one place that
*does* justify NumPy and SciPy: multi-session return arrays, rolling
statistics, correlations and drawdowns where a vectorised implementation is
both clearer and less error-prone than a hand-written loop.

Every function is pure and offline-testable and returns ``None`` (or an empty
result) rather than a fabricated number when the input cannot support the
computation — the same honesty contract the rest of the module follows.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

import numpy as np

try:  # SciPy is an optional nicety here; NumPy alone covers the fallbacks.
    from scipy import stats as _scipy_stats
except Exception:  # pragma: no cover - exercised only when SciPy is absent
    _scipy_stats = None


def _clean(values: Iterable[float]) -> np.ndarray:
    """A float64 array with NaN/inf dropped — never coerced to zero."""
    array = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    if array.size == 0:
        return array
    return array[np.isfinite(array)]


# ---------------------------------------------------------------------------
# Simple-series measures (spec §4)
# ---------------------------------------------------------------------------


def simple_returns(closes: Sequence[float]) -> np.ndarray:
    """``close[t]/close[t-1] - 1`` for a series of closes (spec §3).

    Nothing is interpolated: the caller must already have real consecutive
    sessions. A non-positive prior close makes that step incomputable and it is
    dropped rather than replaced with 0.
    """
    clean = _clean(closes)
    if clean.size < 2:
        return np.asarray([], dtype=float)
    prior = clean[:-1]
    current = clean[1:]
    mask = prior != 0
    return (current[mask] / prior[mask]) - 1.0


def annualized_volatility(returns: Sequence[float], periods_per_year: int = 252, ddof: int = 1) -> Optional[float]:
    """Annualised standard deviation of a return series, in percent.

    Fewer than two observations cannot produce a sample standard deviation, so
    the function returns ``None`` instead of a misleading zero.
    """
    array = _clean(returns)
    if array.size < 2:
        return None
    std = float(np.std(array, ddof=ddof))
    return round(std * math.sqrt(periods_per_year) * 100.0, 6)


def mean_return(returns: Sequence[float]) -> Optional[float]:
    array = _clean(returns)
    return round(float(np.mean(array)) * 100.0, 6) if array.size else None


def rolling_mean_std(
    returns: Sequence[float], window: int
) -> tuple[np.ndarray, np.ndarray]:
    """Rolling mean and sample std over ``window`` observations.

    Returns ``(means, stds)`` with the same length as the input; positions with
    fewer than two observations in their window carry ``nan`` so a caller can
    tell "not computable yet" from a real zero.
    """
    window = max(2, int(window))
    array = _clean(returns)
    if array.size == 0:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    means = np.full(array.shape, np.nan)
    stds = np.full(array.shape, np.nan)
    for index in range(array.size):
        start = max(0, index - window + 1)
        chunk = array[start : index + 1]
        if chunk.size == 0:
            continue
        means[index] = float(np.mean(chunk))
        if chunk.size >= 2:
            stds[index] = float(np.std(chunk, ddof=1))
    return means, stds


def value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> Optional[float]:
    """Historical (empirical) VaR as a negative return in percent.

    This is the observed quantile of the real return sample — it is a
    descriptive figure, never a model forecast.
    """
    array = _clean(returns)
    if array.size < 5:
        return None
    return round(float(np.quantile(array, 1.0 - confidence)) * 100.0, 6)


# ---------------------------------------------------------------------------
# Drawdown (spec §4, §6)
# ---------------------------------------------------------------------------


def max_drawdown(closes: Sequence[float]) -> Optional[float]:
    """Largest peak-to-trough decline of a close series, in percent (negative).

    A drawdown is only defined with at least two real closes.
    """
    array = _clean(closes)
    if array.size < 2:
        return None
    running_peak = np.maximum.accumulate(array)
    peak_ok = running_peak != 0
    if not peak_ok.any():
        return None
    drawdowns = np.where(peak_ok, array / running_peak - 1.0, 0.0)
    return round(float(np.min(drawdowns)) * 100.0, 6)


# ---------------------------------------------------------------------------
# Relationship between two instruments (spec §6)
# ---------------------------------------------------------------------------


def pearson_correlation(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    """Pearson correlation of two equally-sized, real-valued samples."""
    a = _clean(left)
    b = _clean(right)
    if a.size < 2 or a.size != b.size:
        return None
    if float(np.std(a)) == 0 or float(np.std(b)) == 0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 6)


def spearman_rank_correlation(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    """Rank correlation of two samples — SciPy when available, else a manual rank.

    Used for the market-cap race to describe how consistently two companies'
    observed caps move together, without asserting causation.
    """
    a = _clean(left)
    b = _clean(right)
    if a.size < 3 or a.size != b.size:
        return None
    if _scipy_stats is not None:
        rho, _ = _scipy_stats.spearmanr(a, b)
        if rho is None or math.isnan(float(rho)):
            return None
        return round(float(rho), 6)
    # SciPy-free fallback: rank both sides then run Pearson on the ranks.
    def _rank(values: np.ndarray) -> np.ndarray:
        order = values.argsort()
        ranks = np.empty(values.shape, dtype=float)
        ranks[order] = np.arange(values.size, dtype=float)
        return ranks

    return pearson_correlation(_rank(a), _rank(b))
