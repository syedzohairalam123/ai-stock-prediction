"""
Phase 20 — persistence helpers for paper orders + audit trail.

Mirrors `app/repository.py`: thin functions over `session_scope()`, returning
plain dicts so no ORM object ever escapes the session (the Phase 19 bug report
in this project documents exactly what happens when they do).
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Iterable, Optional

from ..db import session_scope
from ..logging_config import get_logger
from .models import PaperAuditRecord, PaperOrderRecord
from .pnl import finite_or_none

logger = get_logger("neural_market.paper.repository")


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _order_to_dict(row: PaperOrderRecord) -> dict:
    return {
        "id": row.id,
        "userId": row.user_id,
        "clientRequestId": row.client_request_id,
        "symbol": row.symbol,
        "instrumentKind": row.instrument_kind,
        "displayName": row.display_name,
        "quoteMode": row.quote_mode,
        "side": row.side,
        "orderType": row.order_type,
        "amountMode": row.amount_mode,
        "amount": row.amount,
        "quantity": row.quantity,
        "limitPrice": row.limit_price,
        "referencePrice": row.reference_price,
        "currency": row.currency,
        "notional": row.notional,
        "status": row.status,
        "dataMode": row.data_mode,
        "dataSource": row.data_source,
        "openedSnapshot": row.opened_snapshot or {},
        "submitSnapshot": row.submit_snapshot or {},
        "forecastMarketId": row.forecast_market_id,
        "probabilityAtOpen": row.probability_at_open,
        "probabilityCurrent": row.probability_current,
        "conditionMet": row.condition_met,
        "conditionCheckedAt": _iso(row.condition_checked_at),
        "conditionDetail": row.condition_detail or {},
        "exitReference": row.exit_reference,
        "exitAt": _iso(row.exit_at),
        "pnl": row.pnl,
        "pnlPercent": row.pnl_percent,
        "notes": row.notes,
        "openedAt": _iso(row.opened_at),
        "submittedAt": _iso(row.submitted_at),
        "expiresAt": _iso(row.expires_at),
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
        # Every payload the paper API returns carries this, so a UI bug can
        # never accidentally render a simulation as a real position.
        "paper": True,
        "simulationOnly": True,
        "statusLabel": f"PAPER {row.status}",
    }


def _audit_to_dict(row: PaperAuditRecord) -> dict:
    return {
        "id": row.id,
        "requestId": row.request_id,
        "orderId": row.order_id,
        "userId": row.user_id,
        "event": row.event,
        "instrument": row.instrument,
        "reference": row.reference or {},
        "result": row.result or {},
        "at": _iso(row.at),
    }


def create_order(payload: dict) -> dict:
    with session_scope() as db:
        row = PaperOrderRecord(**payload)
        db.add(row)
        db.flush()
        return _order_to_dict(row)


def get_order(order_id: str) -> Optional[dict]:
    if not order_id:
        return None
    with session_scope() as db:
        row = db.get(PaperOrderRecord, order_id)
        return _order_to_dict(row) if row is not None else None


def get_order_by_request(user_id: Optional[str], client_request_id: str) -> Optional[dict]:
    """Idempotency lookup: the simulation already created for this request id."""
    if not client_request_id:
        return None
    with session_scope() as db:
        row = (
            db.query(PaperOrderRecord)
            .filter(
                PaperOrderRecord.user_id == user_id,
                PaperOrderRecord.client_request_id == client_request_id,
            )
            .order_by(PaperOrderRecord.created_at.desc())
            .first()
        )
        return _order_to_dict(row) if row is not None else None


def list_orders(
    *,
    user_id: Optional[str] = None,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    side: Optional[str] = None,
    quote_mode: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    before: Optional[datetime] = None,
    limit: int = 50,
) -> list[dict]:
    """Filtered history with cursor support (spec §52/§53).

    `before` is the §53 cursor: an ISO timestamp taken from the last row of
    the previous page (`nextBefore`). One indexed `created_at` scan per page
    — no growing OFFSET.
    """
    with session_scope() as db:
        query = db.query(PaperOrderRecord)
        if user_id is not None:
            query = query.filter(PaperOrderRecord.user_id == user_id)
        if symbol:
            query = query.filter(PaperOrderRecord.symbol == symbol.upper())
        if status:
            query = query.filter(PaperOrderRecord.status == status.upper())
        if side:
            query = query.filter(PaperOrderRecord.side == side.upper())
        if quote_mode:
            query = query.filter(PaperOrderRecord.quote_mode == quote_mode.upper())
        if date_from is not None:
            query = query.filter(PaperOrderRecord.created_at >= datetime.combine(date_from, time.min))
        if date_to is not None:
            query = query.filter(PaperOrderRecord.created_at <= datetime.combine(date_to, time.max))
        if before is not None:
            query = query.filter(PaperOrderRecord.created_at < before)
        rows = (
            query.order_by(PaperOrderRecord.created_at.desc())
            .limit(max(1, min(int(limit), 1000)))
            .all()
        )
        return [_order_to_dict(r) for r in rows]


def update_order(order_id: str, **fields: Any) -> Optional[dict]:
    """Patch a simulation. Only whitelisted keys are applied."""
    allowed = {
        "status", "data_mode", "data_source", "exit_reference", "exit_at", "pnl",
        "pnl_percent", "condition_met", "condition_checked_at", "condition_detail",
        "probability_current", "submit_snapshot", "opened_snapshot", "notes",
        "reference_price", "quantity", "notional", "amount", "limit_price",
        "expires_at",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return get_order(order_id)
    with session_scope() as db:
        row = db.get(PaperOrderRecord, order_id)
        if row is None:
            return None
        for key, value in clean.items():
            setattr(row, key, value)
        db.flush()
        return _order_to_dict(row)


def expire_overdue(now: Optional[datetime] = None) -> int:
    """Mark unfilled DRAFT/SIMULATED limit simulations past their TTL EXPIRED.

    Market simulations resolve immediately, so only still-unresolved limit
    conditions are eligible. Returns how many rows changed.
    """
    stamp = now or datetime.now(timezone.utc)
    changed = 0
    with session_scope() as db:
        rows = (
            db.query(PaperOrderRecord)
            .filter(
                PaperOrderRecord.status == "SIMULATED",
                PaperOrderRecord.order_type == "LIMIT",
                PaperOrderRecord.expires_at.isnot(None),
                PaperOrderRecord.expires_at < stamp,
            )
            .all()
        )
        for row in rows:
            row.status = "EXPIRED"
            changed += 1
        if changed:
            db.flush()
    return changed


def add_audit(
    *,
    request_id: str,
    event: str,
    order_id: Optional[str] = None,
    user_id: Optional[str] = None,
    instrument: Optional[str] = None,
    reference: Optional[dict] = None,
    result: Optional[dict] = None,
) -> dict:
    """Append one audit row. Never raises — auditing must not break a user flow."""
    try:
        with session_scope() as db:
            row = PaperAuditRecord(
                request_id=request_id or "unknown",
                event=event,
                order_id=order_id,
                user_id=user_id,
                instrument=instrument,
                reference=reference or {},
                result=result or {},
            )
            db.add(row)
            db.flush()
            return _audit_to_dict(row)
    except Exception as exc:
        logger.warning("paper audit write failed (%s): %s", event, exc)
        return {}


def list_audit(
    *,
    order_id: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    with session_scope() as db:
        query = db.query(PaperAuditRecord)
        if order_id:
            query = query.filter(PaperAuditRecord.order_id == order_id)
        if request_id:
            query = query.filter(PaperAuditRecord.request_id == request_id)
        rows = (
            query.order_by(PaperAuditRecord.at.desc())
            .limit(max(1, min(int(limit), 1000)))
            .all()
        )
        return [_audit_to_dict(r) for r in rows]


def count_by_status(user_id: Optional[str] = None) -> dict:
    with session_scope() as db:
        query = db.query(PaperOrderRecord)
        if user_id is not None:
            query = query.filter(PaperOrderRecord.user_id == user_id)
        out: dict[str, int] = {}
        for row in query.all():
            out[row.status] = out.get(row.status, 0) + 1
        return out


def sanitize_pnl(value: Any) -> Optional[float]:
    """Guard the one number users read most: no NaN/Inf ever reaches the UI."""
    return finite_or_none(value)


def bulk_statuses(orders: Iterable[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for order in orders:
        status = str(order.get("status") or "UNKNOWN")
        out[status] = out.get(status, 0) + 1
    return out
