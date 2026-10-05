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

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .service import macro_service
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
    """Get macro series data."""
    try:
        observations = macro_service.get_macro_series(series_id, limit=limit)
        return observations
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


@router.get("/health")
async def macro_health():
    """Health check for macro intelligence service."""
    try:
        banks = macro_service.list_central_banks()
        return {
            "status": "ok",
            "central_banks_configured": len(banks),
            "fred_api_key_configured": macro_service.fred_api_key is not None,
        }
    except Exception as e:
        logger.error("Macro health check failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
        }
