"""
Background maintenance jobs (started in FastAPI's lifespan).

A single asyncio task that periodically:
  1. ingests real news from every enabled keyless publisher feed (and any
     configured paid API), so the Financial Intelligence Desk fills itself
     instead of waiting for someone to press Refresh
  2. checks every active alert against freshly fetched data — the same
     evaluation the manual /alerts/check route runs — and sends a
     notification (Telegram/email, if configured) when something fires
  3. resolves prediction records whose target date has passed, so the
     drift-monitoring numbers stay current without anyone clicking a button
  4. purges expired-but-still-usable TTL cache entries and cleans up stale
     rate-limiter buckets (bounded memory on long-running servers)

Everything is best-effort and isolated — one failing job never takes down
the loop or the API. Disable entirely with BACKGROUND_JOBS_ENABLED=false.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta

import pandas as pd

from . import forecast_history
from . import forecast_resolutions
from . import repository as repo
from .alerts import evaluate_alerts
from .config import settings
from .db import session_scope
from .monitoring import resolve_predictions
from .news_service import get_news_service
from .notifications import notify
from .providers import fx_rates

logger = logging.getLogger("neural_market.jobs")

#: Timestamp of the last successful news ingest, so the maintenance loop can
#: run on a different (much faster) cadence than the news refresh interval.
_last_news_ingest: float = 0.0


async def ingest_news(*, force: bool = False) -> int:
    """Pull real news from every enabled source and store it.

    Throttled by ``NEWS_REFRESH_INTERVAL_SECONDS`` (default 30 min) because the
    maintenance loop itself ticks far more often than publishers update. Returns
    the number of newly stored articles, or 0 when the interval has not elapsed.
    """
    global _last_news_ingest

    if not settings.news_rss_enabled and not any(
        (settings.newsapi_key, settings.finnhub_api_key, settings.alpha_vantage_key)
    ):
        return 0

    interval = max(int(settings.news_refresh_interval_seconds), 300)
    now = time.monotonic()
    if not force and _last_news_ingest and (now - _last_news_ingest) < interval:
        return 0

    sources = ["rss", "symbols"] if settings.news_rss_enabled else []
    sources += ["newsapi", "finnhub", "alpha_vantage"]
    region = None if settings.news_default_region.upper() == "ALL" else settings.news_default_region

    try:
        service = get_news_service()
        with session_scope() as db:
            stored = await service.aggregate_and_store(db, sources=sources, region=region)
        # Only mark the interval as elapsed once the attempt completed; a failure
        # should be retried on the next tick, not suppressed for half an hour.
        _last_news_ingest = now
        if stored:
            logger.info("background job ingested %d new news article(s)", stored)
        return int(stored)
    except Exception as exc:
        logger.warning("background news ingest failed: %s", exc)
        return 0


async def check_all_alerts(manager) -> list[dict]:
    """Evaluate every active alert against fresh data; mark + notify the
    ones that fire. Returns the triggered alerts (useful for tests/logs)."""
    active = repo.list_alerts(active_only=True)
    if not active:
        return []
    by_ticker: dict[str, list[dict]] = {}
    for alert in active:
        by_ticker.setdefault(alert["ticker"], []).append(alert)

    triggered_all: list[dict] = []
    for ticker, alerts in by_ticker.items():
        try:
            d, source, status = await manager.history(ticker, date.today() - timedelta(days=60), date.today())
            triggered = evaluate_alerts(d, alerts)
            for t in triggered:
                repo.mark_alert_triggered(t["id"], t["current_value"])
                notify(
                    f"🔔 Neural Market alert: {ticker.upper()}",
                    f"{t['alert_type']} threshold {t['threshold']} — current value {t['current_value']} "
                    f"(data: {source}/{status.value}).",
                )
            triggered_all.extend(triggered)
        except Exception as exc:
            logger.warning("background alert check failed for %s: %s", ticker, exc)
    if triggered_all:
        logger.info("background job triggered %d alert(s)", len(triggered_all))
    return triggered_all


async def resolve_all_predictions(manager) -> int:
    """Resolve every prediction whose first forecast date has passed, using
    the same real-close lookup the /api/monitoring/resolve route performs.
    Returns how many records were resolved."""
    unresolved = repo.get_unresolved_predictions()
    needed: dict[tuple[str, date], float | None] = {}
    for record in unresolved:
        preds = record.get("predictions") or []
        if not preds:
            continue
        target = date.fromisoformat(preds[0]["date"])
        if target <= date.today():
            needed[(record["ticker"], target)] = None

    for (ticker, target) in list(needed.keys()):
        try:
            d, _, _ = await manager.history(ticker, target - timedelta(days=5), target + timedelta(days=2))
            d2 = d.reset_index()
            d2["_d"] = pd.to_datetime(d2[d2.columns[0]]).dt.date
            match = d2[d2["_d"] == target]
            if not match.empty:
                needed[(ticker, target)] = float(match.iloc[0]["Close"])
        except Exception as exc:
            logger.warning("background resolve failed for %s @ %s: %s", ticker, target, exc)

    resolved = resolve_predictions(unresolved, actual_price_lookup=lambda t, d0: needed.get((t, d0)))
    for r in resolved:
        repo.set_actual_price(r["id"], r["actual_price"])
    if resolved:
        logger.info("background job resolved %d past prediction(s)", len(resolved))
    return len(resolved)


async def poll_forecast_resolutions() -> int:
    """Phase 14.2 — refresh the settled-market slice so resolution lookups are
    warm and RESOLVED states stay current without a button press.

    Returns the number of settled records seen; 0 on any failure (never raises,
    like every other job here).
    """
    try:
        records = await forecast_resolutions.get_resolutions(force=True, resolved_only=False)
        settled = [r for r in records if r.get("resolution") in ("YES", "NO")]
        if settled:
            logger.info("background job refreshed %d settled forecast market(s)", len(settled))
        return len(settled)
    except Exception as exc:
        logger.warning("background job error (forecast resolutions): %s", exc)
        return 0


async def run_background_loop(manager, limiter) -> None:
    """Infinite maintenance loop. `manager` is the provider manager and
    `limiter` the app's rate limiter (both created in main.py)."""
    interval = max(int(settings.background_interval_seconds), 30)
    logger.info("background maintenance loop started (interval %ds)", interval)
    while True:
        started = time.monotonic()
        try:
            await ingest_news()
        except Exception as exc:
            logger.warning("background job error (news): %s", exc)
        try:
            # Phase 17: rebuild the breaking/news-topic feed from the corpus that
            # ingest_news() just refreshed, and re-run observed market-impact
            # analysis for the highest-scoring events. Throttled internally by
            # BREAKING_NEWS_REFRESH_INTERVAL_SECONDS.
            from .breaking_news import run_periodic_refresh

            stats = await run_periodic_refresh()
            if stats:
                logger.info("background job refreshed breaking news: %s", stats)
        except Exception as exc:
            logger.warning("background job error (breaking news): %s", exc)
        try:
            await check_all_alerts(manager)
        except Exception as exc:
            logger.warning("background job error (alerts): %s", exc)
        try:
            await resolve_all_predictions(manager)
        except Exception as exc:
            logger.warning("background job error (resolve): %s", exc)
        try:
            # Phase 14.2: keep the settled-market slice fresh so RESOLVED states
            # render without a manual refresh.
            await poll_forecast_resolutions()
        except Exception as exc:
            logger.warning("background job error (forecast resolutions): %s", exc)
        try:
            purged = await manager.purge_caches()
            # Phase 7: the forex/commodities rate caches are long-lived too, so
            # they expire on the same loop instead of growing unbounded.
            purged += await fx_rates.purge_caches()
            # Phase 8: the news service caches per-symbol feed results too.
            purged += get_news_service().purge_cache()
            # Phase 14: forecast history / resolution caches.
            purged += await forecast_history.purge_cache()
            purged += await forecast_resolutions.purge_cache()
            dropped = limiter.cleanup()
            if purged or dropped:
                logger.info(
                    "background maintenance: purged %d cache entries, dropped %d rate-limit buckets",
                    purged, dropped,
                )
        except Exception as exc:
            logger.warning("background job error (maintenance): %s", exc)
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(interval - elapsed, 1))