"""
Phase 14/15 — forecast-analysis API routes (additive).

Everything here is new surface area; the original `/api/forecast/markets`,
`/api/forecast/markets/{id}` and `/api/forecast/categories` routes in `main.py`
are untouched and keep working.

Endpoints
    GET    /api/forecast/markets/{id}/history      real traded probability series
    POST   /api/forecast/markets/{id}/simulate     Monte-Carlo probability forecast
    POST   /api/forecast/combine                   correlation-adjusted combination
    POST   /api/forecast/correlate                 correlation report only
    GET    /api/forecast/combinations              list saved combinations
    POST   /api/forecast/combinations              create / update a combination
    GET    /api/forecast/combinations/{id}         one combination + snapshots
    DELETE /api/forecast/combinations/{id}         delete a combination
    POST   /api/forecast/combinations/{id}/snapshot   append a probability snapshot
    GET    /api/forecast/resolutions               settled markets

Design notes
    * Market data is fetched from the real public source; a market whose history
      is genuinely empty returns an empty list (the client shows "unavailable"),
      never a fabricated curve.
    * Combination endpoints accept histories inline *or* a marketId, in which
      case the server fetches the real history itself.
    * Persistence uses the Phase 3 repository, so it shares the app's single
      storage layer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import repository as repo
from .combination import combine_events, correlation_report
from .config import settings
from .forecast_history import fetch_market_history
from .forecast_markets import fetch_market_by_id, fetch_markets
from .forecast_resolutions import get_resolutions, lookup_resolution
from .forecast_simulation import simulate_probability
from .logging_config import get_logger

logger = get_logger("neural_market.forecast_routes")

router = APIRouter(prefix="/api/forecast", tags=["Forecast Analysis"])

_VALID_RANGES = {"1D", "7D", "1M", "MAX", "FULL"}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SimulationRequest(BaseModel):
    horizonDays: float = Field(default=30.0, gt=0.0, le=365.0)
    paths: Optional[int] = Field(default=None, ge=500, le=100000)
    model: str = Field(default="auto", pattern="^(auto|ou|gbm|ensemble)$")
    seed: Optional[int] = None


class CombinationEvent(BaseModel):
    id: Optional[str] = None
    marketId: Optional[str] = None
    label: Optional[str] = None
    outcome: str = Field(default="YES", pattern="^(YES|NO)$")
    probability: float = Field(..., ge=0.0, le=100.0)
    history: Optional[list[dict[str, Any]]] = None


class CombineRequest(BaseModel):
    events: list[CombinationEvent] = Field(..., min_length=1)
    draws: Optional[int] = Field(default=None, ge=1000, le=200000)
    deltaPp: Optional[float] = Field(default=None, ge=1.0, le=50.0)
    seed: Optional[int] = None
    includeSensitivity: bool = True


class CorrelateRequest(BaseModel):
    events: list[CombinationEvent] = Field(..., min_length=2)


class CombinationSaveRequest(BaseModel):
    id: Optional[str] = None
    name: str = Field(default="Untitled combination", max_length=200)
    userId: Optional[str] = None
    selections: list[dict[str, Any]] = Field(default_factory=list)
    combinedProbability: float = Field(default=0.0, ge=0.0, le=100.0)
    correlationAdjustedProbability: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    correlation: dict[str, Any] = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    combinedProbability: float = Field(..., ge=0.0, le=100.0)
    correlationAdjustedProbability: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    selections: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_market(market_id: str, cache: dict[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    """Market detail by id, with a per-request cache and a list fallback."""
    if market_id in cache:
        return cache[market_id]
    market: dict[str, Any] | None = None
    try:
        market = await fetch_market_by_id(market_id, settings.forecast_market_timeout_seconds)
    except Exception as exc:
        logger.debug("market lookup failed for %s: %s", market_id, exc)
    cache[market_id] = market
    return market


async def _market_or_list(market_id: str) -> dict[str, Any] | None:
    """Lookup that also falls back to scanning the active list (older markets)."""
    market = await _resolve_market(market_id, {})
    if market is not None:
        return market
    try:
        markets = await fetch_markets(settings.forecast_market_limit, settings.forecast_market_timeout_seconds)
    except Exception:
        return None
    return next((m for m in markets if m.get("id") == market_id), None)


async def _attach_history(events: list[CombinationEvent]) -> list[dict[str, Any]]:
    """Fill in each event's history from the real source when it is missing."""
    cache: dict[str, dict[str, Any] | None] = {}
    out: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        payload = event.model_dump()
        payload.setdefault("id", payload.get("id") or payload.get("marketId") or f"event-{index + 1}")
        history = payload.get("history")
        if (not history) and payload.get("marketId"):
            market = await _resolve_market(str(payload["marketId"]), cache)
            if market is not None:
                history_payload = await fetch_market_history(market, range_key="FULL")
                if history_payload and history_payload.get("points"):
                    history = history_payload["points"]
                if not payload.get("label"):
                    payload["label"] = market.get("title")
        payload["history"] = history or []
        out.append(payload)
    return out


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/markets/{market_id}/history")
async def forecast_market_history(
    market_id: str,
    range: str = Query(default="FULL"),
    fidelity: Optional[int] = Query(default=None, ge=1, le=1440),
):
    """Real traded probability series for one market (Phase 14.1)."""
    range_key = (range or "FULL").upper()
    if range_key not in _VALID_RANGES:
        raise HTTPException(400, f"range must be one of {sorted(_VALID_RANGES)}")

    market = await _market_or_list(market_id)
    if market is None:
        raise HTTPException(404, "Forecast market not found.")

    payload = await fetch_market_history(market, range_key=range_key, fidelity_override=fidelity)
    if payload is None:
        # Token id absent or source unreachable — an honest, empty answer with a
        # reason, not a fabricated curve.
        raise HTTPException(503, "Real probability history is unavailable for this market right now.")

    return payload


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

@router.post("/markets/{market_id}/simulate")
async def forecast_market_simulate(market_id: str, body: SimulationRequest):
    """Monte-Carlo probability forecast from the market's real traded history."""
    market = await _market_or_list(market_id)
    if market is None:
        raise HTTPException(404, "Forecast market not found.")

    history_payload = await fetch_market_history(market, range_key="FULL")
    if history_payload is None:
        raise HTTPException(503, "Real probability history is unavailable; a simulation cannot be estimated.")
    points = history_payload.get("points") or []
    if len(points) < 3:
        raise HTTPException(422, "Not enough real traded history to estimate a simulation for this market.")

    result = simulate_probability(
        history=points,
        current_probability=market.get("yesProbability"),
        horizon_days=body.horizonDays,
        paths=body.paths,
        model=body.model,
        seed=body.seed,
    )
    if result is None:
        raise HTTPException(422, "The available history is too short to estimate a simulation.")

    return {
        "marketId": market.get("id"),
        "title": market.get("title"),
        "dataMode": "SIMULATED",
        "historyPoints": len(points),
        "source": history_payload.get("source"),
        **result,
    }


# ---------------------------------------------------------------------------
# Combination analysis
# ---------------------------------------------------------------------------

@router.post("/combine")
async def forecast_combine(body: CombineRequest):
    """Correlation-adjusted combined probability + sensitivity (Phase 15)."""
    if len(body.events) > settings.combination_max_events:
        raise HTTPException(400, f"At most {settings.combination_max_events} events can be combined at once.")
    if len(body.events) < 2:
        raise HTTPException(400, "Provide at least two events to combine.")

    events = await _attach_history(body.events)
    try:
        result = combine_events(
            events,
            draws=body.draws,
            delta_pp=body.deltaPp,
            seed=body.seed,
            include_sensitivity=body.includeSensitivity,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result


@router.post("/correlate")
async def forecast_correlate(body: CorrelateRequest):
    """Empirical pairwise correlation report for the selected events."""
    if len(body.events) > settings.combination_max_events:
        raise HTTPException(400, f"At most {settings.combination_max_events} events can be analysed at once.")
    events = await _attach_history(body.events)
    return correlation_report(events)


# ---------------------------------------------------------------------------
# Persisted combinations
# ---------------------------------------------------------------------------

@router.get("/combinations")
async def list_combination_records(userId: Optional[str] = None):
    return {"combinations": repo.list_combinations(userId)}


@router.post("/combinations")
async def save_combination_record(body: CombinationSaveRequest):
    record = {
        "id": body.id or uuid.uuid4().hex,
        "user_id": body.userId,
        "name": body.name,
        "selections": body.selections,
        "combined_probability": body.combinedProbability,
        "correlation_adjusted_probability": body.correlationAdjustedProbability,
        "correlation": body.correlation,
    }
    try:
        return repo.upsert_combination(record)
    except Exception as exc:
        logger.error("failed to save combination: %s", exc)
        raise HTTPException(500, "Could not save the combination.")


@router.get("/combinations/{combination_id}")
async def get_combination_record(combination_id: str):
    record = repo.get_combination(combination_id)
    if record is None:
        raise HTTPException(404, "Combination not found.")
    record["snapshots"] = repo.list_combination_snapshots(combination_id)
    return record


@router.delete("/combinations/{combination_id}")
async def delete_combination_record(combination_id: str):
    if not repo.delete_combination(combination_id):
        raise HTTPException(404, "Combination not found.")
    return {"deleted": combination_id}


@router.post("/combinations/{combination_id}/snapshot")
async def snapshot_combination_record(combination_id: str, body: SnapshotRequest):
    if repo.get_combination(combination_id) is None:
        raise HTTPException(404, "Combination not found.")
    return repo.add_combination_snapshot(
        combination_id,
        body.combinedProbability,
        body.correlationAdjustedProbability,
        body.selections,
    )


@router.get("/combinations/{combination_id}/snapshots")
async def list_combination_record_snapshots(combination_id: str, limit: int = 200):
    return {"snapshots": repo.list_combination_snapshots(combination_id, limit)}


# ---------------------------------------------------------------------------
# Resolutions
# ---------------------------------------------------------------------------

@router.get("/resolutions")
async def forecast_resolutions(
    marketId: Optional[str] = None,
    resolvedOnly: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Settled markets (Phase 14.2). `marketId` returns just that market's record."""
    if marketId:
        record = await lookup_resolution(marketId)
        if record is None:
            raise HTTPException(404, "No settlement is available for that market.")
        return records_wrap([record])

    try:
        records = await get_resolutions(resolved_only=resolvedOnly)
    except Exception as exc:
        logger.warning("resolutions unavailable: %s", exc)
        raise HTTPException(503, "Settlement data is temporarily unavailable.")
    return records_wrap(records[:limit])


def records_wrap(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resolutions": records,
        "count": len(records),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
