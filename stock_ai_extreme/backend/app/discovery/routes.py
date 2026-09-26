"""
Discovery API (Phase 19, spec §9, §12, §13).

Endpoint map (all under ``/api/discover``):

============================================ ====================================
``GET  /api/discover``                       one feed: trending / new /
                                             popular / recent, with filters,
                                             pagination and source health
``GET  /api/discover/taxonomy``              categories + sub-tags with live
                                             entity counts (tag navigation)
``GET  /api/discover/engine``                the weights/saturations that shape
                                             every score (transparency)
``GET  /api/discover/trends/{entity_id}``    stored {timestamp, activity, score}
                                             observations + explainable
                                             analytics for sparklines
``POST /api/discover/events``                record one real interest event
                                             (a card was opened / matched)
============================================ ====================================

The router never talks to providers directly — everything goes through
:mod:`app.discovery.service`, which caches, degrades honestly and reports the
per-source status of every response.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from . import service, store
from .config import discovery_settings
from .entities import ENTITY_TYPES, FEED_MODES

logger = get_logger("neural_market.discovery.routes")

router = APIRouter(prefix="/api/discover", tags=["discovery"])


class DiscoveryEventRequest(BaseModel):
    """One real interest event recorded by the client (spec §14)."""

    entityId: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(default="view", pattern="^(view|search)$")


def _not_configured(exc: Exception) -> HTTPException:
    logger.warning("discovery called before provider manager was bound: %s", exc)
    return HTTPException(
        503,
        "Discovery data sources are still starting up. Retry in a moment.",
    )


@router.get("")
async def discover(
    mode: str = Query(default="trending", description="trending | new | popular | recent"),
    category: Optional[str] = Query(default=None, description="Canonical category (spec §5)"),
    tag: Optional[str] = Query(default=None, description="Sub-tag filter (exact, case-insensitive)"),
    entity_type: Optional[str] = Query(default=None, alias="type", description="stock | index | crypto | commodity | forex | news_topic | forecast_event"),
    status: Optional[str] = Query(default=None, description="Lifecycle status, e.g. OPEN / RESOLVED"),
    source: Optional[str] = Query(default=None, description="Substring match on the data source name"),
    since: Optional[str] = Query(default=None, description="ISO date — only entities created on/after it (NEW feed)"),
    q: Optional[str] = Query(default=None, max_length=120, description="Substring match on name/symbol/tags"),
    limit: Optional[int] = Query(default=None, ge=1, le=discovery_settings.feed_max_limit),
    offset: int = Query(default=0, ge=0),
    personalize: bool = Query(default=False, description="Boost explicit signals (watchlist/own views/selected categories)"),
    prefer: Optional[str] = Query(default=None, description="Comma-separated categories this client prefers"),
    refresh: bool = Query(default=False, description="Bypass the server-side universe cache"),
) -> Dict[str, Any]:
    """One discovery feed, ranked by the transparent trend engine."""
    if mode.lower() not in FEED_MODES:
        raise HTTPException(422, f"Unknown mode {mode!r} — expected one of {list(FEED_MODES)}.")
    if entity_type and entity_type not in ENTITY_TYPES:
        raise HTTPException(422, f"Unknown type {entity_type!r} — expected one of {list(ENTITY_TYPES)}.")
    prefer_list: List[str] = [p.strip() for p in (prefer or "").split(",") if p.strip()]
    try:
        return await service.get_feed(
            mode=mode,
            category=category,
            tag=tag,
            entity_type=entity_type,
            status=status,
            source=source,
            since=since,
            q=q,
            limit=limit,
            offset=offset,
            personalize=personalize,
            prefer=prefer_list,
            force=refresh,
        )
    except service.DiscoveryNotConfigured as exc:
        raise _not_configured(exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("discovery feed failed")
        raise HTTPException(500, f"Discovery feed is temporarily unavailable: {exc}")


@router.get("/taxonomy")
async def taxonomy(refresh: bool = Query(default=False)) -> Dict[str, Any]:
    """Categories + sub-tags with live entity counts (spec §6, §13)."""
    try:
        return await service.get_taxonomy(force=refresh)
    except service.DiscoveryNotConfigured as exc:
        raise _not_configured(exc)
    except Exception as exc:
        logger.exception("discovery taxonomy failed")
        raise HTTPException(500, f"Taxonomy is temporarily unavailable: {exc}")


@router.get("/engine")
async def engine_meta() -> Dict[str, Any]:
    """The weights, saturations and honesty rules behind every score (§4)."""
    meta = service.trend_engine.describe()
    return {
        **meta,
        "feedModes": list(FEED_MODES),
        "entityTypes": list(ENTITY_TYPES),
        "categories": list(discovery_settings.categories),
        "observationSampleIntervalSeconds": discovery_settings.observation_sample_interval_seconds,
        "velocityLookbackHours": discovery_settings.velocity_lookback_hours,
        "personalization": {
            "enabled": discovery_settings.personalization_enabled,
            "boost": discovery_settings.personalization_boost,
            "signals": ["watchlist", "recently_viewed", "preferred_categories"],
            "note": "Explicit actions only — sensitive preferences are never inferred.",
        },
    }


@router.get("/trends/{entity_id:path}")
async def trend_history(
    entity_id: str,
    hours: Optional[int] = Query(default=None, ge=1, le=discovery_settings.trend_history_hours),
) -> Dict[str, Any]:
    """Stored trend observations + explainable analytics for one entity (§12)."""
    try:
        return await service.get_history(entity_id, hours)
    except service.DiscoveryNotConfigured as exc:
        raise _not_configured(exc)
    except Exception as exc:
        logger.exception("trend history failed for %s", entity_id)
        raise HTTPException(500, f"Trend history is temporarily unavailable: {exc}")


@router.post("/events")
async def record_event(body: DiscoveryEventRequest) -> Dict[str, Any]:
    """Record one *real* interest event (a card was opened / matched).

    These rows are the interest signal — nothing here is estimated. A failure
    reports ``recorded: false`` instead of pretending it landed.
    """
    recorded = store.record_event(body.entityId, body.kind)
    return {"recorded": recorded, "entityId": body.entityId, "kind": body.kind}


__all__ = ["router"]
