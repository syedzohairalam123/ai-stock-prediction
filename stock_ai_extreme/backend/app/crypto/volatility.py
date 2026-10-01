"""
Volatility engine (spec §13, §15).

Four independent, well-understood measures — never a single invented "risk
score":

  * rolling standard deviation of log returns
  * realised volatility (annualised σ of log returns over a configured window)
  * ATR and ATR% (Wilder, from real high/low/close)
  * range-based volatility (mean (high-low)/close)

The regime is classified **against the asset's own historical distribution**
(spec §15) using configurable percentiles, so "HIGH" means "high for this
asset on this timeframe" instead of an arbitrary absolute number. When there is
not enough history to build a distribution, the regime is
``INSUFFICIENT_DATA`` — a real answer, not a fallback guess.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.crypto.config import crypto_settings
from app.crypto.indicators import atr, log_returns, rolling_std
from app.crypto.schemas import VolatilityRegime, VolatilitySnapshot

#: Seconds per year — the conventional annualisation denominator for 24/7 crypto.
SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0

#: Minimum number of return observations before an annualised figure is honest.
MIN_VOL_SAMPLES = 5

#: Rolling windows must contain at least this many points to build a
#: distribution for the regime classifier.
MIN_REGIME_SAMPLES = 6


def periods_per_year(duration_seconds: int) -> float:
    """How many bars of ``duration_seconds`` fit in a year."""
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    return float(SECONDS_PER_YEAR) / float(duration_seconds)


def realized_volatility(
    returns: Sequence[Optional[float]],
    *,
    window: int,
    duration_seconds: int,
    sample: bool = True,
) -> Optional[float]:
    """
    Annualised realised volatility from a real log-return series.

    ``σ_annual = std(r) * sqrt(periods_per_year)`` — the standard close-to-close
    estimator. Requires at least :data:`MIN_VOL_SAMPLES` usable returns.
    """
    usable = [r for r in returns[-window:] if r is not None]
    if len(usable) < max(MIN_VOL_SAMPLES, 3):
        return None
    array = np.asarray(usable, dtype=float)
    std = float(np.std(array, ddof=1 if sample else 0))
    return std * math.sqrt(periods_per_year(duration_seconds))


def realized_volatility_series(
    returns: Sequence[Optional[float]],
    *,
    window: int,
    duration_seconds: int,
) -> List[Optional[float]]:
    """
    Rolling realised volatility, used to build the historical distribution the
    regime classifier reads. Emitted only where the window is genuinely filled.
    """
    out: List[Optional[float]] = [None] * len(returns)
    for index in range(window, len(returns) + 1):
        window_slice = returns[index - window : index]
        value = realized_volatility(
            window_slice, window=window, duration_seconds=duration_seconds
        )
        if value is not None:
            out[index - 1] = value
    return out


def rolling_volatility(
    closes: Sequence[float], *, window: int, duration_seconds: int
) -> Optional[float]:
    """Convenience: realised volatility straight from closes."""
    return realized_volatility(
        log_returns(list(closes)), window=window, duration_seconds=duration_seconds
    )


def range_volatility(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], *, window: int
) -> Optional[float]:
    """
    Mean bar range as a fraction of close over the window.

    A volatility measure that does not depend on the return-sampling convention,
    so it is a genuine cross-check on the close-to-close estimate.
    """
    if window <= 0 or len(closes) < window:
        return None
    numerators: List[float] = []
    for high, low, close in zip(highs[-window:], lows[-window:], closes[-window:]):
        if close and close > 0:
            numerators.append((high - low) / close)
    if not numerators:
        return None
    return float(sum(numerators) / len(numerators))


def volatility_percentile(
    history: Sequence[Optional[float]], current: Optional[float]
) -> Optional[float]:
    """
    Percentile rank of ``current`` within its own historical distribution.

    Uses the mid-rank definition (half credit for ties) so a repeated value is
    not overstated. Returns ``None`` when the distribution is too small.
    """
    usable = [value for value in history if value is not None]
    if current is None or len(usable) < MIN_REGIME_SAMPLES:
        return None
    below = sum(1 for value in usable if value < current)
    equal = sum(1 for value in usable if value == current)
    return (below + 0.5 * equal) / len(usable) * 100.0


def classify_regime(
    *,
    percentile: Optional[float],
    low_percentile: Optional[float] = None,
    high_percentile: Optional[float] = None,
    extreme_percentile: Optional[float] = None,
) -> VolatilityRegime:
    """
    Map a percentile of the asset's own volatility distribution to a regime.

    Configurable thresholds (spec §15) live in :mod:`app.crypto.config`; the
    default split is LOW (<20th), NORMAL (20–80th), HIGH (80–95th),
    EXTREME (>=95th).
    """
    if percentile is None:
        return VolatilityRegime.INSUFFICIENT_DATA
    low = crypto_settings.regime_low_percentile if low_percentile is None else low_percentile
    high = crypto_settings.regime_high_percentile if high_percentile is None else high_percentile
    extreme = (
        crypto_settings.regime_extreme_percentile if extreme_percentile is None else extreme_percentile
    )
    if percentile >= extreme:
        return VolatilityRegime.EXTREME
    if percentile >= high:
        return VolatilityRegime.HIGH
    if percentile < low:
        return VolatilityRegime.LOW
    return VolatilityRegime.NORMAL


class VolatilityEngine:
    """Stateless volatility computation over a real candle series."""

    def snapshot(
        self,
        *,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        duration_seconds: int,
        timeframe: str,
        window: Optional[int] = None,
        atr_period: Optional[int] = None,
        data_status=None,
    ) -> VolatilitySnapshot:
        from app.crypto.schemas import DataStatus

        resolved_window = window or crypto_settings.realized_vol_window
        resolved_atr_period = atr_period or crypto_settings.atr_period

        returns = log_returns(list(closes))
        realized = realized_volatility(
            returns, window=resolved_window, duration_seconds=duration_seconds
        )
        rolling = rolling_volatility(
            closes, window=resolved_window, duration_seconds=duration_seconds
        )
        atr_series = atr(list(highs), list(lows), list(closes), resolved_atr_period)
        latest_atr = atr_series[-1] if atr_series else None
        last_close = closes[-1] if closes else None

        # Regime: compare the latest realised vol against the asset's own
        # rolling realised-volatility distribution over the full series.
        distribution = realized_volatility_series(
            returns, window=resolved_window, duration_seconds=duration_seconds
        )
        percentile = volatility_percentile(distribution, realized)
        regime = classify_regime(percentile=percentile)

        return VolatilitySnapshot(
            timeframe=timeframe,
            realized_volatility=realized,
            rolling_std=(
                _latest(rolling_std(list(closes), resolved_window)) if len(closes) >= resolved_window else None
            ),
            atr=latest_atr,
            atr_percent=(
                latest_atr / last_close * 100.0
                if (latest_atr is not None and last_close and last_close > 0)
                else None
            ),
            range_volatility=range_volatility(
                list(highs), list(lows), list(closes), window=resolved_window
            ),
            volatility_percentile=percentile,
            regime=regime,
            window=resolved_window,
            sample_size=len(closes),
            data_status=data_status or (DataStatus.UNAVAILABLE if not closes else DataStatus.LIVE),
        )

    def history(
        self,
        *,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        duration_seconds: int,
        window: Optional[int] = None,
    ) -> List[Optional[float]]:
        """Rolling realised-volatility series (for the trend-history chart)."""
        resolved_window = window or crypto_settings.realized_vol_window
        return realized_volatility_series(
            log_returns(list(closes)),
            window=resolved_window,
            duration_seconds=duration_seconds,
        )


def _latest(series: Sequence[Optional[float]]) -> Optional[float]:
    for value in reversed(series):
        if value is not None:
            return value
    return None


def regime_summary(snapshot: VolatilitySnapshot) -> Dict[str, object]:
    """Small, JSON-safe digest for API meta blocks."""
    return {
        "regime": snapshot.regime.value,
        "percentile": snapshot.volatility_percentile,
        "realized_volatility": snapshot.realized_volatility,
        "atr_percent": snapshot.atr_percent,
        "window": snapshot.window,
        "sample_size": snapshot.sample_size,
    }


#: Process-wide singleton (stateless, kept for a consistent import surface).
volatility_engine = VolatilityEngine()
