"""
Background workers (spec §86, §87).

Model training and historical aggregation are expensive, so they never run on
the request path: the API serves from cache and the worker keeps the cache,
database and forecast history fresh.

One pass does, in order:

  1. **bootstrap persistence** — catalogue, provider registry, category snapshot;
  2. **provider health** — real probes, recorded for observability;
  3. **market persistence** — real candles + quotes for a bounded symbol batch;
  4. **forecasts** — generate and store for the batch (append-only);
  5. **retrospective evaluation** — score forecasts whose horizon has elapsed;
  6. **retention** — prune high-frequency history beyond the configured window;
  7. **housekeeping** — rate-limiter bucket cleanup.

Every step is individually guarded: a failure is logged and the loop continues,
so one flaky provider can never stop persistence, evaluation or retention.
Disabled entirely with ``CRYPTO_WORKERS_ENABLED=false``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.crypto import repositories as repo
from app.crypto.config import crypto_settings
from app.crypto.schemas import ValueOrigin
from app.crypto.symbols import symbol_service
from app.crypto.timeframes import get_timeframe

logger = logging.getLogger("neural_market.crypto.workers")

#: Timeframes the worker persists history for (a real, bounded set).
PERSIST_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")

#: Timeframes the worker generates scheduled forecasts for.
FORECAST_TIMEFRAMES = ("5m", "1h", "1d")

#: Candles fetched per timeframe per pass.
PERSIST_LIMIT = 300

#: High-frequency retention window (spec §64).
RETENTION_SECONDS = 14 * 86400


async def run_crypto_loop(service=None) -> None:
    """Periodic maintenance loop. Cancelled on application shutdown."""
    if not crypto_settings.workers_enabled:
        logger.info("crypto workers disabled (CRYPTO_WORKERS_ENABLED=false)")
        return

    interval = crypto_settings.worker_interval_seconds
    logger.info("crypto worker loop started (interval=%ss)", interval)

    # First pass runs promptly so a fresh deployment gets real data quickly.
    await asyncio.sleep(5)
    while True:
        try:
            await run_once(service)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never let one failure kill the loop
            logger.warning("crypto worker pass failed: %s", exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


async def run_once(service=None, *, symbol_batch: Optional[int] = None) -> Dict[str, Any]:
    """Execute a single worker pass and return a factual summary of what happened."""
    if service is None:
        from app.crypto.services.service import crypto_service as service

    batch_size = symbol_batch or crypto_settings.worker_symbol_batch
    symbols = _symbol_batch(batch_size)
    summary: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "steps": {},
        "origin": ValueOrigin.CALCULATED.value,
    }

    summary["steps"]["bootstrap"] = await _guard("bootstrap", lambda: _bootstrap(service))
    summary["steps"]["categories"] = await _guard(
        "categories", lambda: persist_category_snapshot(service)
    )
    summary["steps"]["health"] = await _guard("health", lambda: service.probe_health())
    summary["steps"]["market"] = await _guard("market", lambda: _persist_market(service, symbols))
    summary["steps"]["forecast"] = await _guard("forecast", lambda: _persist_forecasts(service, symbols))
    summary["steps"]["evaluation"] = await _guard("evaluation", lambda: service.forecast.evaluate_pending())
    summary["steps"]["retention"] = await _guard("retention", lambda: _retain())
    summary["steps"]["housekeeping"] = await _guard("housekeeping", lambda: _housekeeping())
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    return summary


async def _guard(name: str, action) -> Dict[str, Any]:
    """Run one step; report its real outcome without ever raising."""
    try:
        result = action()
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, dict):
            return {"status": "OK", **(result or {})}
        return {"status": "OK", "result": result} if result is not None else {"status": "OK"}
    except Exception as exc:
        logger.warning("crypto worker step %s failed: %s", name, exc)
        return {"status": "FAILED", "error": type(exc).__name__, "detail": str(exc)[:200]}


def _symbol_batch(size: int) -> List[str]:
    assets = symbol_service.list_assets()
    if not assets:
        return []
    # A stable rotation would need state; a deterministic slice of the ordered
    # catalogue keeps the pass bounded and predictable.
    return [asset["symbol"] for asset in assets[: max(1, size)]]


def _bootstrap(service) -> Dict[str, Any]:
    assets = repo.upsert_assets(symbol_service.list_assets())
    sources = repo.register_data_sources(
        [
            {
                "provider": provider.name,
                "role": "market-data",
                "base_url": getattr(provider, "rest_url", None) or getattr(provider, "base_url", None),
                "native_intervals": sorted(provider.native_intervals),
                "streaming": provider.supports_streaming(),
            }
            for provider in service.manager.providers
        ]
    )
    return {"assets": assets, "sources": sources}


async def _persist_market(service, symbols: List[str]) -> Dict[str, Any]:
    written_candles = 0
    written_quotes = 0
    failures: List[str] = []
    for symbol in symbols:
        try:
            quote = await service.market.quote(symbol)
            if quote.get("source"):
                repo.upsert_quote(quote)
                written_quotes += 1
        except Exception as exc:
            failures.append(f"{symbol}:quote:{type(exc).__name__}")

        for timeframe in PERSIST_TIMEFRAMES:
            try:
                bundle = await service.market.load_series(symbol, timeframe, limit=PERSIST_LIMIT)
                if bundle.candles:
                    written_candles += repo.upsert_candles(
                        symbol=bundle.series.symbol,
                        timeframe=timeframe,
                        provider=bundle.series.source,
                        candles=bundle.candles,
                    )
            except Exception as exc:
                failures.append(f"{symbol}:{timeframe}:{type(exc).__name__}")
    return {"candles": written_candles, "quotes": written_quotes, "failures": failures[:10]}


async def _persist_forecasts(service, symbols: List[str]) -> Dict[str, Any]:
    stored = 0
    unavailable = 0
    failures: List[str] = []
    for symbol in symbols:
        for timeframe in FORECAST_TIMEFRAMES:
            try:
                payload = await service.forecast.get(symbol, timeframe, persist=True)
            except Exception as exc:
                failures.append(f"{symbol}:{timeframe}:{type(exc).__name__}")
                continue
            if payload.get("forecast"):
                stored += 1
            else:
                unavailable += 1
    return {"stored": stored, "unavailable": unavailable, "failures": failures[:10]}


def _retain() -> Dict[str, Any]:
    removed = repo.prune_candles(keep_seconds=RETENTION_SECONDS)
    return {"pruned_candles": removed, "retention_seconds": RETENTION_SECONDS}


def _housekeeping() -> Dict[str, Any]:
    """Clean rate-limiter buckets so a long-running process does not leak memory."""
    from app.crypto.routes import _crypto_limiter

    removed = _crypto_limiter.cleanup()
    return {"rate_limit_buckets_cleaned": removed}


async def persist_category_snapshot(service) -> int:
    """Store the provider's real category taxonomy (called from the worker)."""
    categories = await service.manager.get_categories()
    if not categories:
        return 0
    provider = categories[0].get("source") or "coingecko"
    return repo.upsert_categories(provider, categories)
