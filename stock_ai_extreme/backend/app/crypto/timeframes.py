"""
Timeframe registry + provider capability layer.

Every timeframe string lives here — never scattered through the frontend or the
routers. For each timeframe we record how it is *sourced*:

  * ``native`` — the provider publishes that interval directly (Binance klines
    support 1m/5m/15m/1h/4h/1d/1w/1M), so no transformation is needed.
  * ``ohlcv_rollup`` — the provider has no native interval (there is no native
    yearly candle), so it is aggregated from a lower-resolution real interval
    using the OHLCV roll-up rules in :mod:`app.crypto.normalization`.

Nothing here can fabricate a candle: an unsupported timeframe is reported as
unsupported rather than synthesised.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Dict, List, Optional


class AggregationMethod(str, Enum):
    """How the candles for a timeframe are obtained from the provider."""

    NATIVE = "native"
    OHLCV_ROLLUP = "ohlcv_rollup"


@dataclass(frozen=True)
class TimeframeConfig:
    id: str
    label: str
    duration_seconds: int
    source_interval: str
    aggregation_method: AggregationMethod
    max_history_candles: int
    enabled: bool = True

    @property
    def duration(self) -> timedelta:
        return timedelta(seconds=self.duration_seconds)

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "duration_seconds": self.duration_seconds,
            "source_interval": self.source_interval,
            "aggregation_method": self.aggregation_method.value,
            "max_history_candles": self.max_history_candles,
            "enabled": self.enabled,
        }


#: The complete, ordered registry. `1Y` is a roll-up of 12 monthly candles
#: because no exchange publishes a native yearly candle.
TIMEFRAMES: tuple[TimeframeConfig, ...] = (
    TimeframeConfig("5m", "5 MIN", 300, "5m", AggregationMethod.NATIVE, 1000),
    TimeframeConfig("15m", "15 MIN", 900, "15m", AggregationMethod.NATIVE, 1000),
    TimeframeConfig("1h", "1 HOUR", 3600, "1h", AggregationMethod.NATIVE, 1000),
    TimeframeConfig("4h", "4 HOURS", 14400, "4h", AggregationMethod.NATIVE, 1000),
    TimeframeConfig("1d", "DAILY", 86400, "1d", AggregationMethod.NATIVE, 1000),
    TimeframeConfig("1w", "WEEKLY", 604800, "1w", AggregationMethod.NATIVE, 500),
    TimeframeConfig("1M", "MONTHLY", 2592000, "1M", AggregationMethod.NATIVE, 120),
    TimeframeConfig("1Y", "YEARLY", 31536000, "1M", AggregationMethod.OHLCV_ROLLUP, 12),
)

TIMEFRAME_BY_ID: Dict[str, TimeframeConfig] = {tf.id: tf for tf in TIMEFRAMES}

#: Intervals each supported provider publishes natively. Binance kline
#: intervals per the public docs; a provider absent from this map is assumed
#: to support only the intervals in its config entry.
PROVIDER_NATIVE_INTERVALS: Dict[str, frozenset] = {
    "binance": frozenset(
        {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
    ),
    # CoinGecko's OHLC endpoint exposes only 1/7/14/30/90/180/365-day windows,
    # so it is a coarse history/fallback source rather than a candle provider.
    "coingecko": frozenset({"1d"}),
}

DEFAULT_TIMEFRAME_ID = "5m"


class TimeframeError(ValueError):
    """Raised for an unknown or disabled timeframe id."""


def get_timeframe(timeframe_id: Optional[str]) -> TimeframeConfig:
    """Resolve a timeframe id (defaulting to 5m) or raise :class:`TimeframeError`."""
    key = (timeframe_id or DEFAULT_TIMEFRAME_ID).strip()
    config = TIMEFRAME_BY_ID.get(key)
    if config is None or not config.enabled:
        valid = ", ".join(tf.id for tf in TIMEFRAMES if tf.enabled)
        raise TimeframeError(f"Unknown timeframe {timeframe_id!r}. Expected one of: {valid}.")
    return config


def list_timeframes() -> List[Dict[str, object]]:
    return [tf.to_dict() for tf in TIMEFRAMES if tf.enabled]


def provider_supports(provider: str, interval: str) -> bool:
    native = PROVIDER_NATIVE_INTERVALS.get(provider)
    if native is None:
        return False
    return interval in native


def capabilities(provider: str) -> List[Dict[str, object]]:
    """
    Per-timeframe capability report for a provider.

    ``native`` is true when the provider publishes the interval itself;
    ``aggregation_required`` is true when we must roll up a lower interval, and
    ``supported`` stays false when neither is possible for that provider (so the
    UI can disable the filter instead of showing an empty chart).
    """
    report: List[Dict[str, object]] = []
    for tf in TIMEFRAMES:
        if not tf.enabled:
            continue
        native = provider_supports(provider, tf.source_interval)
        supported = native or tf.aggregation_method is AggregationMethod.OHLCV_ROLLUP
        report.append(
            {
                "id": tf.id,
                "label": tf.label,
                "source_interval": tf.source_interval,
                "native": native,
                "aggregation_required": tf.aggregation_method is AggregationMethod.OHLCV_ROLLUP,
                "aggregation_method": tf.aggregation_method.value,
                "supported": supported,
                "max_history_candles": tf.max_history_candles,
            }
        )
    return report
