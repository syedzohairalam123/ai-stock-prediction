"""
Phase 20 — Quick Order / Paper Trading API routes.

    GET    /api/market/instrument/{symbol}      instrument + live quote
    GET    /api/market/quote/{symbol}           live quote only
    GET    /api/paper/config                    published simulation limits
    POST   /api/paper/preview                   validate + preview (no writes)
    POST   /api/paper/orders                    record a simulation (idempotent)
    GET    /api/paper/orders                    simulation history
    GET    /api/paper/orders/{id}               one simulation
    GET    /api/paper/orders/{id}/audit         its audit trail
    POST   /api/paper/orders/{id}/evaluate      re-check against real data
    POST   /api/paper/orders/{id}/cancel        stop a simulation
    GET    /api/paper/summary                   aggregate paper statistics

Every endpoint here is simulation-only. There is no route that places an order
with any broker or exchange, moves money, settles cash, or processes a payment —
and no such route exists anywhere else in this app either.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from .config import paper_settings
from .service import PaperOrderError, service
from .simulation import SIMULATION_STATUSES

logger = get_logger("neural_market.paper.routes")

market_router = APIRouter(prefix="/api/market", tags=["Paper Market Context"])
paper_router = APIRouter(prefix="/api/paper", tags=["Paper Trading"])

#: Every response from this module carries this so a client can never present a
#: simulation as a real order.
PAPER_META = {
    "paper": True,
    "simulationOnly": True,
    "banner": "PAPER SIMULATION — NOT A REAL ORDER",
    "disclaimer": (
        "Non-monetary simulation. No order is placed, no broker or exchange is contacted, "
        "and no funds are involved."
    ),
}


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #

class PreviewRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=60)
    kind: Optional[str] = Field(default=None, max_length=20)
    side: str = Field(..., max_length=10)
    orderType: str = Field(default="MARKET", max_length=10)
    amount: Optional[float] = None
    amountMode: Optional[str] = Field(default="NOTIONAL", max_length=12)
    limitPrice: Optional[float] = None
    currency: Optional[str] = Field(default=None, max_length=10)
    displayName: Optional[str] = Field(default=None, max_length=200)
    timestamp: Optional[str] = Field(default=None, max_length=64)


class SnapshotModel(BaseModel):
    """The snapshot the ticket captured when it was opened (spec §9/§15)."""

    capturedAt: Optional[str] = None
    observedPrice: Optional[float] = None
    observedTimestamp: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    dataMode: Optional[str] = None
    stale: Optional[bool] = None
    probabilityYes: Optional[float] = None
    probabilityNo: Optional[float] = None
    selectedOutcome: Optional[str] = None


class SubmitRequest(PreviewRequest):
    clientRequestId: Optional[str] = Field(default=None, max_length=80)
    userId: Optional[str] = Field(default=None, max_length=80)
    openedSnapshot: Optional[SnapshotModel] = None
    notes: Optional[str] = Field(default=None, max_length=500)
    draft: bool = False
    acknowledgeStale: bool = False


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _user_id(header_value: Optional[str], body_value: Optional[str] = None) -> str:
    """Resolve the acting user id.

    This app has no authentication yet (documented in `models.py`), so the id is
    supplied by the client and defaults to a shared `anonymous` bucket. Paper
    history is therefore scoped per supplied id — private in the sense that the
    API only returns rows for the requesting id, but not authenticated. That
    limitation is stated here rather than pretended away.
    """
    for candidate in (body_value, header_value):
        if candidate and str(candidate).strip():
            return str(candidate).strip()[:80]
    return "anonymous"


def _raise(exc: PaperOrderError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"message": exc.message, "issues": exc.issues, **PAPER_META},
    )


# --------------------------------------------------------------------------- #
# Market context
# --------------------------------------------------------------------------- #

@market_router.get("/config")
def market_paper_config():
    """Published simulation limits — no hidden constants."""
    return {
        "staleAfterSeconds": paper_settings.paper_stale_after_seconds,
        "orderTtlSeconds": paper_settings.paper_order_ttl_seconds,
        "minNotional": paper_settings.paper_min_notional,
        "maxNotional": paper_settings.paper_max_notional,
        "maxQuantity": paper_settings.paper_max_quantity,
        "amountPrecision": paper_settings.paper_amount_precision,
        "quantityPrecision": paper_settings.paper_quantity_precision,
        "pricePrecision": paper_settings.paper_price_precision,
        "submitTimeoutSeconds": paper_settings.paper_submit_timeout_seconds,
        "volatilityLookbackDays": paper_settings.paper_volatility_lookback_days,
        "statuses": list(SIMULATION_STATUSES),
        **PAPER_META,
    }


@market_router.get("/instrument/{symbol}")
async def market_instrument(
    symbol: str,
    kind: Optional[str] = Query(default=None, description="Context hint from the page the ticket was opened from"),
    currency: Optional[str] = Query(default=None),
    displayName: Optional[str] = Query(default=None),
):
    """Resolve an instrument and its live quote for the ticket header."""
    instrument, error = await service.resolve(symbol, kind, display_name=displayName, currency=currency)
    if instrument is None:
        raise HTTPException(status_code=404, detail={"message": error or "Unsupported instrument.", **PAPER_META})
    quote = await service.quote(instrument)
    return {
        "instrument": instrument.to_dict(),
        "quote": quote.to_dict(),
        "config": market_paper_config(),
        **PAPER_META,
    }


@market_router.get("/quote/{symbol}")
async def market_quote(
    symbol: str,
    kind: Optional[str] = Query(default=None),
    withBidAsk: bool = Query(default=True),
):
    """Live quote only (price, bid/ask/mid, change, volatility or probability)."""
    instrument, error = await service.resolve(symbol, kind)
    if instrument is None:
        raise HTTPException(status_code=404, detail={"message": error or "Unsupported instrument.", **PAPER_META})
    quote = await service.quote(instrument, with_bid_ask=withBidAsk)
    return {"instrument": instrument.to_dict(), "quote": quote.to_dict(), **PAPER_META}


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #

@paper_router.post("/preview")
async def paper_preview(body: PreviewRequest):
    """Validate and preview a simulation. Writes nothing."""
    try:
        return await service.preview(
            symbol=body.symbol,
            kind=body.kind,
            side=body.side,
            order_type=body.orderType,
            amount=body.amount,
            amount_mode=body.amountMode,
            limit_price=body.limitPrice,
            client_timestamp=body.timestamp,
            currency=body.currency,
            display_name=body.displayName,
        )
    except PaperOrderError as exc:  # pragma: no cover - preview never raises today
        _raise(exc)
    except Exception as exc:
        logger.warning("paper preview failed: %s", exc)
        raise HTTPException(status_code=400, detail={"message": "The preview could not be generated.", **PAPER_META})


@paper_router.post("/orders")
async def create_paper_order(body: SubmitRequest, x_paper_user_id: Optional[str] = Header(default=None)):
    """Record a paper simulation. Idempotent on `clientRequestId`."""
    user = _user_id(x_paper_user_id, body.userId)
    try:
        result = await service.submit(
            symbol=body.symbol,
            kind=body.kind,
            side=body.side,
            order_type=body.orderType,
            amount=body.amount,
            amount_mode=body.amountMode,
            limit_price=body.limitPrice,
            opened_snapshot=(body.openedSnapshot.model_dump() if body.openedSnapshot else None),
            client_timestamp=body.timestamp,
            client_request_id=body.clientRequestId,
            user_id=user,
            currency=body.currency,
            display_name=body.displayName,
            notes=body.notes,
            draft=body.draft,
            acknowledge_stale=body.acknowledgeStale,
        )
    except PaperOrderError as exc:
        _raise(exc)
    except Exception as exc:
        logger.error("paper submission failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"message": "The simulation could not be recorded. Nothing was sent anywhere.", **PAPER_META},
        )
    return {**result, **PAPER_META}


@paper_router.get("/orders")
async def list_paper_orders(
    x_paper_user_id: Optional[str] = Header(default=None),
    userId: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
):
    """Recent simulations for this user id (spec §18). Never the real portfolio."""
    if status and status.upper() not in SIMULATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={"message": f"status must be one of {', '.join(SIMULATION_STATUSES)}", **PAPER_META},
        )
    user = _user_id(x_paper_user_id, userId)
    return {**service.history(user_id=user, symbol=symbol, status=status, limit=limit), "userId": user}


@paper_router.get("/summary")
async def paper_summary(
    x_paper_user_id: Optional[str] = Header(default=None),
    userId: Optional[str] = Query(default=None),
):
    user = _user_id(x_paper_user_id, userId)
    return {**service.summary(user), "userId": user}


@paper_router.get("/orders/{order_id}")
async def get_paper_order(order_id: str, x_paper_user_id: Optional[str] = Header(default=None)):
    try:
        order = service.get(order_id)
    except PaperOrderError as exc:
        _raise(exc)
    return {"order": order, **PAPER_META}


@paper_router.get("/orders/{order_id}/audit")
async def get_paper_order_audit(order_id: str):
    try:
        service.get(order_id)
    except PaperOrderError as exc:
        _raise(exc)
    return {**service.audit(order_id=order_id), **PAPER_META}


@paper_router.post("/orders/{order_id}/evaluate")
async def evaluate_paper_order(order_id: str):
    """Compare a simulation with real subsequent observations.

    Never fabricates an exit price: when no newer real data exists the response
    says so and reports no P&L.
    """
    try:
        return {**await service.evaluate(order_id), **PAPER_META}
    except PaperOrderError as exc:
        _raise(exc)
    except Exception as exc:
        logger.warning("paper evaluation failed for %s: %s", order_id, exc)
        raise HTTPException(status_code=400, detail={"message": "The simulation could not be evaluated.", **PAPER_META})


@paper_router.post("/orders/{order_id}/cancel")
async def cancel_paper_order(order_id: str, body: Optional[CancelRequest] = None):
    try:
        order = service.cancel(order_id, reason=body.reason if body else None)
    except PaperOrderError as exc:
        _raise(exc)
    return {"order": order, **PAPER_META}
