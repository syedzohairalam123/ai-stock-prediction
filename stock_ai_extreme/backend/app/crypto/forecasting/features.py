"""
Leakage-safe feature engineering (spec §24, §25).

Every feature at row ``i`` is computed from candles ``0..i`` only, and the
target is the **future** log return ``ln(close_{i+h} / close_i)``. Because each
indicator used here (SMA, EMA, RSI, ATR, rolling std) is causal by construction,
computing the indicator arrays once and then indexing row ``i`` cannot leak
information from the future — and that property is asserted by the automated
tests in ``app/crypto/tests/test_leakage.py``:

  * truncating the series after row ``i`` must not change row ``i``'s features;
  * the target column must be exactly the future return it claims to be.

Rows where any feature or the target is unavailable are dropped rather than
imputed; a fabricated feature value is exactly what the real-data policy forbids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from app.crypto.config import crypto_settings
from app.crypto.indicators import (
    atr,
    ema,
    log_returns,
    rolling_std,
    rsi,
    simple_returns,
    sma,
)
from app.crypto.schemas import Candle

#: Bumped whenever the feature definitions change, so a stored forecast can be
#: reproduced against the exact feature semantics that produced it (spec §29).
FEATURE_VERSION = "crypto-features-v1"

#: Lookbacks that are always part of the vector.
SHORT_LOOKBACK = 5
LONG_LOOKBACK = 20


@dataclass
class FeatureMatrix:
    """Aligned, leakage-safe design matrix and target for one series."""

    feature_names: List[str]
    X: List[List[float]]
    y: List[float]
    base_close: List[float]
    feature_timestamps: List[datetime]
    target_timestamps: List[datetime]
    #: Candle index each row was built from. Baselines need this to slice the
    #: close series causally (they are evaluated on exactly the same rows as ML).
    candle_indices: List[int] = field(default_factory=list)
    horizon: int = 1
    feature_version: str = FEATURE_VERSION
    #: Diagnostics for the quality/limitations panel.
    dropped_rows: int = 0
    diagnostics: Dict[str, float] = field(default_factory=dict)
    #: The newest *unlabeled* row (no realised target yet) — this is the row a
    #: live forecast is actually generated from. It is produced by the exact same
    #: code path as the training rows, so it cannot drift semantically.
    latest_row: List[float] = field(default_factory=list)
    latest_base_close: Optional[float] = None
    latest_timestamp: Optional[datetime] = None
    latest_candle_index: Optional[int] = None

    @property
    def n_rows(self) -> int:
        return len(self.y)

    def as_arrays(self):
        import numpy as np

        return (
            np.asarray(self.X, dtype=float),
            np.asarray(self.y, dtype=float),
        )


def _safe(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator - 1.0


def build_features(
    candles: Sequence[Candle],
    *,
    horizon: int,
    ema_fast: Optional[int] = None,
    ema_slow: Optional[int] = None,
    rsi_period: Optional[int] = None,
    atr_period: Optional[int] = None,
    vol_window: Optional[int] = None,
) -> FeatureMatrix:
    """
    Build the design matrix for one candle series.

    Returns an empty matrix (with ``diagnostics["reason"]``) when there is not
    enough history — the caller reports ``UNAVAILABLE`` rather than training on
    a toy sample.
    """
    fast = ema_fast or crypto_settings.ema_fast
    slow = ema_slow or crypto_settings.ema_slow
    rsi_n = rsi_period or crypto_settings.rsi_period
    atr_n = atr_period or crypto_settings.atr_period
    vol_n = vol_window or crypto_settings.realized_vol_window

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]
    total = len(closes)

    lookback_needed = max(slow, LONG_LOOKBACK, rsi_n + 1, atr_n, vol_n)
    if horizon < 1 or total < lookback_needed + horizon + 5:
        return FeatureMatrix(
            feature_names=[],
            X=[],
            y=[],
            base_close=[],
            feature_timestamps=[],
            target_timestamps=[],
            candle_indices=[],
            horizon=horizon,
            dropped_rows=0,
            diagnostics={
                "reason": "insufficient history",
                "candles": float(total),
                "required": float(lookback_needed + horizon + 5),
            },
        )

    rets = log_returns(closes)
    simple = simple_returns(closes)
    sma_short = sma(closes, SHORT_LOOKBACK)
    sma_long = sma(closes, LONG_LOOKBACK)
    ema_fast_series = ema(closes, fast)
    ema_slow_series = ema(closes, slow)
    rsi_series = rsi(closes, rsi_n)
    atr_series = atr(highs, lows, closes, atr_n)
    vol_series = rolling_std([r if r is not None else 0.0 for r in rets], vol_n)
    sma_vol_short = sma(volumes, SHORT_LOOKBACK)
    sma_vol_long = sma(volumes, LONG_LOOKBACK)

    feature_names = [
        "log_return_1",
        "log_return_5",
        "log_return_20",
        "sma_5_ratio",
        "sma_20_ratio",
        "ema_fast_ratio",
        "ema_slow_ratio",
        "ema_spread",
        "rsi",
        "atr_percent",
        "volatility",
        "volume_ratio_5",
        "volume_ratio_20",
        "simple_return_1",
    ]

    X: List[List[float]] = []
    y: List[float] = []
    base_close: List[float] = []
    feature_ts: List[datetime] = []
    target_ts: List[datetime] = []
    candle_idx: List[int] = []
    dropped = 0

    latest_row: List[float] = []
    latest_base_close: Optional[float] = None
    latest_timestamp: Optional[datetime] = None
    latest_candle_index: Optional[int] = None

    start = max(lookback_needed, LONG_LOOKBACK, slow, rsi_n, atr_n, vol_n)
    for index in range(start, total):
        close = closes[index]
        if close <= 0:
            dropped += 1
            continue
        has_target = index + horizon < total
        if has_target and closes[index + horizon] <= 0:
            dropped += 1
            continue

        def ret_over(k: int) -> Optional[float]:
            if index - k < 0:
                return None
            previous = closes[index - k]
            if previous <= 0:
                return None
            return math.log(close / previous)

        row: List[Optional[float]] = [
            rets[index],
            ret_over(SHORT_LOOKBACK),
            ret_over(LONG_LOOKBACK),
            _ratio(close, sma_short[index]),
            _ratio(close, sma_long[index]),
            _ratio(close, ema_fast_series[index]),
            _ratio(close, ema_slow_series[index]),
            _safe(
                (ema_fast_series[index] - ema_slow_series[index]) / close
                if ema_fast_series[index] is not None and ema_slow_series[index] is not None
                else None
            ),
            _safe((rsi_series[index] - 50.0) / 50.0 if rsi_series[index] is not None else None),
            _safe(atr_series[index] / close if atr_series[index] is not None else None),
            _safe(vol_series[index]),
            _safe(
                (volumes[index] / sma_vol_short[index] - 1.0)
                if sma_vol_short[index] not in (None, 0)
                else None
            ),
            _safe(
                (volumes[index] / sma_vol_long[index] - 1.0)
                if sma_vol_long[index] not in (None, 0)
                else None
            ),
            simple[index],
        ]

        if any(value is None for value in row):
            dropped += 1
            continue

        numeric_row = [float(value) for value in row]
        if has_target:
            X.append(numeric_row)
            y.append(math.log(closes[index + horizon] / close))
            base_close.append(close)
            feature_ts.append(candles[index].timestamp)
            target_ts.append(candles[index + horizon].timestamp)
            candle_idx.append(index)
        # The newest computable row always becomes the live prediction row.
        latest_row = numeric_row
        latest_base_close = close
        latest_timestamp = candles[index].timestamp
        latest_candle_index = index

    diagnostics = {
        "candles": float(total),
        "rows": float(len(y)),
        "dropped_rows": float(dropped),
        "horizon": float(horizon),
        "lookback": float(start),
    }
    return FeatureMatrix(
        feature_names=feature_names,
        X=X,
        y=y,
        base_close=base_close,
        feature_timestamps=feature_ts,
        target_timestamps=target_ts,
        candle_indices=candle_idx,
        horizon=horizon,
        dropped_rows=dropped,
        diagnostics=diagnostics,
        latest_row=latest_row,
        latest_base_close=latest_base_close,
        latest_timestamp=latest_timestamp,
        latest_candle_index=latest_candle_index,
    )


def latest_matrix(matrix: FeatureMatrix) -> Optional[FeatureMatrix]:
    """A one-row matrix holding the newest unlabeled observation.

    Used to generate a *live* forecast: the model is trained on the labelled
    rows and then applied to this row, whose outcome is genuinely unknown.
    """
    if not matrix.latest_row or matrix.latest_base_close is None:
        return None
    return FeatureMatrix(
        feature_names=matrix.feature_names,
        X=[list(matrix.latest_row)],
        y=[0.0],  # no realised target yet; predict() never reads y
        base_close=[matrix.latest_base_close],
        feature_timestamps=[matrix.latest_timestamp],
        target_timestamps=[],
        candle_indices=[matrix.latest_candle_index if matrix.latest_candle_index is not None else 0],
        horizon=matrix.horizon,
        feature_version=matrix.feature_version,
    )


def target_prices(matrix: FeatureMatrix) -> List[float]:
    """The realised future price for each row (used to evaluate stored forecasts)."""
    return [base * math.exp(target) for base, target in zip(matrix.base_close, matrix.y)]


def feature_statistics(X: Sequence[Sequence[float]], names: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """Per-feature summary used by the drift monitor's reference distribution."""
    import numpy as np

    if not X:
        return {}
    array = np.asarray(X, dtype=float)
    stats: Dict[str, Dict[str, float]] = {}
    for column, name in enumerate(names):
        values = array[:, column]
        stats[name] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            "min": float(values.min()),
            "max": float(values.max()),
        }
    return stats
