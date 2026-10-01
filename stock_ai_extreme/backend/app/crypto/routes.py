"""
Versioned crypto API (spec §60, §61, §91, §92, §93).

Every endpoint returns the uniform envelope (``data`` / ``meta`` / ``requestId``
/ ``errors``) and validates its inputs server-side — a client's symbol,
timeframe, price, date or horizon is never trusted, and a rejected input
produces a 4xx rather than being coerced into something plausible.

A dedicated per-IP limiter covers this surface (spec §92) while the shared,
server-side provider stream stays connection-bounded (spec §9): the limit is on
*browser requests*, not on upstream provider calls.

Routes are mounted at ``/api/v1/crypto``; ``app.main`` also mounts the same
router at ``/api/crypto`` so existing tooling that does not speak v1 still works.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.crypto import repositories as repo
from app.crypto import targets as targets_mod
from app.crypto.config import crypto_settings
from app.crypto.providers.base import ProviderError
from app.crypto.schemas import DataStatus, QualityLabel
from app.crypto.services.service import CryptoService, crypto_service, envelope
from app.crypto.symbols import SymbolError
from app.crypto.timeframes import TimeframeError
from app.security import RateLimiter

logger = logging.getLogger("neural_market.crypto.routes")

#: Paths are relative so the router can be mounted at both `/api/v1/crypto` and
#: the legacy `/api/crypto` alias without duplicating a single route definition.
router = APIRouter(tags=["crypto"])
ws_router = APIRouter(tags=["crypto-ws"])

#: Per-IP limiter for the crypto REST surface (spec §92).
_crypto_limiter = RateLimiter(
    max_requests=crypto_settings.rate_limit_max_requests,
    window_seconds=crypto_settings.rate_limit_window_seconds,
)


def _client_key(request: Request) -> str:
    return f"crypto:{request.client.host if request.client else 'unknown'}"


def _check_limit(request: Request) -> None:
    allowed, _remaining = _crypto_limiter.allow(_client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Crypto API rate limit exceeded "
                f"({crypto_settings.rate_limit_max_requests}/{crypto_settings.rate_limit_window_seconds}s)."
            ),
        )


def _service() -> CryptoService:
    return crypto_service


def _resolve(symbol: str) -> str:
    try:
        return _service().manager.resolve(symbol).internal
    except SymbolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _timeframe(timeframe: Optional[str]) -> str:
    from app.crypto.timeframes import get_timeframe

    try:
        return get_timeframe(timeframe).id
    except TimeframeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# reference data
# ---------------------------------------------------------------------------
@router.get("/assets")
async def get_assets(request: Request) -> Dict[str, Any]:
    """The curated catalogue with per-provider symbol mappings."""
    _check_limit(request)
    payload = _service().assets()
    return envelope(payload, source="catalogue", data_status=DataStatus.LIVE, quality=QualityLabel.HIGH)


@router.get("/timeframes")
async def get_timeframes(request: Request) -> Dict[str, Any]:
    """Supported timeframes and their provider capability report (spec §3, §4)."""
    _check_limit(request)
    payload = _service().timeframes()
    return envelope(payload, source="registry", data_status=DataStatus.LIVE)


@router.get("/sources")
async def get_sources(request: Request) -> Dict[str, Any]:
    """Configured providers, real health and per-provider stats (spec §53, §105)."""
    _check_limit(request)
    payload = await _service().sources()
    return envelope(payload, source="providers", data_status=DataStatus.LIVE)


@router.get("/categories")
async def get_categories(request: Request) -> Dict[str, Any]:
    """Discovery sub-categories (spec §41, §46)."""
    _check_limit(request)
    payload = {"categories": _service().categories(), "currency": _service().currency_pairs()}
    return envelope(payload, source="internal", data_status=DataStatus.LIVE)


@router.get("/categories/pre-session")
async def get_pre_session(request: Request) -> Dict[str, Any]:
    """Pre-session / upcoming-event intelligence with honest 24/7 framing (§42)."""
    _check_limit(request)
    payload = await _service().pre_session()
    return envelope(
        payload,
        source=payload.get("trending_source") or "internal",
        data_status=DataStatus(str(payload.get("trending_status") or DataStatus.UNAVAILABLE.value)),
    )


@router.get("/categories/institutions/{symbol}")
async def get_institutions(symbol: str, request: Request) -> Dict[str, Any]:
    """Publicly disclosed holdings with attribution and coverage (spec §43)."""
    _check_limit(request)
    internal = _resolve(symbol)
    payload = await _service().institutions(internal)
    return envelope(
        payload,
        source=(payload.get("disclosed_holdings") or {}).get("source"),
        data_status=DataStatus(str(payload.get("status") or DataStatus.UNAVAILABLE.value)),
    )


@router.get("/categories/industry")
async def get_industry(request: Request) -> Dict[str, Any]:
    """Documented internal taxonomy + provider category metadata (spec §45)."""
    _check_limit(request)
    payload = await _service().industry()
    return envelope(
        payload,
        source="taxonomy",
        data_status=DataStatus(
            str(payload.get("source_categories_status") or DataStatus.UNAVAILABLE.value)
        ),
    )


# ---------------------------------------------------------------------------
# market data
# ---------------------------------------------------------------------------
@router.get("/quote/{symbol}")
async def get_quote(symbol: str, request: Request) -> Dict[str, Any]:
    _check_limit(request)
    internal = _resolve(symbol)
    payload = await _service().market.quote(internal)
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=DataStatus(str(payload.get("status") or DataStatus.UNAVAILABLE.value)),
        age_ms=payload.get("age_ms"),
    )


@router.get("/candles/{symbol}")
async def get_candles(
    symbol: str,
    request: Request,
    timeframe: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=10, le=5000),
    display_points: Optional[int] = Query(None, ge=50, le=2000),
    raw: bool = Query(False),
) -> Dict[str, Any]:
    """Real OHLCV with server-side range control and extrema-preserving downsampling."""
    _check_limit(request)
    internal = _resolve(symbol)
    timeframe_id = _timeframe(timeframe)
    payload = await _service().market.candles(
        internal, timeframe_id, limit=limit, display_points=display_points, raw=raw
    )
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=DataStatus(str(payload.get("data_status") or DataStatus.UNAVAILABLE.value)),
        quality=QualityLabel(payload["quality"]["label"]),
        timeframe=payload["timeframe"],
        notes=payload.get("notes"),
    )


@router.get("/analytics/{symbol}")
async def get_analytics(
    symbol: str,
    request: Request,
    timeframe: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=20, le=5000),
) -> Dict[str, Any]:
    """Indicators + volatility + micro-trend, all labelled with their origin."""
    _check_limit(request)
    internal = _resolve(symbol)
    timeframe_id = _timeframe(timeframe)
    payload = await _service().market.analytics(internal, timeframe_id, limit=limit)
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=DataStatus(str(payload.get("data_status") or DataStatus.UNAVAILABLE.value)),
        quality=QualityLabel(payload["quality"]["label"]),
        timeframe=payload["timeframe"],
    )


@router.get("/multi-timeframe/{symbol}")
async def get_multi_timeframe(symbol: str, request: Request) -> Dict[str, Any]:
    """Timeframe comparison, computed per dataset and never collapsed (spec §17, §18, §73)."""
    _check_limit(request)
    internal = _resolve(symbol)
    payload = await _service().market.multi_timeframe(internal)
    return envelope(payload, source="computed", data_status=DataStatus.LIVE, notes=[payload["note"]])


# ---------------------------------------------------------------------------
# forecasting
# ---------------------------------------------------------------------------
@router.get("/forecast/{symbol}")
async def get_forecast(
    symbol: str,
    request: Request,
    timeframe: Optional[str] = Query(None),
    horizon: Optional[int] = Query(None, ge=1, le=60),
    persist: bool = Query(False),
) -> Dict[str, Any]:
    """
    A versioned MODELLED FORECAST with its validation evidence (spec §20–§29, §69, §83).

    ``persist=true`` stores the forecast so it can later be scored against the
    outcome that actually happened.
    """
    _check_limit(request)
    internal = _resolve(symbol)
    timeframe_id = _timeframe(timeframe)
    payload = await _service().forecast.get(internal, timeframe_id, horizon=horizon, persist=persist)
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=DataStatus(str(payload.get("status") or DataStatus.UNAVAILABLE.value)),
        quality=QualityLabel(str(payload.get("quality") or "UNAVAILABLE")),
        timeframe=payload.get("timeframe"),
        notes=payload.get("limitations"),
        errors=[payload["reason"]] if payload.get("reason") else None,
    )


@router.get("/forecast/{symbol}/history")
async def get_forecast_history(
    symbol: str,
    request: Request,
    timeframe: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Stored forecasts, append-only (spec §30)."""
    _check_limit(request)
    internal = _resolve(symbol)
    payload = _service().forecast.history(internal, timeframe=timeframe, limit=limit)
    return envelope(payload, source="database", data_status=DataStatus.HISTORICAL)


@router.get("/forecast/{symbol}/drift")
async def get_forecast_drift(
    symbol: str, request: Request, timeframe: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Feature-distribution drift (PSI + KS) for the selected timeframe (spec §77, §78)."""
    _check_limit(request)
    internal = _resolve(symbol)
    timeframe_id = _timeframe(timeframe)
    payload = await _service().forecast.drift(internal, timeframe_id)
    return envelope(
        payload,
        source="computed",
        data_status=DataStatus.HISTORICAL if payload.get("status") != "UNKNOWN" else DataStatus.UNAVAILABLE,
        notes=[payload.get("note") or payload.get("reason") or ""],
    )


@router.get("/forecast-performance")
async def get_forecast_performance(
    request: Request, symbol: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Realised forecast accuracy from stored evaluations (spec §31, §80)."""
    _check_limit(request)
    payload = _service().forecast.performance(symbol)
    return envelope(payload, source="database", data_status=DataStatus.HISTORICAL)


# ---------------------------------------------------------------------------
# targets / thresholds
# ---------------------------------------------------------------------------
class TargetCreateRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    target_price: float = Field(..., gt=0)
    direction: str = Field("above", pattern="^(above|below)$")
    target_date: Optional[str] = Field(None, max_length=40)
    notes: Optional[str] = Field(None, max_length=500)


@router.get("/targets/{symbol}")
async def get_targets(
    symbol: str,
    request: Request,
    include_derived: bool = Query(True),
    lookback_days: Optional[int] = Query(None, ge=7, le=1825),
) -> Dict[str, Any]:
    """Evaluated targets + the derived real-price reference ladder (spec §37, §44, §70, §72)."""
    _check_limit(request)
    internal = _resolve(symbol)
    payload = await _service().targets.list_for_symbol(
        internal, include_derived=include_derived, lookback_days=lookback_days
    )
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=DataStatus(str(payload.get("data_status") or DataStatus.UNAVAILABLE.value)),
    )


@router.get("/targets/{symbol}/history")
async def get_target_history(symbol: str, request: Request) -> Dict[str, Any]:
    """Timeline of real observations that changed this symbol's targets (spec §40)."""
    _check_limit(request)
    internal = _resolve(symbol)
    rows = repo.list_targets(symbol=internal)
    events: List[Dict[str, Any]] = []
    for row in rows:
        events.extend(repo.target_events(row["id"]))
    events.sort(key=lambda item: item.get("observed_at") or "", reverse=True)
    return envelope(
        {
            "symbol": internal,
            "target_count": len(rows),
            "event_count": len(events),
            "events": events,
            "note": (
                "Every entry is a real observation (a candle that touched the level, a due date "
                "that elapsed or an explicit invalidation). No target state is set by a click."
            ),
        },
        source="database",
        data_status=DataStatus.HISTORICAL,
    )


@router.get("/targets/{symbol}/ladder")
async def get_ladder(
    symbol: str, request: Request, count: Optional[int] = Query(None, ge=1, le=10)
) -> Dict[str, Any]:
    """Reference ladder from real historical swing highs/lows (spec §37)."""
    _check_limit(request)
    internal = _resolve(symbol)
    payload = await _service().targets.reference_ladder(internal, count=count)
    return envelope(payload, source=payload.get("source"), data_status=DataStatus.LIVE)


class TargetInvalidateRequest(BaseModel):
    target_id: str = Field(..., min_length=1, max_length=64)


@router.post("/targets")
async def create_target(payload: TargetCreateRequest, request: Request) -> Dict[str, Any]:
    """Create an analytical milestone and evaluate it immediately against real candles."""
    _check_limit(request)
    try:
        result = await _service().targets.create(
            symbol=payload.symbol,
            target_price=payload.target_price,
            direction=payload.direction,
            target_date=payload.target_date,
            notes=payload.notes,
        )
    except targets_mod.TargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SymbolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.get("status") == "REJECTED":
        raise HTTPException(status_code=409, detail=result.get("reason"))
    return envelope(result, source=result.get("source"), data_status=DataStatus.LIVE)


@router.post("/targets/invalidate")
async def invalidate_target(payload: TargetInvalidateRequest, request: Request) -> Dict[str, Any]:
    """Explicitly retire a target — the only status a client may set directly."""
    _check_limit(request)
    result = await _service().targets.invalidate(payload.target_id)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="target not found")
    return envelope(result, source="user", data_status=DataStatus.LIVE)


@router.get("/threshold/{symbol}")
async def get_threshold(
    symbol: str,
    request: Request,
    threshold: float = Query(..., gt=0),
    timeframe: Optional[str] = Query(None),
    horizon: Optional[int] = Query(None, ge=1, le=60),
    direction: str = Query("above", pattern="^(above|below)$"),
) -> Dict[str, Any]:
    """
    MODELLED PROBABILITY of the asset being above/below a level (spec §36, §71, §81).

    Reported with both estimates, their calibration (Brier score + reliability
    table) and the model/data source. Never presented as a guarantee.
    """
    _check_limit(request)
    internal = _resolve(symbol)
    timeframe_id = _timeframe(timeframe)
    payload = await _service().targets.threshold(
        symbol=internal, timeframe_id=timeframe_id, threshold=threshold, horizon=horizon, direction=direction
    )
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=DataStatus(str(payload.get("status") or DataStatus.UNAVAILABLE.value)),
        timeframe=payload.get("timeframe"),
        notes=[payload.get("note") or payload.get("reason") or ""],
    )


@router.get("/on-date/{symbol}")
async def get_on_date(
    symbol: str,
    request: Request,
    date: str = Query(..., min_length=4, max_length=40),
    threshold: Optional[float] = Query(None, gt=0),
    direction: str = Query("above", pattern="^(above|below)$"),
) -> Dict[str, Any]:
    """Factual historical query: "what did price do / was it above X on date Y?" (spec §35)."""
    _check_limit(request)
    internal = _resolve(symbol)
    try:
        payload = await _service().targets.on_date(
            symbol=internal, date=date, threshold=threshold, direction=direction
        )
    except targets_mod.TargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return envelope(
        payload,
        source=payload.get("source"),
        data_status=(
            DataStatus.HISTORICAL if payload.get("status") in ("OBSERVED", "ANSWERED") else DataStatus.UNAVAILABLE
        ),
    )


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------
@router.get("/health")
async def get_health(request: Request) -> Dict[str, Any]:
    """Liveness + per-provider availability (spec §105). Ops-only: no upstream probe."""
    _check_limit(request)
    payload = await _service().health()
    return envelope(payload, source="internal", data_status=DataStatus.LIVE)


@router.get("/health/probe")
async def probe_health(request: Request) -> Dict[str, Any]:
    """Issue real provider probes and record them (spec §104, §105)."""
    _check_limit(request)
    payload = await _service().probe_health()
    available = sum(1 for entry in payload if entry["available"])
    return envelope(
        {"providers": payload, "available": available, "count": len(payload)},
        source="providers",
        data_status=DataStatus.LIVE,
    )


@router.get("/observability")
async def get_observability(request: Request) -> Dict[str, Any]:
    """Cache, provider and configuration snapshot for the ops panel (spec §104)."""
    _check_limit(request)
    payload = _service().observability()
    return envelope(payload, source="internal", data_status=DataStatus.LIVE)


@router.get("/persistence")
async def get_persistence(request: Request) -> Dict[str, Any]:
    """Row counts of what has genuinely been persisted (spec §63, §64)."""
    _check_limit(request)
    payload = _service().persistence_status()
    return envelope(payload, source="database", data_status=DataStatus.HISTORICAL)


@router.get("/rate-limit")
async def get_rate_limit_stats(request: Request) -> Dict[str, Any]:
    """Current limiter configuration and tracked buckets (spec §92)."""
    _check_limit(request)
    payload = {
        "max_requests": crypto_settings.rate_limit_max_requests,
        "window_seconds": crypto_settings.rate_limit_window_seconds,
        "tracked_clients": len(_crypto_limiter._hits),  # noqa: SLF001 - diagnostics only
        "ws_max_connections": crypto_settings.ws_max_connections,
    }
    return envelope(payload, source="internal", data_status=DataStatus.LIVE)


# ---------------------------------------------------------------------------
# WebSocket gateway
# ---------------------------------------------------------------------------
@ws_router.websocket("/ws/{client_id}")
async def crypto_ws(websocket: WebSocket, client_id: str) -> None:
    """
    Live market-data gateway (spec §8, §9, §49, §50, §89, §90).

    One upstream provider connection serves every browser client. The socket is
    bounded (connections, symbols per client, coalesced frames) and reports the
    real source of every value it forwards.
    """
    from app.crypto.websocket.manager import crypto_ws_manager

    if not crypto_ws_manager.connection_allowed(client_id):
        await websocket.close(code=1013)
        return
    await websocket.accept()
    await crypto_ws_manager.serve(websocket, client_id)
