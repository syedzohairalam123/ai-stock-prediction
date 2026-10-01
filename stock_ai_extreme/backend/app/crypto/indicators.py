"""
Deterministic indicator primitives (spec §12, §14, §24, §85).

Everything here is a pure function over a real price series — no randomness, no
placeholders. A window that cannot be filled yields ``None`` (never 0.0, which
would read as a real measurement), so downstream code can tell "not enough data"
apart from "the value really is zero".

NumPy is used for the vectorisable rolling maths; the return helpers stay close
to the definition so they are easy to audit against spec §12:

    simple return:  close_t / close_{t-1} - 1
    log return:     ln(close_t / close_{t-1})

A non-positive price (or a zero previous close) is treated as an unusable
observation and yields ``None`` rather than ``inf``/``nan``.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

Number = float


# ---------------------------------------------------------------------------
# returns
# ---------------------------------------------------------------------------
def simple_returns(closes: Sequence[float]) -> List[Optional[float]]:
    """
    ``close_t / close_{t-1} - 1``; index 0 is ``None`` (no previous close).

    Inputs must be a chronologically ordered close series — the first element is
    the OLDEST observation, matching every provider's ordering.
    """
    out: List[Optional[float]] = [None]
    for previous, current in zip(closes, closes[1:]):
        if previous is None or current is None or previous <= 0:
            out.append(None)
        else:
            out.append(current / previous - 1.0)
    return out


def log_returns(closes: Sequence[float]) -> List[Optional[float]]:
    """``ln(close_t / close_{t-1})``; index 0 is ``None``."""
    out: List[Optional[float]] = [None]
    for previous, current in zip(closes, closes[1:]):
        if previous is None or current is None or previous <= 0 or current <= 0:
            out.append(None)
        else:
            out.append(math.log(current / previous))
    return out


def cumulative_return(closes: Sequence[float]) -> Optional[float]:
    """Total return across the whole series, or ``None`` when unusable."""
    if len(closes) < 2 or closes[0] is None or closes[-1] is None or closes[0] <= 0:
        return None
    return closes[-1] / closes[0] - 1.0


def pct_change(values: Sequence[float], lookback: int = 1) -> Optional[float]:
    """Return over the last ``lookback`` observations."""
    if lookback <= 0 or len(values) <= lookback:
        return None
    previous = values[-1 - lookback]
    current = values[-1]
    if previous is None or current is None or previous <= 0:
        return None
    return current / previous - 1.0


# ---------------------------------------------------------------------------
# moving averages
# ---------------------------------------------------------------------------
def sma(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Simple moving average, aligned with the input (``None`` until filled)."""
    out: List[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    window = 0.0
    for index, value in enumerate(values):
        window += value
        if index >= period:
            window -= values[index - period]
        if index >= period - 1:
            out[index] = window / period
    return out


def ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """
    Exponential moving average seeded with the first SMA (a real, standard
    convention) so the first reported value is not an arbitrary 1/N guess.
    """
    out: List[Optional[float]] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    seed = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = seed
    previous = seed
    for index in range(period, len(values)):
        previous = alpha * values[index] + (1.0 - alpha) * previous
        out[index] = previous
    return out


def rolling_mean(values: Sequence[float], period: int) -> List[Optional[float]]:
    return sma(values, period)


def rolling_std(
    values: Sequence[float],
    period: int,
    *,
    sample: bool = True,
) -> List[Optional[float]]:
    """
    Rolling standard deviation.

    ``sample=True`` uses the 1/(N-1) estimator (the unbiased convention used for
    realised volatility); population (1/N) is available for other callers.
    """
    out: List[Optional[float]] = [None] * len(values)
    if period <= 1 or len(values) < period:
        return out
    array = np.asarray(values, dtype=float)
    for index in range(period - 1, len(array)):
        window = array[index - period + 1 : index + 1]
        out[index] = float(np.std(window, ddof=1 if sample else 0))
    return out


def slope(values: Sequence[float], period: int) -> Optional[float]:
    """
    Least-squares slope over the last ``period`` observations, expressed as the
    change in the underlying units per step (not normalised) — a descriptive
    measure of direction, not a prediction.
    """
    if period < 2 or len(values) < period:
        return None
    window = np.asarray(values[-period:], dtype=float)
    x = np.arange(period, dtype=float)
    denominator = float(((x - x.mean()) ** 2).sum())
    if denominator == 0:
        return None
    return float(((x - x.mean()) * (window - window.mean())).sum() / denominator)


def momentum(values: Sequence[float], lookback: int) -> Optional[float]:
    """Rate-of-change momentum over ``lookback`` steps (a real return)."""
    return pct_change(values, lookback)


# ---------------------------------------------------------------------------
# oscillators / range
# ---------------------------------------------------------------------------
def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> List[Optional[float]]:
    """``TR = max(H-L, |H-prevC|, |L-prevC|)`` (spec §14)."""
    out: List[Optional[float]] = [None] * len(closes)
    for index in range(len(closes)):
        high, low = highs[index], lows[index]
        if index == 0:
            # No previous close: the only definition available is the bar range.
            out[index] = high - low
            continue
        previous_close = closes[index - 1]
        out[index] = max(high - low, abs(high - previous_close), abs(low - previous_close))
    return out


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> List[Optional[float]]:
    """
    Average True Range using Wilder's smoothing (the standard ATR), seeded with
    the simple mean of the first ``period`` true ranges.
    """
    tr = true_range(highs, lows, closes)
    out: List[Optional[float]] = [None] * len(closes)
    if period <= 0 or len(closes) < period:
        return out
    seed = sum(tr[:period]) / period  # type: ignore[arg-type]
    out[period - 1] = seed
    previous = seed
    for index in range(period, len(closes)):
        previous = (previous * (period - 1) + tr[index]) / period  # type: ignore[operator]
        out[index] = previous
    return out


def rsi(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """
    Wilder's Relative Strength Index over real closes.

    A window with no losses reports 100 and one with no gains reports 0 — those
    are the mathematically correct limits of the formula, not fabricated values.
    """
    out: List[Optional[float]] = [None] * len(closes)
    if period <= 0 or len(closes) <= period:
        return out
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for index in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        out[index + 1] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0 and avg_gain == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def range_position(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> Optional[float]:
    """
    Where the latest close sits inside the recent high/low range, in [0, 1].

    A flat range (high == low) yields ``None`` rather than a made-up 0.5.
    """
    if period < 2 or len(closes) < period:
        return None
    window_high = max(highs[-period:])
    window_low = min(lows[-period:])
    if window_high <= window_low:
        return None
    return (closes[-1] - window_low) / (window_high - window_low)


def range_expansion(highs: Sequence[float], lows: Sequence[float], period: int) -> Optional[float]:
    """
    Latest bar range relative to the mean range over ``period`` bars.

    >1 means this bar is wider than typical (expansion), <1 narrower.
    """
    if period <= 0 or len(highs) <= period:
        return None
    ranges = [h - l for h, l in zip(highs, lows)]  # noqa: E741
    baseline = sum(ranges[-period - 1 : -1]) / period
    if baseline <= 0:
        return None
    return ranges[-1] / baseline


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------
def indicator_bundle(
    *,
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
    rsi_period: int = 14,
    atr_period: int = 14,
    ema_fast: int = 12,
    ema_slow: int = 26,
    momentum_lookback: int = 10,
) -> Dict[str, Optional[float]]:
    """
    Latest value of each configured indicator, in one pass.

    Only the *latest* value per indicator is returned (the rolling series stays
    internal) because that is all the analytics/forecast layer needs; the full
    series is available from the individual functions when required.
    """
    ema_fast_series = ema(closes, ema_fast)
    ema_slow_series = ema(closes, ema_slow)
    rsi_series = rsi(closes, rsi_period)
    atr_series = atr(highs, lows, closes, atr_period)
    latest_atr = atr_series[-1] if atr_series else None
    last_close = closes[-1] if closes else None
    return {
        "ema_fast": ema_fast_series[-1] if ema_fast_series else None,
        "ema_slow": ema_slow_series[-1] if ema_slow_series else None,
        "ema_fast_slope": slope([v for v in ema_fast_series if v is not None], min(ema_fast, 10))
        if any(v is not None for v in ema_fast_series)
        else None,
        "ema_slow_slope": slope([v for v in ema_slow_series if v is not None], min(ema_slow, 10))
        if any(v is not None for v in ema_slow_series)
        else None,
        "sma_slope": slope(list(closes), min(len(closes), max(momentum_lookback, 2))),
        "rsi": rsi_series[-1] if rsi_series else None,
        "atr": latest_atr,
        "atr_percent": (latest_atr / last_close * 100.0) if (latest_atr is not None and last_close) else None,
        "momentum": momentum(list(closes), momentum_lookback),
        "range_position": range_position(highs, lows, closes, min(len(closes), max(momentum_lookback * 2, 10))),
        "range_expansion": range_expansion(highs, lows, min(len(highs) - 1, max(momentum_lookback, 5)))
        if len(highs) > 1
        else None,
        "volume_change": pct_change(list(volumes), 1) if len(volumes) > 1 else None,
    }
