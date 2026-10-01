"""
Forecast service (spec §20–§31, §69, §77, §81, §83).

Wraps :class:`~app.crypto.forecasting.engine.ForecastEngine` with:

  * **caching** — a forecast is expensive relative to a quote, so the result is
    cached for ``CRYPTO_FORECAST_CACHE_TTL_SECONDS`` keyed by
    (symbol, timeframe, horizon);
  * **persistence** — every generated forecast is stored versioned and
    append-only, so it can later be scored against what actually happened;
  * **self-evaluation** — :meth:`evaluate_pending` scores stored forecasts whose
    horizon has elapsed, using the real candle that closed at that timestamp;
  * **drift** — compares the earlier training window against the newest window of
    the same real feature matrix and reports ``MODEL PERFORMANCE DEGRADED`` when
    the distribution has genuinely moved (spec §77, §78).

A forecast that cannot be produced honestly is reported as ``UNAVAILABLE`` with
its reason; the service never substitutes a placeholder number.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.crypto import quality as quality_mod
from app.crypto import repositories as repo
from app.crypto.config import crypto_settings
from app.crypto.forecasting.engine import evaluate_forecast, forecast_engine
from app.crypto.forecasting.drift import drift_monitor
from app.crypto.schemas import DataStatus, QualityLabel, ValueOrigin

logger = logging.getLogger("neural_market.crypto.services.forecast")

_FORECAST_CACHE_PREFIX = "crypto:forecast:"


class ForecastService:
    """Generation, caching, persistence and retrospective scoring of forecasts."""

    def __init__(self, manager, market_service) -> None:
        self.manager = manager
        self.market = market_service

    # ------------------------------------------------------------------ generate
    async def get(
        self,
        symbol: str,
        timeframe_id: Optional[str],
        *,
        horizon: Optional[int] = None,
        persist: bool = False,
    ) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        from app.crypto.timeframes import get_timeframe

        resolved_timeframe = get_timeframe(timeframe_id)
        resolved_horizon = horizon or crypto_settings.default_horizon

        cache_key = f"{_FORECAST_CACHE_PREFIX}{asset.internal}:{resolved_timeframe.id}:{resolved_horizon}"
        cached = await self.manager.cache.get(cache_key)
        if cached is not None:
            return cached

        bundle = await self.market.load_series(asset.internal, resolved_timeframe.id)
        if not bundle.candles:
            return {
                "symbol": asset.internal,
                "timeframe": resolved_timeframe.id,
                "horizon": resolved_horizon,
                "status": DataStatus.UNAVAILABLE.value,
                "forecast": None,
                "reason": "no real candle history available from the configured providers",
                "label": "MODELLED FORECAST",
                "origin": ValueOrigin.UNAVAILABLE.value,
            }

        quality = quality_mod.quality_from_completeness(
            bundle.gaps.completeness, has_forecast=True
        )
        outcome = forecast_engine.forecast(
            symbol=asset.internal,
            timeframe=resolved_timeframe.id,
            candles=bundle.candles,
            duration_seconds=resolved_timeframe.duration_seconds,
            data_source=bundle.series.source,
            quality=quality,
            horizon=resolved_horizon,
        )

        payload = self._payload(
            asset=asset.internal,
            timeframe=resolved_timeframe.id,
            horizon=resolved_horizon,
            bundle=bundle,
            outcome=outcome,
            quality=quality,
        )
        if outcome.available:
            await self.manager.cache.set(
                cache_key, payload, ttl_seconds=crypto_settings.forecast_cache_ttl_seconds
            )
            if persist:
                await self._persist(payload)
        return payload

    # ------------------------------------------------------------------- history
    def history(self, symbol: str, timeframe: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        rows = repo.forecast_history(symbol=asset.internal, timeframe=timeframe, limit=limit)
        return {
            "symbol": asset.internal,
            "count": len(rows),
            "forecasts": rows,
            "note": "Append-only: failed forecasts are retained for retrospective evaluation.",
            "origin": ValueOrigin.MODELLED.value,
        }

    def performance(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        internal = self.manager.resolve(symbol).internal if symbol else None
        snapshot = repo.forecast_performance(symbol=internal)
        return {**snapshot, "origin": ValueOrigin.MODELLED.value}

    # --------------------------------------------------------------------- drift
    async def drift(self, symbol: str, timeframe_id: Optional[str] = None) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        from app.crypto.timeframes import get_timeframe

        timeframe = get_timeframe(timeframe_id)
        bundle = await self.market.load_series(asset.internal, timeframe.id)
        if not bundle.candles:
            return {
                "symbol": asset.internal,
                "timeframe": timeframe.id,
                "status": "UNKNOWN",
                "reason": "no candle history to compare",
            }
        outcome = forecast_engine.forecast(
            symbol=asset.internal,
            timeframe=timeframe.id,
            candles=bundle.candles,
            duration_seconds=timeframe.duration_seconds,
            data_source=bundle.series.source,
        )
        if not outcome.reference_features:
            return {
                "symbol": asset.internal,
                "timeframe": timeframe.id,
                "status": "UNKNOWN",
                "reason": outcome.reason or "not enough rows to build a reference distribution",
            }
        report = drift_monitor.compare(
            reference=outcome.reference_features,
            recent=outcome.recent_features,
            training_time=(
                outcome.forecast.training_end_time if outcome.forecast else None
            ),
        )
        return {
            "symbol": asset.internal,
            "timeframe": timeframe.id,
            "reference_window": "earliest 70% of the labelled feature rows",
            "recent_window": "newest 30% of the labelled feature rows",
            "origin": ValueOrigin.MODELLED.value,
            **report.to_dict(),
        }

    # --------------------------------------------------------------- evaluation
    async def evaluate_pending(self, *, limit: int = 25) -> Dict[str, Any]:
        """
        Score stored forecasts whose horizon has elapsed (spec §30, §80).

        The realised price is read from the *stored* candle that closed at the
        forecast's target timestamp. If no such candle exists, the forecast stays
        pending rather than being scored against a guess.
        """
        pending = repo.pending_forecasts(limit=limit)
        if not pending:
            return {"evaluated": 0, "pending": 0, "note": "no forecasts have completed their horizon yet"}

        scored = 0
        skipped: List[str] = []
        for row in pending:
            target_timestamp = row.get("target_timestamp")
            if not target_timestamp:
                continue
            try:
                target_dt = datetime.fromisoformat(str(target_timestamp))
            except ValueError:
                continue
            candles = repo.candle_range(
                symbol=row["symbol"], timeframe=row["timeframe"], limit=crypto_settings.max_history_candles
            )
            actual = _closest_candle(candles, target_dt)
            if actual is None:
                skipped.append(row["id"])
                continue
            from app.crypto.schemas import CryptoForecast, ForecastMetrics

            forecast = CryptoForecast(
                id=row["id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                horizon=row["horizon"],
                generated_at=datetime.fromisoformat(str(row["generated_at"])),
                prediction=row["prediction"],
                last_close=row["last_close"],
                lower_bound=row.get("lower_bound"),
                upper_bound=row.get("upper_bound"),
                model_name=row["model_name"],
                model_version=row["model_version"],
                feature_version=row["feature_version"],
                training_window=row.get("training_window") or 0,
                training_end_time=(
                    datetime.fromisoformat(str(row["training_end_time"]))
                    if row.get("training_end_time")
                    else None
                ),
                metrics=ForecastMetrics(**(row.get("metrics") or {})),
                baseline_metrics=ForecastMetrics(**(row.get("baseline_metrics") or {})),
                beats_baseline=bool(row.get("beats_baseline")),
                data_source=row["data_source"],
                data_quality=QualityLabel(row.get("data_quality") or "UNAVAILABLE"),
            )
            evaluation = evaluate_forecast(
                forecast=forecast, actual_price=actual["close"], actual_timestamp=target_dt
            )
            repo.insert_forecast_evaluation(evaluation)
            scored += 1
        return {
            "evaluated": scored,
            "pending": len(pending) - scored,
            "skipped_no_candle": len(skipped),
            "note": "Realised prices read from stored candles at the forecast target timestamp.",
        }

    # ------------------------------------------------------------------ internal
    async def _persist(self, payload: Dict[str, Any]) -> None:
        forecast = payload.get("forecast")
        if not forecast:
            return
        from app.crypto.timeframes import get_timeframe

        timeframe = get_timeframe(payload["timeframe"])
        target_timestamp = payload.get("target_timestamp")
        try:
            repo.insert_forecast(
                {
                    "id": forecast["id"],
                    "symbol": forecast["symbol"],
                    "timeframe": forecast["timeframe"],
                    "horizon": forecast["horizon"],
                    "forecast_generated_at": datetime.fromisoformat(forecast["generated_at"]),
                    "target_timestamp": (
                        datetime.fromisoformat(target_timestamp) if target_timestamp else None
                    ),
                    "last_close": forecast["last_close"],
                    "prediction": forecast["prediction"],
                    "lower_bound": forecast.get("lower_bound"),
                    "upper_bound": forecast.get("upper_bound"),
                    "model_name": forecast["model_name"],
                    "model_version": forecast["model_version"],
                    "feature_version": forecast["feature_version"],
                    "training_window": forecast.get("training_window"),
                    "training_end_time": (
                        datetime.fromisoformat(forecast["training_end_time"])
                        if forecast.get("training_end_time")
                        else None
                    ),
                    "metrics": forecast.get("metrics") or {},
                    "baseline_metrics": forecast.get("baseline_metrics") or {},
                    "beats_baseline": forecast.get("beats_baseline"),
                    "data_source": forecast.get("data_source"),
                    "data_quality": forecast.get("data_quality"),
                    "limitations": forecast.get("limitations") or [],
                }
            )
        except Exception as exc:  # persistence must never break the response
            logger.warning("failed to persist forecast %s: %s", forecast.get("id"), exc)

    def _payload(
        self,
        *,
        asset: str,
        timeframe: str,
        horizon: int,
        bundle,
        outcome,
        quality: QualityLabel,
    ) -> Dict[str, Any]:
        selected = outcome.forecast
        target_timestamp = None
        if selected is not None and bundle.candles:
            import datetime as dt

            target_timestamp = (
                bundle.candles[-1].timestamp + dt.timedelta(seconds=bundle.timeframe.duration_seconds * horizon)
            ).isoformat()

        drift = None
        if outcome.reference_features:
            report = drift_monitor.compare(
                reference=outcome.reference_features, recent=outcome.recent_features
            )
            drift = report.to_dict()

        return {
            "symbol": asset,
            "timeframe": timeframe,
            "timeframe_label": bundle.timeframe.label,
            "horizon": horizon,
            "horizon_seconds": bundle.timeframe.duration_seconds * horizon,
            "target_timestamp": target_timestamp,
            "status": DataStatus.LIVE.value if outcome.available else DataStatus.UNAVAILABLE.value,
            "quality": quality.value,
            "data_quality_detail": bundle.quality.to_dict(),
            "source": bundle.series.source,
            "candles_used": len(bundle.candles),
            "forecast": selected.to_dict() if selected else None,
            "reason": outcome.reason,
            "label": "MODELLED FORECAST",
            "origin": ValueOrigin.MODELLED.value,
            "validation": [result.to_dict() for result in outcome.validation],
            "baselines": sorted(
                {r.name for r in outcome.validation if r.kind == "baseline"}
            ),
            "anomaly": outcome.anomaly.to_dict() if outcome.anomaly else None,
            "drift": drift,
            "limitations": outcome.limitations,
            "diagnostics": outcome.diagnostics,
            "residual_std": outcome.residual_std,
            "note": (
                "MODELLED FORECAST — an analytical estimate with a measured error profile, not a "
                "guaranteed outcome. See `limitations` and `validation`."
            ),
        }


def _closest_candle(candles: List[Dict[str, Any]], target: datetime) -> Optional[Dict[str, Any]]:
    """Stored candle nearest the target timestamp, within half a bar; else None."""
    if not candles:
        return None
    reference = target if target.tzinfo else target.replace(tzinfo=timezone.utc)
    best: Optional[Dict[str, Any]] = None
    best_delta: Optional[float] = None
    for candle in candles:
        try:
            stamp = datetime.fromisoformat(str(candle["timestamp"]))
        except (ValueError, TypeError, KeyError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        delta = abs((stamp - reference).total_seconds())
        if best_delta is None or delta < best_delta:
            best, best_delta = candle, delta
    # Accept only a genuinely nearby observation (a real closed bar).
    if best is None or best_delta is None or best_delta > 3 * 86400:
        return None
    return best
