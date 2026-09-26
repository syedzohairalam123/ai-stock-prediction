"""
REST API for Phase 18 — Political & Geopolitical Data Mapping / Forecast
Visualization (all under ``/api/political``).

============================  ==================================================
``GET  /overview``           one payload for the map page (events, regions,
                             region states, measurements, sources, meta)
``GET  /regions``             region registry + per-region presentation state
``GET  /regions/{region_id}`` detail: measurements by type, events, timeline,
                             historical results
``GET  /events``              the sourced political/election calendar
``GET  /measurements``        sourced measurements with filters
``GET  /head-to-head``        neutral side-by-side sourced comparison
``GET  /timeline``            geopolitical coverage timeline (GDELT)
``GET  /sources``             the source registry with health + attribution
``GET  /meta``                enums, thresholds, neutrality statements
``GET  /health``              subsystem health and cache stats
``POST /refresh``            force provider re-fetch
============================  ==================================================

Every response carries a retrieval timestamp and per-provider status. Every
political number is quoted from a named external source with its measurement
type; the routes add no values of their own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..logging_config import get_logger
from .engine import engine
from .schemas import (
    EventsResponse,
    HeadToHeadResponse,
    MeasurementType,
    MeasurementsResponse,
    PoliticalCategory,
    PoliticalHealthResponse,
    PoliticalMetaResponse,
    RegionDataState,
    RegionDetailResponse,
    RegionsResponse,
    RegionStateDetail,
    RetrievalMeta,
    SourcesResponse,
    TimelineResponse,
    OverviewResponse,
)

logger = get_logger("neural_market.political.routes")

router = APIRouter(prefix="/api/political", tags=["political"])


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date {value!r}: use ISO format.") from exc
    return parsed


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    election_id: Optional[str] = Query(default=None, max_length=80),
    refresh: bool = Query(default=False, description="Force a provider re-fetch."),
):
    """Everything the map page needs in one request."""
    overview_payload = await engine.overview(election_id=election_id) if not refresh else None
    if overview_payload is None:
        await engine.refresh()
        overview_payload = await engine.overview(election_id=election_id)
    return overview_payload


@router.get("/regions", response_model=RegionsResponse)
async def regions(
    state: Optional[RegionDataState] = Query(default=None),
    region_type: Optional[str] = Query(default=None, pattern="^(STATE|DISTRICT|COUNTRY)$"),
):
    """The region registry with each region's current presentation state."""
    all_regions = await engine.regions_bundle()
    measurements, _pairs, _hit = await engine.measurements_bundle()
    history, _hpairs, _hhit = await engine.history_bundle()
    pool = measurements + history
    details = [
        engine.classify_region(region.id, pool)
        for region in all_regions
        if (region_type is None or region.region_type == region_type)
    ]
    if state is not None:
        details = [d for d in details if d.state == state]
    by_id = {region.id: region for region in all_regions}
    return RegionsResponse(
        regions=[by_id[d.region_id] for d in details],
        region_states=[engine._state_detail(d) for d in details],
        retrieval=RetrievalMeta(generated_at=datetime.now(timezone.utc), providers=[], cache="HIT"),
    )


@router.get("/regions/{region_id}", response_model=RegionDetailResponse)
async def region_detail(
    region_id: str,
    election_id: Optional[str] = Query(default=None, max_length=80),
):
    """Region detail panel data: measurements grouped by type, calendar events,
    coverage timeline and historical results."""
    detail = await engine.region_detail(region_id, election_id=election_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Unknown region {region_id!r}.")
    return detail


@router.get("/events", response_model=EventsResponse)
async def events(
    category: Optional[PoliticalCategory] = Query(default=None),
    jurisdiction: Optional[str] = Query(default=None, min_length=2, max_length=40),
    country: Optional[str] = Query(default=None, min_length=2, max_length=40),
    date_from: Optional[str] = Query(default=None, description="ISO date/datetime"),
    date_to: Optional[str] = Query(default=None, description="ISO date/datetime"),
    source_id: Optional[str] = Query(default=None, max_length=40),
    upcoming_only: bool = Query(default=False),
):
    """The sourced election/event calendar (FEC)."""
    return await engine.events_view(
        category=category,
        jurisdiction=jurisdiction,
        country=country,
        date_from=_parse_iso_date(date_from),
        date_to=_parse_iso_date(date_to),
        source_id=source_id,
        upcoming_only=upcoming_only,
    )


@router.get("/measurements", response_model=MeasurementsResponse)
async def measurements(
    region_id: Optional[str] = Query(default=None, max_length=40),
    election_id: Optional[str] = Query(default=None, max_length=80),
    measurement_type: Optional[MeasurementType] = Query(default=None),
    source_id: Optional[str] = Query(default=None, max_length=40),
    include_historical: bool = Query(default=True),
):
    """Sourced measurements, always separated by measurement type.

    POLL / FORECAST / MODEL / HISTORICAL_RESULT are returned in ``by_type``
    groups and are never merged into a single combined number.
    """
    return await engine.measurements_view(
        region_id=region_id,
        election_id=election_id,
        measurement_type=measurement_type,
        source_id=source_id,
        include_historical=include_historical,
    )


@router.get("/head-to-head", response_model=HeadToHeadResponse)
async def head_to_head(
    election_id: Optional[str] = Query(default=None, max_length=80),
    region_id: Optional[str] = Query(default=None, max_length=40),
):
    """Neutral side-by-side comparison of sourced measurements.

    Rows are ordered by source and measurement date — never by probability —
    and the response carries no winner, ranking or recommendation field.
    """
    result = await engine.head_to_head(election_id=election_id, region_id=region_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No sourced measurements exist for that election/region combination.",
        )
    return result


@router.get("/timeline", response_model=TimelineResponse)
async def timeline(
    hours: int = Query(default=72, ge=1, le=336),
    limit: int = Query(default=60, ge=1, le=200),
    category: Optional[PoliticalCategory] = Query(default=None),
    country: Optional[str] = Query(default=None, min_length=2, max_length=60),
    region_id: Optional[str] = Query(default=None, max_length=40),
):
    """Geopolitical coverage timeline (GDELT DOC 2.0), newest first."""
    return await engine.timeline_view(
        category=category,
        country=country,
        region_id=region_id,
        hours=hours,
        limit=limit,
    )


@router.get("/sources", response_model=SourcesResponse)
def sources():
    """Source registry: attribution, capabilities and honest health."""
    infos = engine.source_infos()
    return SourcesResponse(
        sources=infos,
        summary={
            "count": len(infos),
            "ok": sum(1 for s in infos if s.status.value == "OK"),
            "degraded": sum(1 for s in infos if s.status.value == "DEGRADED"),
            "unavailable": sum(1 for s in infos if s.status.value == "UNAVAILABLE"),
        },
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/meta", response_model=PoliticalMetaResponse)
def meta():
    """Self-describing metadata the UI renders legends/disclaimers from."""
    return engine.meta()


@router.get("/health", response_model=PoliticalHealthResponse)
def health():
    """Subsystem health: provider statuses and cache statistics."""
    return engine.health()


@router.post("/refresh")
async def refresh():
    """Force a provider re-fetch (bounded by provider-side rate limits)."""
    return await engine.refresh()
