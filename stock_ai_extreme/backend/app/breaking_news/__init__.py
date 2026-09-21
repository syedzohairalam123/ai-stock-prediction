"""
Phase 17 — Real-Time Breaking News + Trending Topics + Market Impact Intelligence.

A real-data news intelligence engine layered on top of the Phase 8 news desk:
the same publisher feeds, the same stored corpus and the same analytics, with
breaking-event detection, duplicate clustering, hot-topic trend scoring, observed
market-impact association and Phase 14 forecast probability movement on top.

Import surface:

* ``breaking_news_router`` — mount this in the FastAPI app.
* ``configure_breaking_news(manager)`` — wire the Phase 2 provider manager in
  after main.py has built one (needed for market-impact analysis).
* ``run_periodic_refresh()`` — the background-job entry point that rebuilds the
  feed and refreshes impact analysis.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .config import breaking_news_settings
from .engine import BreakingNewsEngine, FeedBundle, engine as breaking_news_engine
from .routes import build_snapshot
from .routes import router as breaking_news_router
from .stream import stream_manager

__all__ = [
    "breaking_news_router",
    "breaking_news_engine",
    "BreakingNewsEngine",
    "FeedBundle",
    "stream_manager",
    "configure_breaking_news",
    "run_periodic_refresh",
    "get_engine",
]

#: Timestamp of the last periodic rebuild, so the maintenance loop can tick far
#: more often than the (provider-costly) breaking-news rebuild interval.
_last_refresh: float = 0.0


def get_engine() -> BreakingNewsEngine:
    return breaking_news_engine


def configure_breaking_news(manager: Any) -> BreakingNewsEngine:
    """Attach the provider manager and bind the streaming snapshot producer.

    Called once from ``main.py`` after the provider manager exists. Idempotent,
    so a test or a second app instance can call it again safely.
    """
    breaking_news_engine.configure(manager)
    stream_manager.bind(lambda: build_snapshot())
    return breaking_news_engine


async def run_periodic_refresh(*, force: bool = False) -> Optional[dict]:
    """Background job: rebuild the feed and refresh observed impacts.

    Throttled by ``BREAKING_NEWS_REFRESH_INTERVAL_SECONDS`` because the impact
    pass makes real provider calls. Returns a small stats dict, or ``None`` when
    the engine has not been wired to a provider manager yet (e.g. in tests).
    """
    global _last_refresh

    if breaking_news_engine.manager is None:
        return None

    interval = max(int(breaking_news_settings.refresh_interval_seconds), 120)
    now = time.monotonic()
    if not force and _last_refresh and (now - _last_refresh) < interval:
        return None

    from ..db import session_scope

    stats: dict = {}
    try:
        with session_scope() as db:
            bundle = await breaking_news_engine.rebuild(db, hours=24)
            impact_events, probability_movements = await breaking_news_engine.analyze_top_events(db, bundle)
            stats = {
                "events": len(bundle.items),
                "topics": breaking_news_engine.last_build_stats.get("topics", 0),
                "impact_events": impact_events,
                "probability_movements": probability_movements,
            }
        _last_refresh = now
        # Nudge connected clients as soon as the new data exists.
        try:
            await stream_manager.ensure_snapshot()
        except Exception:
            pass
    except Exception as exc:  # a failing rebuild must never kill the loop
        from ..logging_config import get_logger

        get_logger("neural_market.breaking_news").warning("periodic breaking-news refresh failed: %s", exc)
        return None
    return stats
