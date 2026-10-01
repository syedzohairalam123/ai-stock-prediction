"""
Market + analytics service (spec §54–§56, §62, §65–§68, §73).

Owns the flow from a provider response to a display-ready, quality-labelled
payload:

    provider candles → normalize (already done) → gap audit → indicators →
    volatility → micro-trend → optional display downsampling

Range control (spec §65) is enforced here rather than in the route: the caller
may ask for any limit, and the server clamps it to the configured cap. Chart
payloads may be downsampled, but the *raw* candles are always available and the
downsample preserves extrema (spec §66).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.crypto import quality as quality_mod
from app.crypto.config import crypto_settings
from app.crypto.indicators import indicator_bundle, log_returns, pct_change
from app.crypto.normalization import detect_gaps, downsample_for_display
from app.crypto.providers.base import CandleSeries, ProviderError, ProviderQuote
from app.crypto.schemas import (
    Candle,
    DataStatus,
    MicroTrendResult,
    QualityLabel,
    ValueOrigin,
    VolatilitySnapshot,
)
from app.crypto.timeframes import TimeframeConfig, get_timeframe, list_timeframes
from app.crypto.trend import micro_trend_engine, summarize_multi_timeframe
from app.crypto.volatility import volatility_engine

logger = logging.getLogger("neural_market.crypto.services.market")

#: Bars used for each row of the multi-timeframe comparison (spec §73).
MULTI_TIMEFRAME_BARS = 300


@dataclass
class SeriesBundle:
    """A candle series plus everything the UI needs to trust it."""

    series: CandleSeries
    timeframe: TimeframeConfig
    gaps: Any
    quality: quality_mod.QualityAssessment
    data_status: DataStatus

    @property
    def candles(self) -> List[Candle]:
        return self.series.candles


class MarketService:
    """Reads real market data and turns it into labelled analytics."""

    def __init__(self, manager) -> None:
        self.manager = manager

    # -------------------------------------------------------------------- quote
    async def quote(self, symbol: str) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        try:
            quote: ProviderQuote = await self.manager.get_quote(asset.internal)
        except ProviderError as exc:
            return {
                "symbol": asset.internal,
                "status": DataStatus.UNAVAILABLE.value,
                "reason": exc.message,
                "origin": ValueOrigin.UNAVAILABLE.value,
            }

        status = quality_mod.freshness_status(quote.source_timestamp)
        age_ms = _age_ms(quote.source_timestamp)
        return {
            **quote.to_dict(),
            "status": status.value,
            "age_ms": age_ms,
            "currency": "USD",
            "origin": ValueOrigin.SOURCE.value,
            "origin_by_field": {
                "price": ValueOrigin.SOURCE.value,
                "bid": ValueOrigin.SOURCE.value,
                "ask": ValueOrigin.SOURCE.value,
                "volume_24h": ValueOrigin.SOURCE.value,
                "change_percent_24h": ValueOrigin.SOURCE.value,
            },
        }

    # ------------------------------------------------------------------ candles
    async def candles(
        self,
        symbol: str,
        timeframe_id: Optional[str],
        *,
        limit: Optional[int] = None,
        display_points: Optional[int] = None,
        raw: bool = False,
    ) -> Dict[str, Any]:
        bundle = await self.load_series(symbol, timeframe_id, limit=limit)
        candles = bundle.candles
        payload_candles = candles
        downsampled = False
        if not raw and display_points:
            payload_candles = downsample_for_display(candles, display_points)
            downsampled = len(payload_candles) < len(candles)
        elif not raw and len(candles) > crypto_settings.display_target_points:
            payload_candles = downsample_for_display(candles, crypto_settings.display_target_points)
            downsampled = len(payload_candles) < len(candles)

        return {
            "symbol": bundle.series.symbol,
            "timeframe": bundle.timeframe.id,
            "timeframe_label": bundle.timeframe.label,
            "interval": bundle.series.interval,
            "aggregated": bundle.series.aggregated,
            "source": bundle.series.source,
            "data_status": bundle.data_status.value,
            "quality": bundle.quality.to_dict(),
            "gaps": bundle.gaps.to_dict(),
            "requested_limit": limit,
            "returned": len(payload_candles),
            "raw_count": len(candles),
            "downsampled": downsampled,
            "downsample_note": (
                "Display payload downsampled with extrema preserved; pass raw=true for every candle."
                if downsampled
                else None
            ),
            "notes": list(bundle.series.notes),
            "candles": [c.to_dict() for c in payload_candles],
            "origin": ValueOrigin.SOURCE.value,
        }

    # ----------------------------------------------------------------- analytics
    async def analytics(
        self,
        symbol: str,
        timeframe_id: Optional[str],
        *,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        bundle = await self.load_series(symbol, timeframe_id, limit=limit)
        volatility, trend = self._compute(bundle)
        indicators = self._indicators(bundle)
        closes = [c.close for c in bundle.candles]
        return {
            "symbol": bundle.series.symbol,
            "timeframe": bundle.timeframe.id,
            "timeframe_label": bundle.timeframe.label,
            "source": bundle.series.source,
            "data_status": bundle.data_status.value,
            "quality": bundle.quality.to_dict(),
            "gaps": bundle.gaps.to_dict(),
            "sample_size": len(bundle.candles),
            "last_close": closes[-1] if closes else None,
            "returns": {
                "last_bar_simple": _last_simple_return(closes),
                "over_window": pct_change(closes, min(len(closes) - 1, 20)) if len(closes) > 1 else None,
                "origin": ValueOrigin.CALCULATED.value,
            },
            "indicators": indicators,
            "volatility": volatility.to_dict(),
            "trend": trend.to_dict(),
            "value_origins": {
                "price": ValueOrigin.SOURCE.value,
                "indicators": ValueOrigin.CALCULATED.value,
                "volatility": ValueOrigin.CALCULATED.value,
                "trend": ValueOrigin.DERIVED.value,
                "quality": ValueOrigin.DERIVED.value,
            },
            "note": (
                "OBSERVED DATA is the provider price series. MODEL INTERPRETATION begins at the "
                "trend and volatility labels, which are derived from that series."
            ),
        }

    async def multi_timeframe(self, symbol: str) -> Dict[str, Any]:
        """
        One row per timeframe (spec §17, §18, §73).

        Each row is computed from its own real dataset — incompatible resolutions
        are never merged into a blended number, and conflicting directions are
        reported as such rather than collapsed.
        """
        rows: List[Dict[str, Any]] = []
        for timeframe in list_timeframes():
            timeframe_id = timeframe["id"]
            try:
                bundle = await self.load_series(
                    symbol, timeframe_id, limit=min(MULTI_TIMEFRAME_BARS, timeframe["max_history_candles"])
                )
            except Exception as exc:  # a single timeframe failing must not break the view
                logger.warning("multi-timeframe row %s failed: %s", timeframe_id, exc)
                rows.append(
                    {
                        "timeframe": timeframe_id,
                        "label": timeframe["label"],
                        "trend": "UNAVAILABLE",
                        "data_status": DataStatus.UNAVAILABLE.value,
                        "quality": QualityLabel.UNAVAILABLE.value,
                        "error": type(exc).__name__,
                    }
                )
                continue

            if not bundle.candles:
                rows.append(
                    {
                        "timeframe": timeframe_id,
                        "label": timeframe["label"],
                        "trend": "UNAVAILABLE",
                        "return": None,
                        "volatility": None,
                        "volume_change": None,
                        "data_status": DataStatus.UNAVAILABLE.value,
                        "quality": QualityLabel.UNAVAILABLE.value,
                    }
                )
                continue

            volatility, trend = self._compute(bundle)
            closes = [c.close for c in bundle.candles]
            volumes = [c.volume for c in bundle.candles]
            rows.append(
                {
                    "timeframe": timeframe_id,
                    "label": timeframe["label"],
                    "trend": trend.direction.value,
                    "trend_strength": trend.strength,
                    "return": trend.recent_return,
                    "return_over_20": pct_change(closes, min(len(closes) - 1, 20)) if len(closes) > 1 else None,
                    "volatility": volatility.realized_volatility,
                    "volatility_regime": volatility.regime.value,
                    "atr_percent": volatility.atr_percent,
                    "volume_change": pct_change(volumes, 1) if len(volumes) > 1 else None,
                    "data_status": bundle.data_status.value,
                    "quality": bundle.quality.label.value,
                    "source": bundle.series.source,
                    "sample_size": len(bundle.candles),
                }
            )

        return {
            "symbol": symbol.upper(),
            "rows": rows,
            "summary": summarize_multi_timeframe(rows),
            "note": (
                "Each row is computed from its own real dataset. Short-term and broader timeframes "
                "can legitimately disagree and are reported separately."
            ),
            "origin": ValueOrigin.DERIVED.value,
        }

    # ------------------------------------------------------------------- helpers
    async def load_series(
        self, symbol: str, timeframe_id: Optional[str], *, limit: Optional[int] = None
    ) -> SeriesBundle:
        asset = self.manager.resolve(symbol)
        timeframe = get_timeframe(timeframe_id)
        series = await self.manager.get_candles(asset.internal, timeframe.id, limit=limit)
        gaps = detect_gaps(
            series.candles, interval_seconds=timeframe.duration_seconds, timeframe=timeframe.id
        )
        health = self.manager.health_snapshot()
        provider_healthy = next(
            (entry.get("available") for entry in health if entry.get("provider") == series.source),
            None,
        )
        assessment = quality_mod.assess(
            source_timestamp=series.source_timestamp,
            gap_report=gaps,
            provider_healthy=provider_healthy if isinstance(provider_healthy, bool) else None,
            symbol_mapped=bool(asset.binance or asset.coingecko_id),
            candle_count=len(series.candles),
            bar_seconds=timeframe.duration_seconds,
        )
        data_status = (
            DataStatus.UNAVAILABLE
            if not series.candles
            else assessment.status
        )
        return SeriesBundle(
            series=series, timeframe=timeframe, gaps=gaps, quality=assessment, data_status=data_status
        )

    def _compute(self, bundle: SeriesBundle) -> tuple[VolatilitySnapshot, MicroTrendResult]:
        candles = bundle.candles
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]

        volatility = volatility_engine.snapshot(
            highs=highs,
            lows=lows,
            closes=closes,
            duration_seconds=bundle.timeframe.duration_seconds,
            timeframe=bundle.timeframe.id,
            data_status=bundle.data_status,
        )
        trend = micro_trend_engine.analyse(
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            timeframe=bundle.timeframe.id,
            duration_seconds=bundle.timeframe.duration_seconds,
            volatility_regime=volatility.regime,
            realized_volatility=volatility.realized_volatility,
            data_status=bundle.data_status,
        )
        return volatility, trend

    def _indicators(self, bundle: SeriesBundle) -> Dict[str, Any]:
        candles = bundle.candles
        if not candles:
            return {"available": False}
        bundle_values = indicator_bundle(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=[c.close for c in candles],
            volumes=[c.volume for c in candles],
            rsi_period=crypto_settings.rsi_period,
            atr_period=crypto_settings.atr_period,
            ema_fast=crypto_settings.ema_fast,
            ema_slow=crypto_settings.ema_slow,
            momentum_lookback=crypto_settings.momentum_lookback,
        )
        return {"available": True, "origin": ValueOrigin.CALCULATED.value, **bundle_values}


def _age_ms(timestamp: Optional[datetime]) -> Optional[int]:
    seconds = quality_mod.age_seconds(timestamp)
    return None if seconds is None else int(max(0.0, seconds) * 1000)


def _last_simple_return(closes: Sequence[float]) -> Optional[float]:
    return pct_change(list(closes), 1) if len(closes) > 1 else None
