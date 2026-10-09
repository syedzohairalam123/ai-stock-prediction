"""
Phase 23A — API routes for Central Bank and Macroeconomic Intelligence Engine.

Endpoints:
- GET /api/v1/macro/central-banks - List central banks
- GET /api/v1/macro/central-banks/{bank_id} - Get central bank details
- GET /api/v1/macro/meetings - Get upcoming meetings
- GET /api/v1/macro/meetings/{bank_id} - Get meetings for specific bank
- GET /api/v1/macro/policy/{bank_id} - Get policy history
- GET /api/v1/macro/series/{series_id} - Get macro series data
- GET /api/v1/macro/series - List available series
- GET /api/v1/macro/analytics/policy/{bank_id} - Policy rate analytics
- GET /api/v1/macro/analytics/trend/{series_id} - Macro trend analytics
- POST /api/v1/macro/refresh/{bank_id} - Refresh data from source
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .service import macro_service, available_source_banks
from .analytics import (
    analyze_policy_rates,
    analyze_macro_trend,
    compare_historical_regimes,
    calculate_rate_change_correlation,
)

logger = logging.getLogger("neural_market.macro_intelligence.routes")

router = APIRouter(prefix="/api/v1/macro", tags=["Macro Intelligence"])


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class CentralBankResponse(BaseModel):
    id: str
    name: str
    country: str
    currency: str
    timezone: str
    source: str


class MeetingResponse(BaseModel):
    id: int
    central_bank_id: str
    scheduled_at: str
    timezone: str
    status: str
    meeting_type: str
    countdown: dict
    current_policy_rate: Optional[float] = None
    previous_decision: Optional[str] = None
    source_url: Optional[str] = None
    source_timestamp: Optional[str] = None


class PolicyDecisionResponse(BaseModel):
    id: int
    meeting_id: int
    previous_rate: float
    new_rate: float
    change_bps: int
    direction: str
    decision_timestamp: str
    source: str
    source_document: Optional[str] = None


class MacroSeriesResponse(BaseModel):
    id: int
    series_id: str
    observation_date: str
    release_date: str
    value: float
    unit: str
    frequency: str
    source: str
    data_freshness: str
    revision: int = 0
    previous_value: Optional[float] = None


class PolicyAnalyticsResponse(BaseModel):
    total_decisions: int
    hikes: int
    cuts: int
    unchanged: int
    avg_hike_bps: float
    avg_cut_bps: float
    max_hike_bps: int
    max_cut_bps: int
    current_rate: Optional[float] = None
    rate_range_min: Optional[float] = None
    rate_range_max: Optional[float] = None
    total_bps_change: int
    volatility_bps: float


class TrendAnalyticsResponse(BaseModel):
    series_id: str
    trend: str
    latest_value: float
    previous_value: float
    change_pct: float
    rolling_avg_3m: Optional[float] = None
    rolling_avg_6m: Optional[float] = None
    rolling_avg_12m: Optional[float] = None
    volatility: float
    momentum: float


# ---------------------------------------------------------------------------
# Central Bank Endpoints
# ---------------------------------------------------------------------------


@router.get("/central-banks", response_model=list[CentralBankResponse])
async def list_central_banks():
    """List all configured central banks."""
    try:
        banks = macro_service.list_central_banks()
        if not banks:
            # Initialize default banks if none exist
            macro_service.initialize_central_banks()
            banks = macro_service.list_central_banks()
        return banks
    except Exception as e:
        logger.error("Failed to list central banks: %s", e)
        raise HTTPException(500, str(e))


@router.get("/central-banks/supported")
async def list_supported_banks():
    """Ids the engine currently has a real source adapter for (spec §3).

    Declared before ``/central-banks/{bank_id}`` so the literal path wins the
    match. This is the extensibility surface: a new bank appears here the
    moment its adapter is registered — no engine change.
    """
    banks = available_source_banks()
    return {
        "supported_banks": banks,
        "count": len(banks),
        "note": (
            "Each listed bank has a registered real source adapter. Supporting "
            "ECB/BOE/BOC/RBA/SNB later is one adapter registration plus one "
            "catalogue entry; the fetch/normalise/store/API path is shared."
        ),
    }


@router.get("/central-banks/{bank_id}", response_model=CentralBankResponse)
async def get_central_bank(bank_id: str):
    """Get central bank details by ID."""
    try:
        bank = macro_service.get_central_bank(bank_id)
        if not bank:
            raise HTTPException(404, f"Central bank {bank_id} not found")
        return bank
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get central bank %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Policy Meeting Endpoints
# ---------------------------------------------------------------------------


@router.get("/meetings", response_model=list[MeetingResponse])
async def get_meetings(
    bank_id: Optional[str] = Query(None, description="Filter by central bank ID"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of meetings")
):
    """Get upcoming policy meetings with countdown."""
    try:
        meetings = macro_service.get_upcoming_meetings(bank_id=bank_id, limit=limit)
        return meetings
    except Exception as e:
        logger.error("Failed to get meetings: %s", e)
        raise HTTPException(500, str(e))


@router.get("/upcoming", response_model=list[MeetingResponse])
async def get_upcoming(
    bank_id: Optional[str] = Query(None, description="Optional central bank filter"),
    limit: int = Query(10, ge=1, le=50),
):
    """Alias for the upcoming-meeting view (spec §15).

    Same payload as ``/meetings`` so a consumer written against the spec's
    route list works unchanged; the data path is shared, not duplicated.
    """
    try:
        return macro_service.get_upcoming_meetings(bank_id=bank_id, limit=limit)
    except Exception as e:
        logger.error("Failed to get upcoming meetings: %s", e)
        raise HTTPException(500, str(e))


@router.get("/meetings/{bank_id}", response_model=list[MeetingResponse])
async def get_bank_meetings(
    bank_id: str,
    limit: int = Query(10, ge=1, le=50)
):
    """Get upcoming meetings for a specific central bank."""
    try:
        meetings = macro_service.get_upcoming_meetings(bank_id=bank_id, limit=limit)
        return meetings
    except Exception as e:
        logger.error("Failed to get meetings for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.post("/meetings/refresh/{bank_id}")
async def refresh_meetings(
    bank_id: str,
    limit: int = Query(20, ge=1, le=100)
):
    """Refresh meetings from official source."""
    try:
        meetings = macro_service.fetch_and_store_meetings(bank_id, limit=limit)
        return {
            "bank_id": bank_id,
            "meetings_fetched": len(meetings),
            "meetings": meetings,
        }
    except Exception as e:
        logger.error("Failed to refresh meetings for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Policy Decision Endpoints
# ---------------------------------------------------------------------------


@router.get("/policy/{bank_id}", response_model=list[PolicyDecisionResponse])
async def get_policy_history(
    bank_id: str,
    limit: int = Query(50, ge=1, le=200)
):
    """Get historical policy rate decisions for a central bank."""
    try:
        decisions = macro_service.get_policy_history(bank_id, limit=limit)
        return decisions
    except Exception as e:
        logger.error("Failed to get policy history for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.post("/policy/refresh/{bank_id}")
async def refresh_policy_decisions(
    bank_id: str,
    limit: int = Query(50, ge=1, le=200)
):
    """Refresh policy decisions from official source."""
    try:
        decisions = macro_service.fetch_and_store_decisions(bank_id, limit=limit)
        return {
            "bank_id": bank_id,
            "decisions_fetched": len(decisions),
            "decisions": decisions,
        }
    except Exception as e:
        logger.error("Failed to refresh policy decisions for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Macro Series Endpoints
# ---------------------------------------------------------------------------


@router.get("/series")
async def list_series():
    """List available macro series."""
    try:
        series = macro_service.get_available_series()
        return {"series": series}
    except Exception as e:
        logger.error("Failed to list series: %s", e)
        raise HTTPException(500, str(e))


@router.get("/series/{series_id}", response_model=list[MacroSeriesResponse])
async def get_macro_series(
    series_id: str,
    limit: int = Query(500, ge=1, le=5000)
):
    """Get macro series data.

    An id that is neither a curated series nor has any stored observations is
    reported as 404 (spec §19: invalid series) rather than a 200 empty list
    that would look like "no data" for a series that does not exist.
    """
    try:
        observations = macro_service.get_macro_series(series_id, limit=limit)
        if not observations and not macro_service.is_known_series(series_id):
            raise HTTPException(
                404,
                f"Unknown macro series '{series_id}'. Use GET /api/v1/macro/series "
                "for the available series ids.",
            )
        return observations
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get series %s: %s", series_id, e)
        raise HTTPException(500, str(e))


@router.post("/series/refresh/{series_id}")
async def refresh_macro_series(
    series_id: str,
    limit: int = Query(1000, ge=1, le=10000)
):
    """Refresh macro series from FRED."""
    try:
        observations = macro_service.fetch_and_store_macro_series(series_id, limit=limit)
        return {
            "series_id": series_id,
            "observations_fetched": len(observations),
            "observations": observations,
        }
    except Exception as e:
        logger.error("Failed to refresh series %s: %s", series_id, e)
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Analytics Endpoints
# ---------------------------------------------------------------------------


@router.get("/analytics/policy/{bank_id}", response_model=PolicyAnalyticsResponse)
async def get_policy_analytics(bank_id: str):
    """Get policy rate analytics for a central bank."""
    try:
        decisions = macro_service.get_policy_history(bank_id, limit=200)
        analytics = analyze_policy_rates(decisions)
        return analytics
    except Exception as e:
        logger.error("Failed to get policy analytics for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.get("/analytics/trend/{series_id}", response_model=TrendAnalyticsResponse)
async def get_trend_analytics(
    series_id: str,
    window_3m: int = Query(90, ge=30, le=180),
    window_6m: int = Query(180, ge=90, le=365),
    window_12m: int = Query(360, ge=180, le=730)
):
    """Get macro trend analytics for a series."""
    try:
        observations = macro_service.get_macro_series(series_id, limit=1000)
        analytics = analyze_macro_trend(
            observations,
            series_id=series_id,
            window_3m=window_3m,
            window_6m=window_6m,
            window_12m=window_12m,
        )
        return analytics
    except Exception as e:
        logger.error("Failed to get trend analytics for %s: %s", series_id, e)
        raise HTTPException(500, str(e))


@router.get("/analytics/regime/{bank_id}")
async def get_regime_comparison(bank_id: str):
    """Compare historical macro regimes."""
    try:
        decisions = macro_service.get_policy_history(bank_id, limit=200)

        # Get macro data for comparison
        macro_data = {}
        for series_info in macro_service.get_available_series():
            series_id = series_info["series_id"]
            observations = macro_service.get_macro_series(series_id, limit=500)
            if observations:
                macro_data[series_id] = observations

        comparison = compare_historical_regimes(decisions, macro_data)
        return comparison
    except Exception as e:
        logger.error("Failed to get regime comparison for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.get("/expectations/{bank_id}")
async def get_expectations(
    bank_id: str,
    limit: int = Query(50, ge=1, le=500),
):
    """
    Stored, sourced expectation snapshots (spec §7).

    Each row is what a named source implied at a named timestamp, kept so the
    change in expectations over time is visible. When no configured source
    publishes machine-readable probabilities the response says
    ``Market-implied expectations unavailable.`` rather than inventing one —
    market expectations are never presented as the central bank's decision.
    """
    try:
        return macro_service.get_expectation_history(bank_id, limit=limit)
    except Exception as e:
        logger.error("Failed to load expectation history for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.post("/expectations/refresh/{bank_id}")
async def refresh_expectations(
    bank_id: str,
    meeting_id: Optional[int] = Query(None, ge=1),
):
    """Pull real market-implied expectations from a live prediction market.

    The sourced snapshot comes from Polymarket's public API. When no open
    market is reachable the response states
    ``Market-implied expectations unavailable.`` rather than inventing a
    number (spec §2, §7).
    """
    try:
        stored = await macro_service.refresh_sourced_expectations(
            bank_id, meeting_id=meeting_id
        )
        if not stored:
            # Fall back to any adapter the bank itself implements.
            stored = macro_service.fetch_and_store_expectations(
                bank_id, meeting_id=meeting_id
            )
    except Exception as e:
        logger.error("Failed to refresh expectations for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))
    if not stored:
        return {
            "central_bank_id": bank_id,
            "stored": 0,
            "status": "UNAVAILABLE",
            "statement": "Market-implied expectations unavailable.",
            "note": (
                "No open market-implied expectation source is reachable for this bank "
                "right now; nothing was fabricated (spec §2)."
            ),
        }
    return {
        "central_bank_id": bank_id,
        "stored": len(stored),
        "status": "LIVE",
        "snapshots": stored,
    }


@router.get("/event-window/{bank_id}")
async def get_event_window(
    bank_id: str,
    ticker: str = Query("^GSPC", max_length=20),
    lookback_decisions: int = Query(4, ge=1, le=10),
    windows: str = Query("1,3,5,10,20", max_length=60),
):
    """
    Market observations around completed policy meetings (spec §10).

    Windows are validated server-side and the market leg comes from the same
    real provider path as every other chart. Results are historical
    observations — the API never claims causation.
    """
    parsed: list[int] = []
    for part in windows.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            raise HTTPException(400, f"Invalid window '{part}' — integers only.")
        if value < 1 or value > 60:
            raise HTTPException(400, "Windows must be between 1 and 60 days.")
        parsed.append(value)
    if not parsed:
        raise HTTPException(400, "At least one window is required.")

    try:
        return await macro_service.event_window_analysis(
            bank_id,
            ticker=ticker.strip().upper(),
            lookback_decisions=lookback_decisions,
            windows=parsed,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed event-window analysis for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.get("/indicators")
async def get_indicators(
    keys: Optional[str] = Query(
        None,
        max_length=400,
        description="Comma-separated indicator keys; defaults to the curated set",
    ),
):
    """Latest verified observation per curated macro indicator (spec §8)."""
    parsed = None
    if keys:
        parsed = [key.strip() for key in keys.split(",") if key.strip()]
    try:
        indicators = macro_service.get_macro_indicators(parsed)
        return {"indicators": indicators, "count": len(indicators)}
    except Exception as e:
        logger.error("Failed to load macro indicators: %s", e)
        raise HTTPException(500, str(e))


@router.get("/policy-range/{bank_id}")
async def get_policy_rate_range(bank_id: str):
    """Latest verified policy setting, both range bounds labelled (spec §4)."""
    try:
        return macro_service.get_policy_rate_range(bank_id)
    except Exception as e:
        logger.error("Failed to get policy range for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))


@router.post("/refresh/{bank_id}")
async def refresh_all(bank_id: str, series_limit: int = Query(120, ge=10, le=500)):
    """Refresh meetings, decisions, indicators and expectations for one bank.

    The blocking source fetches run in a worker thread so the event loop keeps
    serving other requests during a refresh.
    """
    try:
        result = await asyncio.to_thread(
            macro_service.refresh_all, bank_id, series_limit
        )
    except Exception as e:
        logger.error("Failed to refresh macro data for %s: %s", bank_id, e)
        raise HTTPException(500, str(e))
    try:
        snapshots = await macro_service.refresh_sourced_expectations(bank_id)
    except Exception as e:
        logger.warning("Expectations refresh failed for %s: %s", bank_id, e)
        snapshots = []
    result["expectation_snapshots_stored"] = len(snapshots)
    return result


@router.get("/health")
async def macro_health():
    """Health check for macro intelligence service."""
    try:
        banks = macro_service.list_central_banks()
        return {
            "status": "ok",
            "central_banks_configured": len(banks),
            "registered_source_banks": available_source_banks(),
            "fred_api_key_configured": macro_service.fred_api_key is not None,
        }
    except Exception as e:
        logger.error("Macro health check failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
        }
