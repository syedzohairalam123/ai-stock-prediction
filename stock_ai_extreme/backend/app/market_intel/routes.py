"""Phase 23B — API routes for Market Direction & Corporate Market-Cap Intelligence.

Endpoints (all additive; nothing existing is changed):

- GET  /api/v1/market-intel/instruments            - supported instruments
- GET  /api/v1/market-intel/dashboard              - SPX + SPY cards
- GET  /api/v1/market-intel/{instrument}/quote     - latest available session
- GET  /api/v1/market-intel/{instrument}/history   - priced observation series
- GET  /api/v1/market-intel/{instrument}/direction - UP/DOWN/FLAT history
- GET  /api/v1/market-intel/{instrument}/statistics- historical stats
- GET  /api/v1/market-intel/{instrument}/rolling   - rolling return/volatility
- GET  /api/v1/market-intel/comparison             - SPX vs SPY alignment
- GET  /api/v1/market-intel/leaderboard            - dynamic market-cap ranking
- GET  /api/v1/market-intel/companies              - company security mappings
- GET  /api/v1/market-intel/company/{id}/history   - stored cap history
- GET  /api/v1/market-intel/company/{id}/snapshots - materialised cap snapshots
- GET  /api/v1/market-intel/company/{id}/mappings  - listed securities for one company
- GET  /api/v1/market-intel/company/{id}/shares    - share-count observations
- GET  /api/v1/market-intel/company/{id}/scenario  - hypothetical scenario
- GET  /api/v1/market-intel/race                   - descriptive cap race
- GET  /api/v1/market-intel/rank-history           - cross-company rank timeline
- POST /api/v1/market-intel/corporate-actions/refresh/{id} - ingest real splits
- GET  /api/v1/market-intel/events/{bank_id}       - policy event study
- GET  /api/v1/market-intel/health                 - configuration health
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .service import DEFAULT_HISTORY_DAYS, market_intel_service

logger = logging.getLogger("neural_market.market_intel.routes")

router = APIRouter(prefix="/api/v1/market-intel", tags=["Market Intelligence"])

#: Route order matters: the literal segments below are declared BEFORE the
#: ``/{instrument}`` routes so /dashboard or /leaderboard never resolve as an
#: instrument name.


@router.get("/instruments")
async def list_instruments():
    """The instruments this engine can serve (SPX index, SPY ETF)."""
    return {"instruments": market_intel_service.instruments()}


@router.get("/health")
async def health():
    return market_intel_service.health()


@router.get("/dashboard")
async def dashboard(days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825)):
    """Separate SPX and SPY cards, each labelled with its session and source."""
    return await market_intel_service.get_dashboard(days=days)


@router.get("/comparison")
async def comparison(
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825),
    limit: int | None = Query(None, ge=1, le=5000),
):
    """Session-aligned SPX vs SPY comparison (missing sessions stay null)."""
    return await market_intel_service.get_comparison(days=days, limit=limit)


@router.get("/leaderboard")
async def leaderboard(
    limit: int | None = Query(None, ge=1, le=100),
    refresh: bool = Query(True),
):
    """Dynamic market-cap leaderboard computed from real observations."""
    return await market_intel_service.get_leaderboard(limit=limit, refresh=refresh)


@router.get("/race")
async def race(period_days: int = Query(180, ge=1, le=3650)):
    """Descriptive market-cap comparison over a period (no forecasts)."""
    return await market_intel_service.get_race(period_days=period_days)


@router.get("/rank-history")
async def rank_history(limit: int = Query(500, ge=1, le=5000)):
    """Stored rank snapshots across companies for a ranking timeline (spec §14)."""
    return market_intel_service.get_rank_history(limit=limit)


@router.get("/companies")
async def company_mappings(company_id: str | None = Query(None)):
    """Listed securities per company from ``company_security_mappings`` (spec §15)."""
    try:
        return market_intel_service.get_security_mappings(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/{company_id}/history")
async def company_history(
    company_id: str,
    limit: int = Query(365, ge=1, le=5000),
    offset: int = Query(0, ge=0, le=100000),
):
    """Stored market-cap observations for one company (real rows only)."""
    try:
        return market_intel_service.get_company_history(company_id, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/{company_id}/snapshots")
async def company_snapshots(
    company_id: str,
    limit: int = Query(365, ge=1, le=5000),
):
    """Materialised market-cap snapshots with their frozen inputs (spec §15)."""
    try:
        return market_intel_service.get_market_cap_snapshots(company_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/{company_id}/mappings")
async def company_mappings_one(company_id: str):
    """Listed securities for one company."""
    try:
        return market_intel_service.get_security_mappings(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/{company_id}/shares")
async def company_shares(
    company_id: str,
    limit: int = Query(365, ge=1, le=5000),
):
    """Append-only share-count observations with their own as-of date (spec §15)."""
    try:
        return market_intel_service.get_shares_outstanding(company_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/corporate-actions/refresh/{company_id}")
async def refresh_corporate_actions(company_id: str):
    """Ingest provider-reported stock splits as real corporate actions (spec §10)."""
    try:
        return await market_intel_service.refresh_corporate_actions(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/company/{company_id}/scenario")
async def company_scenario(
    company_id: str,
    return_pct: float = Query(..., ge=-99.0, le=1000.0, description="Scenario price change in percent"),
):
    """Hypothetical scenario calculator (arithmetic, not a prediction)."""
    try:
        result = await market_intel_service.get_scenario(company_id, return_pct / 100.0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["scenario_return_pct"] = return_pct
    return result


@router.get("/company/{company_id}/corporate-actions")
async def company_corporate_actions(
    company_id: str,
    limit: int = Query(100, ge=1, le=1000),
):
    """Source-reported corporate actions that affect cap comparability."""
    try:
        return market_intel_service.get_corporate_actions(company_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class CorporateActionRequest(BaseModel):
    company_id: str
    action_type: str = Field(..., description="SPLIT | BUYBACK | ISSUANCE | OTHER")
    effective_date: str
    ratio: float | None = None
    source: str | None = None
    notes: str | None = None


@router.post("/corporate-actions")
async def record_corporate_action(body: CorporateActionRequest):
    """Record a corporate action from a named source (idempotent)."""
    try:
        return market_intel_service.record_corporate_action(
            body.company_id,
            body.action_type,
            body.effective_date,
            ratio=body.ratio,
            source=body.source,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/events/{bank_id}")
async def event_study(
    bank_id: str,
    instrument: str = Query("spx", description="spx | spy"),
    lookback_decisions: int = Query(4, ge=1, le=40),
):
    """Observational SPX/SPY study around Phase 23A policy decisions."""
    try:
        return await market_intel_service.get_event_study(
            bank_id.upper(),
            instrument_key=instrument,
            lookback_decisions=lookback_decisions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{instrument}/quote")
async def instrument_quote(
    instrument: str,
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825),
):
    """Latest available trading-session close (explicitly not a live quote)."""
    try:
        payload = await market_intel_service.get_instrument(instrument, days=days, limit=1)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "instrument": payload["instrument"],
        "latest": payload["latest"],
        "source": payload["source"],
        "data_status": payload["data_status"],
        "error": payload["error"],
    }


@router.get("/{instrument}/history")
async def instrument_history(
    instrument: str,
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825),
    limit: int | None = Query(None, ge=1, le=5000),
    offset: int = Query(0, ge=0, le=100000),
):
    """Priced observation series for SPX or SPY."""
    try:
        return await market_intel_service.get_instrument(
            instrument, days=days, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{instrument}/direction")
async def instrument_direction(
    instrument: str,
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825),
    limit: int | None = Query(None, ge=1, le=5000),
    offset: int = Query(0, ge=0, le=100000),
):
    """UP/DOWN/FLAT history computed from consecutive real sessions."""
    try:
        return await market_intel_service.get_direction_history(
            instrument, days=days, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{instrument}/statistics")
async def instrument_statistics(
    instrument: str,
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825),
):
    """Historical direction statistics with period and sample size."""
    try:
        return await market_intel_service.get_statistics(instrument, days=days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{instrument}/rolling")
async def instrument_rolling(
    instrument: str,
    days: int = Query(DEFAULT_HISTORY_DAYS, ge=30, le=1825),
    window: int = Query(20, ge=2, le=252),
):
    """Rolling return and annualised volatility."""
    try:
        return await market_intel_service.get_rolling(
            instrument, days=days, window=window
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
