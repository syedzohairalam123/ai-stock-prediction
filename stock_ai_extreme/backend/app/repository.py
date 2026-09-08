"""
Phase 3/16 — repository functions. Routes call these; nothing in main.py
constructs a raw SQLAlchemy query directly.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .db import session_scope
from .models import Alert, PortfolioHolding, PredictionRecord, WatchlistItem


def save_prediction(ticker: str, model: str, horizon: int, data_source: str, data_status: str,
                     predictions: list, metrics: dict) -> int:
    with session_scope() as db:
        record = PredictionRecord(
            ticker=ticker.upper(), model=model, horizon=horizon,
            data_source=data_source, data_status=data_status,
            predictions=predictions, metrics=metrics,
        )
        db.add(record)
        db.flush()
        return record.id


def get_prediction_history(ticker: str, limit: int = 50) -> list[dict]:
    with session_scope() as db:
        rows = db.execute(
            select(PredictionRecord)
            .where(PredictionRecord.ticker == ticker.upper())
            .order_by(PredictionRecord.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "id": r.id, "ticker": r.ticker, "model": r.model, "horizon": r.horizon,
                "created_at": r.created_at.isoformat(), "data_source": r.data_source,
                "data_status": r.data_status, "predictions": r.predictions, "metrics": r.metrics,
                "actual_price": r.actual_price,
            }
            for r in rows
        ]


def list_watchlist() -> list[dict]:
    with session_scope() as db:
        rows = db.execute(select(WatchlistItem).order_by(WatchlistItem.added_at.asc())).scalars().all()
        return [{"id": r.id, "ticker": r.ticker, "note": r.note, "added_at": r.added_at.isoformat()} for r in rows]


def add_to_watchlist(ticker: str, note: str | None = None) -> dict:
    with session_scope() as db:
        item = WatchlistItem(ticker=ticker.upper(), note=note)
        db.add(item)
        try:
            db.flush()
        except IntegrityError as exc:
            raise ValueError(f"{ticker.upper()} is already on the watchlist.") from exc
        return {"id": item.id, "ticker": item.ticker, "note": item.note, "added_at": item.added_at.isoformat()}


def remove_from_watchlist(ticker: str) -> bool:
    with session_scope() as db:
        result = db.execute(delete(WatchlistItem).where(WatchlistItem.ticker == ticker.upper()))
        return result.rowcount > 0


def get_unresolved_predictions(limit: int = 200) -> list[dict]:
    with session_scope() as db:
        rows = db.execute(
            select(PredictionRecord).where(PredictionRecord.actual_price.is_(None)).limit(limit)
        ).scalars().all()
        return [
            {"id": r.id, "ticker": r.ticker, "model": r.model, "predictions": r.predictions, "created_at": r.created_at.isoformat()}
            for r in rows
        ]


def set_actual_price(record_id: int, actual_price: float) -> None:
    with session_scope() as db:
        record = db.get(PredictionRecord, record_id)
        if record:
            record.actual_price = actual_price


def get_resolved_predictions(ticker: str | None = None, model: str | None = None, limit: int = 500) -> list[dict]:
    with session_scope() as db:
        stmt = select(PredictionRecord).where(PredictionRecord.actual_price.is_not(None))
        if ticker:
            stmt = stmt.where(PredictionRecord.ticker == ticker.upper())
        if model:
            stmt = stmt.where(PredictionRecord.model == model)
        rows = db.execute(stmt.order_by(PredictionRecord.created_at.asc()).limit(limit)).scalars().all()
        return [
            {
                "id": r.id, "ticker": r.ticker, "model": r.model, "created_at": r.created_at.isoformat(),
                "predicted_price": (r.predictions or [{}])[0].get("price"), "actual_price": r.actual_price,
            }
            for r in rows
        ]


def create_alert(ticker: str, alert_type: str, threshold: float) -> dict:
    with session_scope() as db:
        alert = Alert(ticker=ticker.upper(), alert_type=alert_type, threshold=threshold)
        db.add(alert)
        db.flush()
        return _alert_to_dict(alert)


def list_alerts(ticker: str | None = None, active_only: bool = False) -> list[dict]:
    with session_scope() as db:
        stmt = select(Alert)
        if ticker:
            stmt = stmt.where(Alert.ticker == ticker.upper())
        if active_only:
            stmt = stmt.where(Alert.active == True)  # noqa: E712 (SQLAlchemy needs `== True`, not `is True`)
        rows = db.execute(stmt.order_by(Alert.created_at.desc())).scalars().all()
        return [_alert_to_dict(r) for r in rows]


def delete_alert(alert_id: int) -> bool:
    with session_scope() as db:
        result = db.execute(delete(Alert).where(Alert.id == alert_id))
        return result.rowcount > 0


def mark_alert_triggered(alert_id: int, value: float) -> None:
    from datetime import datetime, timezone
    with session_scope() as db:
        alert = db.get(Alert, alert_id)
        if alert:
            alert.triggered_at = datetime.now(timezone.utc)
            alert.triggered_value = value
            alert.active = False


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id, "ticker": a.ticker, "alert_type": a.alert_type, "threshold": a.threshold,
        "active": a.active, "created_at": a.created_at.isoformat(),
        "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        "triggered_value": a.triggered_value,
    }


def list_holdings() -> list[dict]:
    """Portfolio positions, oldest first (stable ordering for the UI)."""
    with session_scope() as db:
        rows = db.execute(select(PortfolioHolding).order_by(PortfolioHolding.created_at.asc())).scalars().all()
        return [_holding_to_dict(r) for r in rows]


def add_holding(ticker: str, shares: float, avg_cost: float, note: str | None = None) -> dict:
    with session_scope() as db:
        holding = PortfolioHolding(ticker=ticker.upper(), shares=shares, avg_cost=avg_cost, note=note)
        db.add(holding)
        db.flush()
        return _holding_to_dict(holding)


def get_holding(holding_id: int) -> dict | None:
    with session_scope() as db:
        holding = db.get(PortfolioHolding, holding_id)
        return _holding_to_dict(holding) if holding else None


def update_holding(holding_id: int, shares: float | None = None, avg_cost: float | None = None,
                   note: str | None = None) -> dict | None:
    """Partial update: only the provided fields change; `note` explicitly
    cleared by passing an empty string. Returns the updated row or None if
    the holding doesn't exist."""
    with session_scope() as db:
        holding = db.get(PortfolioHolding, holding_id)
        if holding is None:
            return None
        if shares is not None:
            holding.shares = shares
        if avg_cost is not None:
            holding.avg_cost = avg_cost
        if note is not None:
            holding.note = note or None
        db.flush()
        return _holding_to_dict(holding)


def delete_holding(holding_id: int) -> bool:
    with session_scope() as db:
        result = db.execute(delete(PortfolioHolding).where(PortfolioHolding.id == holding_id))
        return result.rowcount > 0


def _holding_to_dict(h: PortfolioHolding) -> dict:
    return {
        "id": h.id, "ticker": h.ticker, "shares": h.shares, "avg_cost": h.avg_cost,
        "note": h.note, "created_at": h.created_at.isoformat(), "updated_at": h.updated_at.isoformat(),
    }
