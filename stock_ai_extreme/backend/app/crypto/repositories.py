"""
Persistence repository for the crypto module (spec §63, §64).

Thin, explicit functions over the project's existing :func:`app.db.session_scope`.
No business logic lives here — the repository only stores what a provider really
published or what an engine really computed, and reads it back.

Every write is defensive: a persistence failure is logged and swallowed by the
*caller* where appropriate, so a full disk or a locked SQLite file can never take
down a live market-data request.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import delete, desc, func, select

from app.crypto.config import crypto_settings
from app.crypto.database.models import (
    CryptoAsset,
    CryptoCandle,
    CryptoCategory,
    CryptoDataSource,
    CryptoForecast,
    CryptoForecastEvaluation,
    CryptoProviderHealth,
    CryptoQuote,
    CryptoTarget,
    CryptoTargetEvent,
)
from app.db import session_scope

logger = logging.getLogger("neural_market.crypto.repositories")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def coerce_datetime(value: Any) -> Optional[datetime]:
    """Accept a datetime or an ISO-8601 string (schemas serialize to ISO)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite stores naive datetimes; normalise a real timestamp to naive UTC."""
    parsed = coerce_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def to_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Read a stored timestamp back as an explicitly UTC-aware value."""
    parsed = coerce_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value: Optional[datetime]) -> Optional[str]:
    aware = to_aware_utc(value)
    return aware.isoformat() if aware else None


def _parse(value: Any) -> Optional[datetime]:
    """Local alias kept for readability in the row serializers."""
    return coerce_datetime(value)


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------
def upsert_assets(assets: Sequence[Dict[str, Any]]) -> int:
    written = 0
    with session_scope() as db:
        for asset in assets:
            row = db.get(CryptoAsset, asset["symbol"])
            if row is None:
                row = CryptoAsset(symbol=asset["symbol"], name=asset["name"])
                db.add(row)
            row.name = asset.get("name") or row.name
            row.display_symbol = asset.get("display")
            row.binance_symbol = asset.get("binance_symbol")
            row.coingecko_id = asset.get("coingecko_id")
            row.industry = asset.get("industry")
            row.streaming = bool(asset.get("streaming"))
            written += 1
    return written


def count_assets() -> int:
    with session_scope() as db:
        return int(db.scalar(select(func.count()).select_from(CryptoAsset)) or 0)


# ---------------------------------------------------------------------------
# quotes
# ---------------------------------------------------------------------------
def upsert_quote(quote: Dict[str, Any]) -> None:
    symbol = quote.get("symbol")
    provider = quote.get("source")
    if not symbol or not provider:
        return
    with session_scope() as db:
        row = db.scalar(
            select(CryptoQuote).where(CryptoQuote.symbol == symbol, CryptoQuote.provider == provider)
        )
        if row is None:
            row = CryptoQuote(symbol=symbol, provider=provider)
            db.add(row)
        row.price = quote.get("price")
        row.bid = quote.get("bid")
        row.ask = quote.get("ask")
        row.volume_24h = quote.get("volume_24h")
        row.change_percent_24h = quote.get("change_percent_24h")
        row.high_24h = quote.get("high_24h")
        row.low_24h = quote.get("low_24h")
        row.data_status = quote.get("status")
        row.timestamp = to_naive_utc(quote.get("source_timestamp")) or utcnow().replace(tzinfo=None)


def latest_quote(symbol: str) -> Optional[Dict[str, Any]]:
    with session_scope() as db:
        row = db.scalar(
            select(CryptoQuote).where(CryptoQuote.symbol == symbol).order_by(desc(CryptoQuote.timestamp))
        )
        if row is None:
            return None
        return {
            "symbol": row.symbol,
            "provider": row.provider,
            "price": row.price,
            "bid": row.bid,
            "ask": row.ask,
            "volume_24h": row.volume_24h,
            "change_percent_24h": row.change_percent_24h,
            "high_24h": row.high_24h,
            "low_24h": row.low_24h,
            "status": row.data_status,
            "timestamp": iso(row.timestamp),
        }


# ---------------------------------------------------------------------------
# candles
# ---------------------------------------------------------------------------
def upsert_candles(
    *,
    symbol: str,
    timeframe: str,
    provider: str,
    candles: Iterable[Any],
) -> int:
    """
    Insert or refresh real candles.

    The natural key is (symbol, timeframe, provider, timestamp), so re-fetching
    the same bar updates it in place — an idempotent write, not a duplicate.
    """
    written = 0
    with session_scope() as db:
        existing = {
            to_naive_utc(row.timestamp)
            for row in db.scalars(
                select(CryptoCandle).where(
                    CryptoCandle.symbol == symbol,
                    CryptoCandle.timeframe == timeframe,
                    CryptoCandle.provider == provider,
                )
            )
        }
        for candle in candles:
            stamp = to_naive_utc(candle.timestamp)
            if stamp is None:
                continue
            if stamp in existing:
                row = db.scalar(
                    select(CryptoCandle).where(
                        CryptoCandle.symbol == symbol,
                        CryptoCandle.timeframe == timeframe,
                        CryptoCandle.provider == provider,
                        CryptoCandle.timestamp == stamp,
                    )
                )
                if row is None:
                    continue
                row.open, row.high, row.low, row.close = candle.open, candle.high, candle.low, candle.close
                row.volume = candle.volume
            else:
                db.add(
                    CryptoCandle(
                        symbol=symbol,
                        timeframe=timeframe,
                        provider=provider,
                        timestamp=stamp,
                        open=candle.open,
                        high=candle.high,
                        low=candle.low,
                        close=candle.close,
                        volume=candle.volume,
                    )
                )
                existing.add(stamp)
            written += 1
    return written


def candle_range(
    *,
    symbol: str,
    timeframe: str,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Stored candles, newest last, for a bounded read (spec §65)."""
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(CryptoCandle)
                .where(CryptoCandle.symbol == symbol, CryptoCandle.timeframe == timeframe)
                .order_by(desc(CryptoCandle.timestamp))
                .limit(max(1, min(limit, crypto_settings.max_history_candles)))
            )
        )
        # Serialize inside the session: session_scope() commits on exit, which
        # expires ORM attributes and would raise DetachedInstanceError.
        return [
            {
                "timestamp": iso(row.timestamp),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "provider": row.provider,
            }
            for row in reversed(rows)
        ]


def candle_count() -> int:
    with session_scope() as db:
        return int(db.scalar(select(func.count()).select_from(CryptoCandle)) or 0)


def prune_candles(*, keep_seconds: int = 14 * 86400) -> int:
    """
    Retention: drop high-frequency history older than the configured window.

    Spec §64 says not to keep unlimited high-frequency data. The daily and
    coarser timeframes are retained, since their row count is negligible.
    """
    cutoff = utcnow().replace(tzinfo=None) - timedelta(seconds=keep_seconds)
    with session_scope() as db:
        result = db.execute(
            delete(CryptoCandle).where(
                CryptoCandle.timestamp < cutoff, CryptoCandle.timeframe.in_(["5m", "15m", "1h"])
            )
        )
        return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# forecasts
# ---------------------------------------------------------------------------
def insert_forecast(record: Dict[str, Any]) -> None:
    with session_scope() as db:
        db.add(
            CryptoForecast(
                id=record["id"],
                symbol=record["symbol"],
                timeframe=record["timeframe"],
                horizon=int(record["horizon"]),
                forecast_generated_at=to_naive_utc(record["forecast_generated_at"]),
                target_timestamp=to_naive_utc(record.get("target_timestamp")),
                last_close=float(record["last_close"]),
                prediction=float(record["prediction"]),
                lower_bound=record.get("lower_bound"),
                upper_bound=record.get("upper_bound"),
                model_name=record["model_name"],
                model_version=record["model_version"],
                feature_version=record["feature_version"],
                training_window=int(record.get("training_window") or 0),
                training_end_time=to_naive_utc(record.get("training_end_time")),
                metrics=record.get("metrics") or {},
                baseline_metrics=record.get("baseline_metrics") or {},
                beats_baseline=bool(record.get("beats_baseline")),
                data_source=record["data_source"],
                data_quality=record.get("data_quality"),
                limitations=record.get("limitations") or [],
                evaluated=False,
            )
        )


def forecast_history(*, symbol: str, timeframe: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Stored forecasts, newest first. Failed forecasts are never removed."""
    with session_scope() as db:
        query = select(CryptoForecast).where(CryptoForecast.symbol == symbol)
        if timeframe:
            query = query.where(CryptoForecast.timeframe == timeframe)
        rows = list(db.scalars(query.order_by(desc(CryptoForecast.forecast_generated_at)).limit(max(1, min(limit, 500)))))
        # Serialized inside the session to avoid DetachedInstanceError on commit.
        return [_forecast_row(row) for row in rows]


def _forecast_row(row: CryptoForecast) -> Dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "horizon": row.horizon,
        "generated_at": iso(row.forecast_generated_at),
        "target_timestamp": iso(row.target_timestamp),
        "last_close": row.last_close,
        "prediction": row.prediction,
        "lower_bound": row.lower_bound,
        "upper_bound": row.upper_bound,
        "model_name": row.model_name,
        "model_version": row.model_version,
        "feature_version": row.feature_version,
        "training_window": row.training_window,
        "training_end_time": iso(row.training_end_time),
        "metrics": row.metrics,
        "baseline_metrics": row.baseline_metrics,
        "beats_baseline": row.beats_baseline,
        "data_source": row.data_source,
        "data_quality": row.data_quality,
        "limitations": row.limitations,
        "evaluated": row.evaluated,
        "label": "MODELLED FORECAST",
        "origin": "MODELLED",
    }


def pending_forecasts(*, limit: int = 50, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Forecasts whose target timestamp has passed but that are not yet scored."""
    reference = to_naive_utc(now or utcnow())
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(CryptoForecast)
                .where(
                    CryptoForecast.evaluated.is_(False),
                    CryptoForecast.target_timestamp.is_not(None),
                    CryptoForecast.target_timestamp <= reference,
                )
                .order_by(CryptoForecast.target_timestamp)
                .limit(max(1, min(limit, 200)))
            )
        )
        return [_forecast_row(row) for row in rows]


def insert_forecast_evaluation(record: Dict[str, Any], *, mark_evaluated: bool = True) -> None:
    evaluated_at = to_naive_utc(record.get("evaluated_at")) or utcnow().replace(tzinfo=None)
    with session_scope() as db:
        db.add(
            CryptoForecastEvaluation(
                forecast_id=record["forecast_id"],
                symbol=record["symbol"],
                timeframe=record["timeframe"],
                predicted=float(record["predicted"]),
                actual=record.get("actual"),
                error=record.get("error"),
                absolute_error=record.get("absolute_error"),
                percentage_error=record.get("percentage_error"),
                directional_correct=record.get("directional_correct"),
                within_interval=record.get("within_interval"),
                model_name=record.get("model_name"),
                model_version=record.get("model_version"),
                evaluated_at=evaluated_at,
            )
        )
        if mark_evaluated:
            row = db.get(CryptoForecast, record["forecast_id"])
            if row is not None:
                row.evaluated = True


def forecast_performance(*, symbol: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
    """
    Realised model performance from stored evaluations (spec §31, §77).

    Reported only from evaluations that actually happened — no placeholder
    accuracy is returned when there is nothing to score.
    """
    with session_scope() as db:
        query = select(CryptoForecastEvaluation).order_by(desc(CryptoForecastEvaluation.evaluated_at))
        if symbol:
            query = query.where(CryptoForecastEvaluation.symbol == symbol)
        rows = list(db.scalars(query.limit(max(1, min(limit, 5000)))))
        if not rows:
            return {
                "status": "UNAVAILABLE",
                "reason": "no forecasts have completed their horizon yet",
                "evaluations": 0,
            }
        absolute_errors = [row.absolute_error for row in rows if row.absolute_error is not None]
        directional = [row.directional_correct for row in rows if row.directional_correct is not None]
        within = [row.within_interval for row in rows if row.within_interval is not None]
        mae = sum(absolute_errors) / len(absolute_errors) if absolute_errors else None
        return {
            "status": "OK",
            "evaluations": len(rows),
            "mae": mae,
            "directional_accuracy": (sum(1 for d in directional if d) / len(directional)) if directional else None,
            "interval_coverage": (sum(1 for w in within if w) / len(within)) if within else None,
            "latest_evaluated_at": iso(rows[0].evaluated_at),
            "models": sorted({row.model_name for row in rows if row.model_name}),
        }


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------
def create_target(record: Dict[str, Any]) -> None:
    with session_scope() as db:
        db.add(
            CryptoTarget(
                id=record["id"],
                symbol=record["symbol"],
                target_price=float(record["target_price"]),
                direction=record["direction"],
                target_date=to_naive_utc(record.get("target_date")),
                created_at=to_naive_utc(record.get("created_at")) or utcnow().replace(tzinfo=None),
                source=record.get("source") or "user",
                methodology=record.get("methodology") or "User-defined analytical milestone.",
                status=record.get("status") or "ACTIVE",
                first_reached_at=to_naive_utc(record.get("first_reached_at")),
                notes=record.get("notes"),
            )
        )


def list_targets(*, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with session_scope() as db:
        query = select(CryptoTarget).order_by(desc(CryptoTarget.created_at))
        if symbol:
            query = query.where(CryptoTarget.symbol == symbol)
        rows = list(db.scalars(query.limit(max(1, min(limit, crypto_settings.max_targets_per_symbol * 5)))))
        return [_target_row(row) for row in rows]


def get_target(target_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as db:
        row = db.get(CryptoTarget, target_id)
        return _target_row(row) if row else None


def _target_row(row: CryptoTarget) -> Dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "target_price": row.target_price,
        "direction": row.direction,
        "target_date": iso(row.target_date),
        "created_at": iso(row.created_at),
        "source": row.source,
        "methodology": row.methodology,
        "status": row.status,
        "first_reached_at": iso(row.first_reached_at),
        "notes": row.notes,
        "origin": "CALCULATED" if row.source == "derived" else "SOURCE",
    }


def update_target(
    target_id: str,
    *,
    status: Optional[str] = None,
    first_reached_at: Optional[datetime] = None,
) -> bool:
    with session_scope() as db:
        row = db.get(CryptoTarget, target_id)
        if row is None:
            return False
        if status is not None:
            row.status = status
        if first_reached_at is not None and row.first_reached_at is None:
            row.first_reached_at = to_naive_utc(first_reached_at)
        return True


def count_targets(symbol: str) -> int:
    with session_scope() as db:
        return int(
            db.scalar(
                select(func.count()).select_from(CryptoTarget).where(CryptoTarget.symbol == symbol)
            )
            or 0
        )


def record_target_event(record: Dict[str, Any]) -> None:
    with session_scope() as db:
        db.add(
            CryptoTargetEvent(
                target_id=record["target_id"],
                symbol=record["symbol"],
                event_type=record["event_type"],
                status=record.get("status"),
                observed_price=record.get("observed_price"),
                observed_at=to_naive_utc(record["observed_at"]) or utcnow().replace(tzinfo=None),
                source=record.get("source"),
                detail=record.get("detail") or {},
            )
        )


def target_events(target_id: str, *, limit: int = 50) -> List[Dict[str, Any]]:
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(CryptoTargetEvent)
                .where(CryptoTargetEvent.target_id == target_id)
                .order_by(desc(CryptoTargetEvent.observed_at))
                .limit(max(1, min(limit, 500)))
            )
        )
        return [
            {
                "id": row.id,
                "target_id": row.target_id,
                "symbol": row.symbol,
                "event_type": row.event_type,
                "status": row.status,
                "observed_price": row.observed_price,
                "observed_at": iso(row.observed_at),
                "source": row.source,
                "detail": row.detail,
            }
            for row in rows
        ]


# ---------------------------------------------------------------------------
# categories / sources / health
# ---------------------------------------------------------------------------
def upsert_categories(provider: str, categories: Sequence[Dict[str, Any]]) -> int:
    written = 0
    with session_scope() as db:
        for entry in categories:
            category_id = entry.get("id")
            if not category_id:
                continue
            row = db.scalar(
                select(CryptoCategory).where(
                    CryptoCategory.category_id == category_id, CryptoCategory.provider == provider
                )
            )
            if row is None:
                row = CryptoCategory(category_id=category_id, name=entry.get("name") or category_id, provider=provider)
                db.add(row)
            row.name = entry.get("name") or row.name
            row.market_cap = entry.get("market_cap")
            row.market_cap_change_24h = entry.get("market_cap_change_24h")
            row.volume_24h = entry.get("volume_24h")
            row.top_coins = entry.get("top_3_coins") or []
            row.observed_at = utcnow().replace(tzinfo=None)
            written += 1
    return written


def count_categories() -> int:
    with session_scope() as db:
        return int(db.scalar(select(func.count()).select_from(CryptoCategory)) or 0)


def register_data_sources(sources: Sequence[Dict[str, Any]]) -> int:
    written = 0
    with session_scope() as db:
        for entry in sources:
            provider = entry.get("provider")
            if not provider:
                continue
            row = db.get(CryptoDataSource, provider)
            if row is None:
                row = CryptoDataSource(provider=provider)
                db.add(row)
            row.role = entry.get("role") or "market-data"
            row.base_url = entry.get("base_url")
            row.native_intervals = list(entry.get("native_intervals") or [])
            row.streaming = bool(entry.get("streaming"))
            written += 1
    return written


def record_provider_health(provider: str, *, available: bool, status: str, latency_ms: Optional[float], detail: Optional[str]) -> None:
    with session_scope() as db:
        db.add(
            CryptoProviderHealth(
                provider=provider,
                available=available,
                status=status,
                latency_ms=latency_ms,
                detail=(detail or "")[:300] or None,
                checked_at=utcnow().replace(tzinfo=None),
            )
        )


def provider_health_history(*, provider: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with session_scope() as db:
        query = select(CryptoProviderHealth).order_by(desc(CryptoProviderHealth.checked_at))
        if provider:
            query = query.where(CryptoProviderHealth.provider == provider)
        rows = list(db.scalars(query.limit(max(1, min(limit, 500)))))
        return [
            {
                "provider": row.provider,
                "available": row.available,
                "status": row.status,
                "latency_ms": row.latency_ms,
                "detail": row.detail,
                "checked_at": iso(row.checked_at),
            }
            for row in rows
        ]


def persistence_counts() -> Dict[str, int]:
    """Row counts for the persistence status endpoint."""
    return {
        "assets": count_assets(),
        "candles": candle_count(),
        "categories": count_categories(),
        "targets": _count(CryptoTarget),
        "forecasts": _count(CryptoForecast),
        "evaluations": _count(CryptoForecastEvaluation),
        "target_events": _count(CryptoTargetEvent),
        "provider_health": _count(CryptoProviderHealth),
    }


def _count(model) -> int:
    with session_scope() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)
