"""
Data freshness + quality + value-origin labelling (spec §54, §55, §56, §99).

Freshness is judged from the **provider's own publication timestamp**, never
from when this process happened to fetch the data. That distinction is the whole
point of the module: a quote fetched 2 ms ago that the source stamped 40 minutes
ago is DELAYED, not LIVE.

Quality is a blend of five independent, checkable inputs — candle completeness,
timestamp freshness, provider health, candle continuity and symbol-mapping
integrity — and it degrades to ``UNAVAILABLE`` when there is nothing to judge.

:data:`ValueOrigin` rides on every returned value so the architecture can always
answer "is this SOURCE, CALCULATED, MODELLED, DERIVED or UNAVAILABLE?" — the
distinction spec §99 forbids hiding from the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.crypto.schemas import DataGapReport, DataStatus, QualityLabel, ValueOrigin

#: Freshness bands (seconds of age relative to the source timestamp).
#: Documented rather than arbitrary: public crypto feeds tick continuously, so a
#: 5-minute-old *source* timestamp is already late for an intraday view.
LIVE_MAX_AGE_SECONDS = 60
RECENT_MAX_AGE_SECONDS = 300
DELAYED_MAX_AGE_SECONDS = 3600

#: For slow timeframes a bar only closes once per period, so the newest closed
#: bar is legitimately older than these bands. Callers pass the bar duration.
SLOW_TIMEFRAME_GRACE_MULTIPLIER = 1.5


@dataclass
class QualityAssessment:
    """The full quality verdict for one dataset."""

    label: QualityLabel
    status: DataStatus
    age_ms: Optional[int]
    completeness: Optional[float]
    driver: str
    components: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label.value,
            "status": self.status.value,
            "age_ms": self.age_ms,
            "completeness": self.completeness,
            "driver": self.driver,
            "components": self.components,
        }


def age_seconds(source_timestamp: Optional[datetime], *, now: Optional[datetime] = None) -> Optional[float]:
    """Age of a source timestamp in seconds; ``None`` when the source is silent."""
    if source_timestamp is None:
        return None
    reference = source_timestamp
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return (current - reference).total_seconds()


def freshness_status(
    source_timestamp: Optional[datetime],
    *,
    bar_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> DataStatus:
    """
    Map a source timestamp to a freshness label.

    A slow timeframe is granted a bar-length grace window: on a daily chart the
    newest closed bar is up to a day old by construction, which is not staleness.
    """
    seconds = age_seconds(source_timestamp, now=now)
    if seconds is None:
        return DataStatus.UNAVAILABLE
    if seconds < 0:
        # The source is ahead of us: report LIVE, and let the caller note the skew.
        return DataStatus.LIVE
    grace = 0.0
    if bar_seconds:
        grace = max(0.0, bar_seconds * SLOW_TIMEFRAME_GRACE_MULTIPLIER - LIVE_MAX_AGE_SECONDS)
    if seconds <= LIVE_MAX_AGE_SECONDS + grace:
        return DataStatus.LIVE
    if seconds <= RECENT_MAX_AGE_SECONDS + grace:
        return DataStatus.RECENT
    if seconds <= DELAYED_MAX_AGE_SECONDS + grace:
        return DataStatus.DELAYED
    return DataStatus.STALE


def assess(
    *,
    source_timestamp: Optional[datetime],
    gap_report: Optional[DataGapReport] = None,
    provider_healthy: Optional[bool] = None,
    symbol_mapped: bool = True,
    candle_count: int = 0,
    bar_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> QualityAssessment:
    """
    Blend the five quality inputs into HIGH / MEDIUM / LOW / UNAVAILABLE (spec §55).

    Each component contributes a real, bounded penalty; the driver of the worst
    penalty is reported so the UI can explain *why* quality is not HIGH.
    """
    status = freshness_status(source_timestamp, bar_seconds=bar_seconds, now=now)
    seconds = age_seconds(source_timestamp, now=now)
    components: Dict[str, Any] = {
        "freshness": status.value,
        "age_seconds": seconds,
        "provider_healthy": provider_healthy,
        "symbol_mapped": symbol_mapped,
        "candles": candle_count,
    }

    if candle_count == 0 or status is DataStatus.UNAVAILABLE:
        return QualityAssessment(
            label=QualityLabel.UNAVAILABLE,
            status=DataStatus.UNAVAILABLE,
            age_ms=None if seconds is None else int(max(0.0, seconds) * 1000),
            completeness=gap_report.completeness if gap_report else None,
            driver="no usable data from the configured source",
            components=components,
        )

    penalty = 0.0
    driver = "clean"

    if status is DataStatus.STALE:
        penalty += 0.7
        driver = "source timestamp is stale"
    elif status is DataStatus.DELAYED:
        penalty += 0.4
        driver = "provider timestamp is delayed"
    elif status is DataStatus.RECENT:
        penalty += 0.1

    if gap_report is not None:
        components["completeness"] = gap_report.completeness
        components["missing_intervals"] = gap_report.missing_intervals
        if gap_report.completeness < 0.9:
            gap_penalty = min(0.5, (1.0 - gap_report.completeness) * 1.5)
            penalty += gap_penalty
            if gap_penalty > 0.2:
                driver = "candle gaps in the requested range"

    if provider_healthy is False:
        penalty += 0.3
        driver = "provider health check failed"
    if not symbol_mapped:
        penalty += 0.4
        driver = "symbol mapping is not verified for this provider"

    if penalty <= 0.15:
        label = QualityLabel.HIGH
    elif penalty <= 0.45:
        label = QualityLabel.MEDIUM
    else:
        label = QualityLabel.LOW

    return QualityAssessment(
        label=label,
        status=status,
        age_ms=None if seconds is None else int(max(0.0, seconds) * 1000),
        completeness=gap_report.completeness if gap_report else None,
        driver=driver,
        components=components,
    )


# ---------------------------------------------------------------------------
# value-origin audit (spec §99)
# ---------------------------------------------------------------------------
#: Declared origins for the values this module produces. Kept as a table so the
#: classification is reviewable in one place rather than inferred per field.
VALUE_ORIGIN_TABLE: Dict[str, ValueOrigin] = {
    "price": ValueOrigin.SOURCE,
    "bid": ValueOrigin.SOURCE,
    "ask": ValueOrigin.SOURCE,
    "volume": ValueOrigin.SOURCE,
    "market_cap": ValueOrigin.SOURCE,
    "candle": ValueOrigin.SOURCE,
    "sma": ValueOrigin.CALCULATED,
    "ema": ValueOrigin.CALCULATED,
    "rsi": ValueOrigin.CALCULATED,
    "atr": ValueOrigin.CALCULATED,
    "realized_volatility": ValueOrigin.CALCULATED,
    "volatility_regime": ValueOrigin.DERIVED,
    "trend_direction": ValueOrigin.DERIVED,
    "trend_strength": ValueOrigin.DERIVED,
    "data_quality": ValueOrigin.DERIVED,
    "forecast": ValueOrigin.MODELLED,
    "prediction_interval": ValueOrigin.MODELLED,
    "modelled_probability": ValueOrigin.MODELLED,
    "calibration": ValueOrigin.MODELLED,
    "target_status": ValueOrigin.CALCULATED,
    "target_touch_count": ValueOrigin.CALCULATED,
}


def origin_of(key: str) -> ValueOrigin:
    """Look up the declared origin of a value; unknown keys are UNAVAILABLE."""
    return VALUE_ORIGIN_TABLE.get(key, ValueOrigin.UNAVAILABLE)


def annotate(origin: ValueOrigin, value: Any) -> Dict[str, Any]:
    """Wrap a value with its declared origin for an API payload."""
    return {"value": value, "origin": origin.value}


def quality_from_completeness(completeness: Optional[float], *, has_forecast: bool) -> QualityLabel:
    """Small helper for the forecast layer, which has no timestamp of its own."""
    if not has_forecast:
        return QualityLabel.UNAVAILABLE
    if completeness is None:
        return QualityLabel.MEDIUM
    if completeness >= 0.98:
        return QualityLabel.HIGH
    if completeness >= 0.9:
        return QualityLabel.MEDIUM
    return QualityLabel.LOW
