"""
Phase 14.2 — real resolution tracking for forecast markets.

The open-market query filters `closed=false`, so a market's *resolution* was
never visible: `RESOLVED` never rendered and nothing polled for settlements.

This module queries the CLOSED slice of the same public source (separately and
on its own, longer cache), normalizes each settled market to a resolution
record, and offers both a bulk list and a per-market lookup. A background job
(`jobs.poll_forecast_resolutions`) refreshes the cached slice so the API stays
warm without hammering the source.

Honesty rules
-------------
* A closed market with no settlement outcome is returned with
  `resolution: null` and `status: "CLOSED"` — never guessed.
* `resolutionDate` is only ever the source's own `closedTime` (or null).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .forecast_markets import fetch_closed_markets, fetch_market_by_id
from .logging_config import get_logger

logger = get_logger("neural_market.forecast_resolutions")

_SOURCE_NAME = "Polymarket public market data"

_cache: dict[str, Any] = {"expires": 0.0, "records": [], "by_id": {}}
_lock = asyncio.Lock()


def _to_record(market: dict[str, Any]) -> dict[str, Any]:
    sources = market.get("sources") or []
    return {
        "marketId": market.get("id"),
        "conditionId": market.get("conditionId") or "",
        "title": market.get("title"),
        "category": market.get("category"),
        "status": market.get("status"),
        "resolution": market.get("resolution"),
        "resolutionDate": market.get("resolutionDate"),
        "closeTime": market.get("closeTime"),
        "yesProbability": market.get("yesProbability"),
        "noProbability": market.get("noProbability"),
        "source": {
            "name": _SOURCE_NAME,
            "url": (sources[0].get("url") if sources else None) or "https://polymarket.com",
            "verifiedAt": (sources[0].get("verifiedAt") if sources else None) or datetime.now(timezone.utc).isoformat(),
        },
    }


async def _refresh() -> list[dict[str, Any]]:
    markets = await fetch_closed_markets(
        settings.forecast_resolution_scan_limit,
        settings.forecast_market_timeout_seconds,
    )
    records = [_to_record(market) for market in markets]
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        for key in (record.get("marketId"), record.get("conditionId")):
            if key:
                by_id[str(key)] = record
    _cache["expires"] = time.monotonic() + settings.forecast_resolution_cache_ttl_seconds
    _cache["records"] = records
    _cache["by_id"] = by_id
    return records


async def get_resolutions(*, force: bool = False, resolved_only: bool = True) -> list[dict[str, Any]]:
    """Recently settled markets (newest first by the source's ordering)."""
    async with _lock:
        if force or _cache["expires"] <= time.monotonic() or not _cache["records"]:
            try:
                await _refresh()
            except Exception as exc:
                logger.warning("forecast resolution refresh failed: %s", exc)
                if not _cache["records"]:
                    raise
    records: list[dict[str, Any]] = _cache["records"]
    if resolved_only:
        return [r for r in records if r.get("resolution") in ("YES", "NO")]
    return list(records)


async def lookup_resolution(market_id: str) -> dict[str, Any] | None:
    """Resolution for one market, from the cache then a direct source lookup."""
    cleaned = str(market_id or "").strip()
    if not cleaned:
        return None
    try:
        async with _lock:
            if _cache["expires"] <= time.monotonic() or not _cache["records"]:
                await _refresh()
    except Exception as exc:  # cache miss + source down -> try the direct path
        logger.debug("resolution cache refresh failed during lookup: %s", exc)

    cached = _cache["by_id"].get(cleaned)
    if cached is not None:
        return cached

    try:
        market = await fetch_market_by_id(cleaned, settings.forecast_market_timeout_seconds)
    except Exception as exc:
        logger.warning("direct resolution lookup failed for %s: %s", cleaned, exc)
        return None
    if market is None:
        return None
    if market.get("status") not in ("RESOLVED", "CLOSED"):
        return None
    return _to_record(market)


async def stamp_market(market: dict[str, Any]) -> dict[str, Any]:
    """Attach a resolution to a normalized market dict when one exists.

    Pure-ish helper shared by the routes/background job: returns the market
    unchanged when it is not settled, otherwise with `resolution`,
    `resolutionDate`, `status` and `resolutionSource` populated from the real
    settlement record.
    """
    if market.get("resolution") in ("YES", "NO") and market.get("status") == "RESOLVED":
        return market
    record = await lookup_resolution(str(market.get("id") or ""))
    if record is None:
        return market
    resolution = record.get("resolution")
    if resolution not in ("YES", "NO"):
        return market
    updated = dict(market)
    updated["resolution"] = resolution
    updated["status"] = "RESOLVED"
    updated["resolutionDate"] = record.get("resolutionDate") or record.get("closeTime")
    sources = list(updated.get("sources") or [])
    updated["resolutionSource"] = {
        "name": record["source"]["name"],
        "url": record["source"]["url"],
        "publishedAt": record.get("resolutionDate"),
        "verifiedAt": record["source"]["verifiedAt"],
    }
    if not sources:
        updated["sources"] = [updated["resolutionSource"]]
    return updated


async def purge_cache() -> int:
    """Expire the cached slice (background maintenance)."""
    async with _lock:
        if _cache["expires"] <= time.monotonic() and _cache["records"]:
            _cache["records"] = []
            _cache["by_id"] = {}
            _cache["expires"] = 0.0
            return 1
    return 0


def clear_cache() -> None:
    _cache["records"] = []
    _cache["by_id"] = {}
    _cache["expires"] = 0.0
