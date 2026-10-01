"""
Micro-trend engine (spec §11, §16, §18, §19).

A **descriptive** short-term trend read, deliberately not a prediction. It
aggregates several independent, real factors — recent returns, candle direction,
EMA/SMA slope, momentum, volume change, realised volatility and position inside
the recent range — into a direction, a strength and a confidence.

Two honesty properties are enforced here rather than left to the UI:

  * ``INSUFFICIENT_DATA`` is a first-class direction. Below the configured
    minimum sample the engine refuses to answer instead of extrapolating from
    two candles.
  * Confidence is a blend of *sample size* and *factor agreement*, and it is
    capped. It is never an implied probability of the future — spec §27 forbids
    manufacturing certainty.

Timeframe consistency (spec §18) is handled by :func:`summarize_multi_timeframe`,
which reports "short-term UP, broader DOWN" rather than collapsing conflicting
horizons into one number.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from app.crypto.config import crypto_settings
from app.crypto.indicators import indicator_bundle, log_returns
from app.crypto.schemas import (
    DataStatus,
    MicroTrendResult,
    TrendDirection,
    VolatilityRegime,
)

#: Minimum bars before any direction is emitted.
MIN_TREND_SAMPLES = 12

#: Relative-return band (as a fraction of realised volatility) inside which the
#: move is treated as noise rather than direction.
_SIDEWAYS_BAND = 0.15

#: Confidence is capped here: a descriptive blend must never read as certainty.
MAX_CONFIDENCE = 0.9


class MicroTrendEngine:
    """Deterministic, per-timeframe trend descriptor over real candles."""

    def analyse(
        self,
        *,
        highs: Sequence[float],
        lows: Sequence[float],
        closes: Sequence[float],
        volumes: Sequence[float],
        timeframe: str,
        duration_seconds: int,
        volatility_regime: Optional[VolatilityRegime] = None,
        realized_volatility: Optional[float] = None,
        data_status: DataStatus = DataStatus.UNAVAILABLE,
        generated_at: Optional[datetime] = None,
    ) -> MicroTrendResult:
        sample_size = len(closes)
        if sample_size < MIN_TREND_SAMPLES:
            return MicroTrendResult(
                direction=TrendDirection.INSUFFICIENT_DATA,
                strength=0.0,
                confidence=0.0,
                timeframe=timeframe,
                volatility_regime=volatility_regime,
                factors={"reason": f"need >= {MIN_TREND_SAMPLES} candles", "sample_size": sample_size},
                sample_size=sample_size,
                data_status=DataStatus.UNAVAILABLE if sample_size == 0 else data_status,
                generated_at=generated_at or datetime.now(timezone.utc),
            )

        indicators = indicator_bundle(
            highs=list(highs),
            lows=list(lows),
            closes=list(closes),
            volumes=list(volumes),
            rsi_period=crypto_settings.rsi_period,
            atr_period=crypto_settings.atr_period,
            ema_fast=crypto_settings.ema_fast,
            ema_slow=crypto_settings.ema_slow,
            momentum_lookback=crypto_settings.momentum_lookback,
        )

        recent_return = _recent_return(list(closes), crypto_settings.momentum_lookback)
        factors = self._factors(
            indicators=indicators,
            closes=list(closes),
            recent_return=recent_return,
            realized_volatility=realized_volatility,
        )
        score = _weighted_score(factors)
        scale = _normalisation_scale(realized_volatility, recent_return)

        if scale is None or abs(score) < _SIDEWAYS_BAND:
            direction = TrendDirection.SIDEWAYS
        elif score > 0:
            direction = TrendDirection.UP
        else:
            direction = TrendDirection.DOWN

        strength = min(1.0, abs(score))
        confidence = _confidence(factors=factors, sample_size=sample_size, strength=strength)

        return MicroTrendResult(
            direction=direction,
            strength=round(strength, 6),
            confidence=round(confidence, 6),
            timeframe=timeframe,
            recent_return=recent_return,
            volatility_regime=volatility_regime,
            factors=factors,
            sample_size=sample_size,
            data_status=data_status,
            generated_at=generated_at or datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------ internal
    def _factors(
        self,
        *,
        indicators: Dict[str, Optional[float]],
        closes: List[float],
        recent_return: Optional[float],
        realized_volatility: Optional[float],
    ) -> Dict[str, object]:
        """Signed, comparable factor contributions in roughly [-1, 1]."""
        fast = indicators.get("ema_fast")
        slow = indicators.get("ema_slow")
        ema_slope = indicators.get("ema_fast_slope")
        sma_slope_value = indicators.get("sma_slope")
        momentum = indicators.get("momentum")
        volume_change = indicators.get("volume_change")
        range_position = indicators.get("range_position")
        range_expansion = indicators.get("range_expansion")
        rsi_value = indicators.get("rsi")

        last_close = closes[-1]
        trend_factor = _sign_scaled(
            (fast - slow) / last_close if (fast is not None and slow is not None and last_close) else None
        )
        slope_factor = _sign_scaled(
            (ema_slope / last_close) if (ema_slope is not None and last_close) else None
        )
        sma_factor = _sign_scaled(
            (sma_slope_value / last_close) if (sma_slope_value is not None and last_close) else None
        )
        # Momentum is normalised by the same-window volatility so a quiet market
        # and a wild one are comparable.
        momentum_factor = _sign_scaled(
            (momentum / realized_volatility) if (momentum is not None and realized_volatility) else None
        )
        position_factor = None
        if range_position is not None:
            position_factor = max(-1.0, min(1.0, (range_position - 0.5) * 2.0))
        # RSI contributes only at the edges (it is a bounded oscillator).
        rsi_factor = None
        if rsi_value is not None:
            rsi_factor = max(-1.0, min(1.0, (rsi_value - 50.0) / 50.0)) * 0.5
        # Volume direction follows price direction; it amplifies, never leads.
        volume_factor = _sign_scaled(volume_change) if volume_change is not None else None

        return {
            "recent_return": recent_return,
            "ema_spread": trend_factor,
            "ema_slope": slope_factor,
            "sma_slope": sma_factor,
            "momentum": momentum_factor,
            "range_position": position_factor,
            "rsi": rsi_factor,
            "volume_change": volume_factor,
            "range_expansion": range_expansion,
            "rsi_value": rsi_value,
            "raw": {
                "ema_fast": fast,
                "ema_slow": slow,
                "atr": indicators.get("atr"),
                "atr_percent": indicators.get("atr_percent"),
            },
        }


def _recent_return(closes: Sequence[float], lookback: int) -> Optional[float]:
    if len(closes) <= lookback or lookback <= 0:
        return None
    previous = closes[-1 - lookback]
    if previous <= 0:
        return None
    return closes[-1] / previous - 1.0


def _sign_scaled(value: Optional[float]) -> Optional[float]:
    """Clamp a signed factor into [-1, 1] without changing its sign."""
    if value is None:
        return None
    return max(-1.0, min(1.0, float(value) * 10.0))


_FACTOR_WEIGHTS: Dict[str, float] = {
    "ema_spread": 0.22,
    "ema_slope": 0.22,
    "sma_slope": 0.14,
    "momentum": 0.22,
    "range_position": 0.10,
    "rsi": 0.06,
    "volume_change": 0.04,
}


def _weighted_score(factors: Dict[str, object]) -> float:
    """Weighted mean over the factors that were actually computable."""
    total_weight = 0.0
    weighted = 0.0
    for name, weight in _FACTOR_WEIGHTS.items():
        value = factors.get(name)
        if not isinstance(value, (int, float)):
            continue
        weighted += float(value) * weight
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return weighted / total_weight


def _normalisation_scale(
    realized_volatility: Optional[float], recent_return: Optional[float]
) -> Optional[float]:
    """
    A positive scale for deciding "is this move real?".

    Prefers the asset's own realised volatility; falls back to the magnitude of
    the observed return. ``None`` means neither was available, in which case the
    engine must not classify direction.
    """
    if realized_volatility is not None and realized_volatility > 0:
        return realized_volatility
    if recent_return is not None and abs(recent_return) > 0:
        return abs(recent_return)
    return None


def _confidence(*, factors: Dict[str, object], sample_size: int, strength: float) -> float:
    """
    Blend of sample adequacy and factor agreement, capped at :data:`MAX_CONFIDENCE`.

    ``agreement`` is the share of signed factors pointing the same way as the
    blended score — a real, checkable property of this observation, not a
    probability about the future.
    """
    signed = [
        float(factors[name])
        for name in _FACTOR_WEIGHTS
        if isinstance(factors.get(name), (int, float))
    ]
    if not signed:
        return 0.0
    direction = 1.0 if sum(signed) >= 0 else -1.0
    agreement = sum(1 for value in signed if value * direction > 0) / len(signed)
    sample_factor = min(1.0, sample_size / (MIN_TREND_SAMPLES * 4.0))
    confidence = 0.35 * sample_factor + 0.45 * agreement + 0.20 * strength
    return min(MAX_CONFIDENCE, max(0.0, confidence))


# ---------------------------------------------------------------------------
# multi-timeframe
# ---------------------------------------------------------------------------
def summarize_multi_timeframe(rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    """
    Compose per-timeframe trend results into an honest, non-collapsed summary.

    Spec §18: if 5m is UP and 1h is DOWN we say exactly that. A single
    ``aligned`` boolean is provided because "all horizons agree" is itself a real
    observation — but the short/broader split is never discarded in favour of it.
    """
    if not rows:
        return {
            "short_term": None,
            "broader": None,
            "aligned": None,
            "directions": {},
            "note": "No timeframe data available.",
        }

    short_ids = {"5m", "15m"}
    broader_ids = {"1d", "1w", "1M", "1Y"}

    short_dirs = [r.get("trend") for r in rows if r.get("timeframe") in short_ids]
    broader_dirs = [r.get("trend") for r in rows if r.get("timeframe") in broader_ids]

    def _consensus(values: List[object]) -> Optional[str]:
        real = [str(v) for v in values if v and str(v) != TrendDirection.INSUFFICIENT_DATA.value]
        if not real:
            return None
        unique = set(real)
        if len(unique) == 1:
            return real[0]
        return "MIXED"

    directions = {str(r.get("timeframe")): r.get("trend") for r in rows}
    real_directions = {
        v for v in directions.values() if v and v != TrendDirection.INSUFFICIENT_DATA.value
    }
    return {
        "short_term": _consensus(short_dirs),
        "broader": _consensus(broader_dirs),
        "aligned": len(real_directions) == 1 if real_directions else None,
        "directions": directions,
        "note": (
            "Timeframes can legitimately disagree; short-term and broader reads are "
            "reported separately rather than collapsed into one conclusion."
        ),
    }


#: Process-wide singleton (stateless).
micro_trend_engine = MicroTrendEngine()
