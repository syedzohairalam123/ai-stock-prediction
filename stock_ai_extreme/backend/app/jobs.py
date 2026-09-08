"""
Background maintenance jobs (started in FastAPI's lifespan).

A single asyncio task that periodically:
  1. checks every active alert against freshly fetched data — the same
     evaluation the manual /alerts/check route runs — and sends a
     notification (Telegram/email, if configured) when something fires
  2. resolves prediction records whose target date has passed, so the
     drift-monitoring numbers stay current without anyone clicking a button
  3. purges expired-but-still-usable TTL cache entries and cleans up stale
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

from . import repository as repo
from .alerts import evaluate_alerts
from .config import settings
from .monitoring import resolve_predictions
from .notifications import notify

logger = logging.getLogger("neural_market.jobs")


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


async def run_background_loop(manager, limiter) -> None:
    """Infinite maintenance loop. `manager` is the provider manager and
    `limiter` the app's rate limiter (both created in main.py)."""
    interval = max(int(settings.background_interval_seconds), 30)
    logger.info("background maintenance loop started (interval %ds)", interval)
    while True:
        started = time.monotonic()
        try:
            await check_all_alerts(manager)
        except Exception as exc:
            logger.warning("background job error (alerts): %s", exc)
        try:
            await resolve_all_predictions(manager)
        except Exception as exc:
            logger.warning("background job error (resolve): %s", exc)
        try:
            purged = await manager.purge_caches()
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