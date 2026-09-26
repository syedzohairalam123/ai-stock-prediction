"""
Entity collectors for discovery (spec §2, §10, §17).

Each collector turns one *real* data source into normalized
:class:`~app.discovery.entities.DiscoverableEntity` objects:

=========================== ========================================== ====================
Collector                   Source                                     Types
=========================== ========================================== ====================
``forecast_events``         Polymarket Gamma API (public, keyless)     forecast_event
``news_topics``             Phase 17 topic engine tables (real         news_topic
                            mention counts / hourly timeline)
``psx_stocks``              Phase 2 provider manager via              stock
                            ``popular_stocks`` (quotes + profiles)
``global_indices``          Provider manager quotes for real           index
                            quotable world indices
``instruments``             Provider manager quotes for crypto /       crypto, commodity,
                            commodities / forex                       forex
=========================== ========================================== ====================

Rules honoured by every collector:

    * one failing source is reported in ``sources`` with its reason and
      never blanks out the others (spec §17 — honest degradation);
    * a metric the source does not supply stays ``None`` (the trend engine
      reports it as a *missing signal*, never as 0);
    * ``created_at`` is only ever filled from a real creation timestamp — a
      stock with no real "created" date simply cannot appear in the NEW feed.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..logging_config import get_logger
from .config import discovery_settings
from .entities import ActivityMetric, DiscoverableEntity
from .taxonomy import entity_category_and_tags, normalize_tag, tags_from_sector_groups

logger = get_logger("neural_market.discovery.collectors")

#: Real, quotable world indices (Yahoo symbols). PSX *index* levels are not
#: available on the free provider (documented app-wide), so they are honestly
#: absent here rather than served as demo data.
INDEX_UNIVERSE: Dict[str, Dict[str, str]] = {
    "^GSPC": {"name": "S&P 500", "region": "United States"},
    "^DJI": {"name": "Dow Jones Industrial Average", "region": "United States"},
    "^IXIC": {"name": "Nasdaq Composite", "region": "United States"},
    "^NDX": {"name": "Nasdaq 100", "region": "United States"},
    "^VIX": {"name": "CBOE Volatility Index", "region": "United States"},
    "^FTSE": {"name": "FTSE 100", "region": "United Kingdom"},
    "^N225": {"name": "Nikkei 225", "region": "Japan"},
    "^HSI": {"name": "Hang Seng", "region": "Hong Kong"},
    "^GDAXI": {"name": "DAX", "region": "Germany"},
    "^BSESN": {"name": "BSE Sensex", "region": "India"},
}

_ASSET_CATEGORIES = {"crypto": "Crypto", "commodities": "Commodities", "forex": "Forex"}


def _iso(value: Any) -> Optional[str]:
    """Normalize a timestamp to an ISO string, or None when there isn't one."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text  # already an ISO-ish string from the source
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _num(value: Any) -> Optional[float]:
    """Float or None — NaN/inf/strings become None, never a fake 0."""
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _data_mode_for_status(status: Optional[str]) -> str:
    """Map a provider freshness status onto the discovery data-mode contract.

    LIVE = fresh provider data · DELAYED = real but cached/older · UNAVAILABLE
    = no provider could answer. Nothing in this module ever emits DEMO.
    """
    return {
        "LIVE": "LIVE",
        "RECENT": "DELAYED",
        "CACHED": "DELAYED",
        "STALE": "DELAYED",
        "UNAVAILABLE": "UNAVAILABLE",
    }.get((status or "").upper(), "DELAYED")


def _source_report(source: str, count: int, *, status: str = "OK", reason: Optional[str] = None,
                   requested: Optional[int] = None, failed: Optional[list] = None) -> Dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "count": count,
        "requested": requested,
        "failed": failed or [],
        "reason": reason,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# forecast events — Polymarket public Gamma API
# ---------------------------------------------------------------------------
async def forecast_events() -> Tuple[List[DiscoverableEntity], Dict[str, Any]]:
    """Live public forecast markets with their real createdAt/updatedAt."""
    from ..config import settings as app_settings
    from ..forecast_markets import fetch_markets

    try:
        markets = await fetch_markets(
            discovery_settings.forecast_event_limit,
            app_settings.forecast_market_timeout_seconds,
        )
    except Exception as exc:
        logger.debug("forecast event collection failed: %s", exc)
        return [], _source_report(
            "polymarket", 0, status="UNAVAILABLE", reason=str(exc),
            requested=discovery_settings.forecast_event_limit,
        )

    entities: List[DiscoverableEntity] = []
    for market in markets:
        question = str(market.get("title") or "").strip()
        market_id = str(market.get("id") or "").strip()
        if not question or not market_id:
            continue
        volume = _num(market.get("volume24hr"))
        participants = _num(market.get("participantCount"))
        if volume is not None:
            activity = ActivityMetric(
                label="24h volume", value=round(volume, 2), unit="USD",
                as_of=_iso(market.get("updatedAt")), note="Reported by the public market API.",
            )
            activity_kind = "event_volume"
            activity_value = volume
        elif participants is not None:
            activity = ActivityMetric(
                label="Participants", value=int(participants), unit="traders",
                as_of=_iso(market.get("updatedAt")), note="Reported by the public market API.",
            )
            activity_kind = "event_participants"
            activity_value = participants
        else:
            activity = ActivityMetric(
                label="24h volume", value=None, unit="USD",
                note="The source did not publish a volume for this market.",
            )
            activity_kind = "event_volume"
            activity_value = None

        category, tags = entity_category_and_tags(category=market.get("category"), name=question)
        entities.append(
            DiscoverableEntity(
                id=f"forecast:{market_id}",
                type="forecast_event",
                name=question,
                symbol=None,
                category=category,
                tags=tags,
                created_at=_iso(market.get("createdAt")),
                updated_at=_iso(market.get("updatedAt")),
                activity=activity,
                source="Polymarket",
                data_mode=str(market.get("dataMode") or "LIVE"),
                status=str(market.get("status") or "ACTIVE"),
                route=f"/forecast/{market_id}",
                signals={
                    "created_at": _iso(market.get("createdAt")),
                    "updated_at": _iso(market.get("updatedAt")),
                    "activity_value": activity_value,
                    "activity_kind": activity_kind,
                },
                provenance={
                    "yesProbability": market.get("yesProbability"),
                    "noProbability": market.get("noProbability"),
                    "closeTime": market.get("closeTime"),
                    "volume24hr": volume,
                    "participantCount": int(participants) if participants is not None else None,
                },
            )
        )
    return entities, _source_report("polymarket", len(entities), requested=discovery_settings.forecast_event_limit)


# ---------------------------------------------------------------------------
# news topics — Phase 17 corpus tables
# ---------------------------------------------------------------------------
def news_topics() -> Tuple[List[DiscoverableEntity], Dict[str, Any]]:
    """Topics with real mention counts, velocities and timestamps."""
    try:
        from ..db import session_scope
        from ..breaking_news.models.models import NewsTopic

        with session_scope() as db:
            rows = (
                db.query(NewsTopic)
                .order_by(NewsTopic.trend_score.desc(), NewsTopic.last_seen.desc())
                .limit(discovery_settings.news_topic_limit)
                .all()
            )
            payload = [
                {
                    "id": row.id,
                    "topic_name": row.topic_name,
                    "topic_type": row.topic_type,
                    "category": row.category,
                    "mention_count": row.mention_count,
                    "article_count": row.article_count,
                    "source_count": row.source_count,
                    "trend_velocity": row.trend_velocity,
                    "last_seen": _iso(row.last_seen),
                    "first_seen": _iso(row.first_seen),
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at) or _iso(row.last_seen),
                    "related_stocks": list(row.related_stocks or []),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.debug("news topic collection failed: %s", exc)
        return [], _source_report("news_corpus", 0, status="UNAVAILABLE", reason=str(exc))

    entities: List[DiscoverableEntity] = []
    now = datetime.now(timezone.utc)
    for item in payload:
        name = str(item["topic_name"] or "").strip()
        if not name:
            continue
        last_seen = item["last_seen"]
        fresh = False
        if last_seen:
            try:
                age_hours = (now - datetime.fromisoformat(last_seen)).total_seconds() / 3600.0
                fresh = age_hours <= 24
            except ValueError:
                fresh = False
        category, tags = entity_category_and_tags(
            category=item["category"],
            tags=[normalize_tag(item["category"])] if item["category"] else [],
            name=name,
        )
        mention_count = _num(item["mention_count"])
        entities.append(
            DiscoverableEntity(
                id=f"topic:{item['id']}",
                type="news_topic",
                name=name,
                symbol=None,
                category=category,
                tags=tags,
                created_at=item["created_at"],
                updated_at=item["updated_at"] or last_seen,
                activity=ActivityMetric(
                    label="Corpus mentions",
                    value=int(mention_count) if mention_count is not None else None,
                    unit="mentions",
                    as_of=last_seen,
                    note="Counted from ingested headlines; not a readership number.",
                ),
                source="News corpus",
                data_mode="LIVE" if fresh else "DELAYED",
                status="ACTIVE",
                route=f"/topics/{item['id']}",
                signals={
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"] or last_seen,
                    "activity_value": mention_count,
                    "activity_kind": "topic_mentions",
                    "velocity": _num(item["trend_velocity"]),
                    "velocity_kind": "topic",
                    "news_sources": _num(item["source_count"]),
                },
                provenance={
                    "topicType": item["topic_type"],
                    "articleCount": item["article_count"],
                    "sourceCount": item["source_count"],
                    "firstSeen": item["first_seen"],
                    "lastSeen": last_seen,
                    "relatedStocks": item["related_stocks"][:8],
                },
            )
        )
    return entities, _source_report("news_corpus", len(entities), requested=discovery_settings.news_topic_limit)


# ---------------------------------------------------------------------------
# PSX stocks — provider manager (quotes + profiles + sparkline history)
# ---------------------------------------------------------------------------
async def psx_stocks(manager) -> Tuple[List[DiscoverableEntity], Dict[str, Any]]:
    """Popular PSX equities, quoted live through the Phase 2 provider chain."""
    from ..popular_stocks import POPULAR_PSX_STOCKS, fetch_stock_data, get_popular_stocks_list
    from ..repository import list_watchlist

    group_by_symbol = tags_from_sector_groups(POPULAR_PSX_STOCKS)
    symbols: List[str] = list(get_popular_stocks_list(limit=discovery_settings.stock_universe_limit))
    # Watchlist tickers belong in the universe: they are real user interest,
    # and a saved stock that cannot be discovered would be a hole in the feed.
    try:
        for item in list_watchlist():
            ticker = str(item.get("ticker") or "").upper()
            if ticker and ticker not in symbols:
                symbols.append(ticker)
    except Exception as exc:
        logger.debug("watchlist symbols skipped: %s", exc)
    symbols = symbols[: max(discovery_settings.stock_universe_limit * 2, 40)]

    results = await asyncio.gather(
        *(fetch_stock_data(manager, symbol) for symbol in symbols), return_exceptions=True
    )

    entities: List[DiscoverableEntity] = []
    failed: List[str] = []
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception) or result is None:
            failed.append(symbol)
            continue
        change_pct = _num(result.get("change_pct"))
        group_tag = group_by_symbol.get(symbol.upper())
        extra = [tag for tag in (group_tag, result.get("sector"), result.get("industry"), "PSX") if tag]
        category, tags = entity_category_and_tags(category="Stocks", tags=extra, name=result.get("name") or "")
        # De-duplicate while keeping order (sector + group can be identical).
        tags = list(dict.fromkeys(t for t in tags if t))
        entities.append(
            DiscoverableEntity(
                id=f"stock:{symbol.upper()}",
                type="stock",
                name=result.get("name") or symbol.upper(),
                symbol=symbol.upper(),
                category=category,
                tags=tags[:7],
                created_at=None,  # no real listing timestamp here — never faked
                updated_at=_iso(result.get("timestamp")),
                activity=ActivityMetric(
                    label="Day change",
                    value=change_pct,
                    unit="%",
                    as_of=_iso(result.get("timestamp")),
                    note="Versus the provider's previous close.",
                ),
                source=str(result.get("source") or "provider"),
                data_mode=_data_mode_for_status(result.get("status")),
                status="ACTIVE",
                route=f"/stock/{symbol.upper()}",
                signals={
                    "updated_at": _iso(result.get("timestamp")),
                    "activity_value": change_pct,
                    "activity_kind": "change_pct",
                },
                provenance={
                    "price": result.get("price"),
                    "previousClose": result.get("previous_close"),
                    "marketCap": result.get("market_cap"),
                    "sector": result.get("sector"),
                    "industry": result.get("industry"),
                    "volume": result.get("volume"),
                    "dataStatus": result.get("status"),
                    "sparkline": [
                        {"date": row.get("date"), "price": row.get("price")}
                        for row in (result.get("trend") or [])[:10]
                    ],
                },
            )
        )

    status = "OK" if not failed else ("DEGRADED" if entities else "UNAVAILABLE")
    return entities, _source_report(
        "psx_quotes", len(entities), status=status, requested=len(symbols), failed=failed,
        reason=None if entities else "No PSX symbol could be quoted right now.",
    )


# ---------------------------------------------------------------------------
# global indices — provider manager quotes
# ---------------------------------------------------------------------------
async def global_indices(manager) -> Tuple[List[DiscoverableEntity], Dict[str, Any]]:
    """Real quotable world indices (levels are provider data, never demo)."""
    results = await asyncio.gather(
        *(manager.quote(symbol) for symbol in INDEX_UNIVERSE), return_exceptions=True
    )
    entities: List[DiscoverableEntity] = []
    failed: List[str] = []
    for symbol, result in zip(INDEX_UNIVERSE, results):
        if isinstance(result, Exception):
            failed.append(symbol)
            continue
        change_pct = _num(result.change_percent)
        meta = INDEX_UNIVERSE[symbol]
        category, tags = entity_category_and_tags(
            category="Finance", tags=["Index", meta["region"]], name=meta["name"]
        )
        entities.append(
            DiscoverableEntity(
                id=f"index:{symbol}",
                type="index",
                name=meta["name"],
                symbol=symbol,
                category=category,
                tags=tags,
                created_at=None,
                updated_at=_iso(result.timestamp),
                activity=ActivityMetric(
                    label="Day change", value=change_pct, unit="%",
                    as_of=_iso(result.timestamp),
                ),
                source=str(result.source or "provider"),
                data_mode=_data_mode_for_status(result.status.value if result.status else None),
                status="ACTIVE",
                route=None,
                signals={
                    "updated_at": _iso(result.timestamp),
                    "activity_value": change_pct,
                    "activity_kind": "change_pct",
                },
                provenance={
                    "price": _num(result.price),
                    "previousClose": _num(result.previous_close),
                    "region": meta["region"],
                    "dataStatus": result.status.value if result.status else None,
                },
            )
        )
    status = "OK" if not failed else ("DEGRADED" if entities else "UNAVAILABLE")
    return entities, _source_report(
        "index_quotes", len(entities), status=status, requested=len(INDEX_UNIVERSE), failed=failed,
        reason=None if entities else "No index could be quoted right now.",
    )


# ---------------------------------------------------------------------------
# crypto / commodities / forex instruments — provider manager quotes
# ---------------------------------------------------------------------------
async def instruments(manager) -> Tuple[List[DiscoverableEntity], Dict[str, Any]]:
    """Curated crypto / commodity / forex instruments with live quotes."""
    from ..multi_asset import ASSET_CLASSES

    symbols: List[Tuple[str, str, str]] = []  # (symbol, name, asset_class)
    for asset_class, mapping in ASSET_CLASSES.items():
        for symbol, name in list(mapping.items())[: max(discovery_settings.instrument_limit // 3, 4)]:
            symbols.append((symbol, name, asset_class))

    results = await asyncio.gather(
        *(manager.quote(symbol) for symbol, _name, _cls in symbols), return_exceptions=True
    )

    entities: List[DiscoverableEntity] = []
    failed: List[str] = []
    for (symbol, name, asset_class), result in zip(symbols, results):
        if isinstance(result, Exception):
            failed.append(symbol)
            continue
        change_pct = _num(result.change_percent)
        category, tags = entity_category_and_tags(
            category=_ASSET_CATEGORIES.get(asset_class, "Finance"),
            tags=[name, asset_class.title()],
            name=name,
        )
        entities.append(
            DiscoverableEntity(
                id=f"{asset_class}:{symbol}",
                type={"crypto": "crypto", "commodities": "commodity", "forex": "forex"}.get(
                    asset_class, "commodity"
                ),
                name=name,
                symbol=symbol,
                category=category,
                tags=tags,
                created_at=None,
                updated_at=_iso(result.timestamp),
                activity=ActivityMetric(
                    label="Day change", value=change_pct, unit="%",
                    as_of=_iso(result.timestamp),
                ),
                source=str(result.source or "provider"),
                data_mode=_data_mode_for_status(result.status.value if result.status else None),
                status="ACTIVE",
                route={"crypto": "/crypto", "commodities": "/forex-commodities",
                       "forex": "/forex-commodities"}.get(asset_class),
                signals={
                    "updated_at": _iso(result.timestamp),
                    "activity_value": change_pct,
                    "activity_kind": "change_pct",
                },
                provenance={
                    "price": _num(result.price),
                    "previousClose": _num(result.previous_close),
                    "assetClass": asset_class,
                    "dataStatus": result.status.value if result.status else None,
                },
            )
        )
    status = "OK" if not failed else ("DEGRADED" if entities else "UNAVAILABLE")
    return entities, _source_report(
        "instrument_quotes", len(entities), status=status, requested=len(symbols), failed=failed,
        reason=None if entities else "No instrument could be quoted right now.",
    )


# ---------------------------------------------------------------------------
async def collect(manager) -> Tuple[List[DiscoverableEntity], List[Dict[str, Any]]]:
    """Run every collector concurrently; isolate failures per source."""
    forecast_task = forecast_events()
    stocks_task = psx_stocks(manager)
    indices_task = global_indices(manager)
    instruments_task = instruments(manager)

    (forecast_entities, forecast_report), (stock_entities, stock_report), (
        index_entities, index_report
    ), (instrument_entities, instrument_report) = await asyncio.gather(
        forecast_task, stocks_task, indices_task, instruments_task, return_exceptions=False
    )
    # News topics are DB-only (no network), so they run inline for simplicity.
    topic_entities, topic_report = news_topics()

    entities = (
        forecast_entities
        + topic_entities
        + stock_entities
        + index_entities
        + instrument_entities
    )
    reports = [forecast_report, topic_report, stock_report, index_report, instrument_report]
    return entities, reports


__all__ = [
    "INDEX_UNIVERSE",
    "collect",
    "forecast_events",
    "news_topics",
    "psx_stocks",
    "global_indices",
    "instruments",
]
