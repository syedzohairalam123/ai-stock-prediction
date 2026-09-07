"""
Phase 3/16 — repository functions. Routes call these; nothing in main.py
constructs a raw SQLAlchemy query directly.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .db import session_scope
from .models import PredictionRecord, WatchlistItem


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
