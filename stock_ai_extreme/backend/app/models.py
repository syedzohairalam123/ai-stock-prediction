"""
Phase 3 (persistence) + Phase 16 (watchlist) ORM models.

Kept intentionally small: this app has no auth yet (that's a later phase),
so these tables are single-tenant for now. Adding a `user_id` foreign key
later is a small migration, not a redesign — nothing here assumes there's
only ever one user, it just doesn't enforce multi-user separation yet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PredictionRecord(Base):
    """One row per prediction ever generated. This is what Phase 9's
    backtesting and any future 'how accurate has this model really been'
    view reads from — real historical predictions, not simulated ones."""
    __tablename__ = "prediction_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    model: Mapped[str] = mapped_column(String(20))
    horizon: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    data_source: Mapped[str] = mapped_column(String(40))
    data_status: Mapped[str] = mapped_column(String(20))
    predictions: Mapped[list] = mapped_column(JSON)   # the list of {date, price, lower, upper, ...}
    metrics: Mapped[dict] = mapped_column(JSON)        # {mae, rmse, ...}
    # Filled in later, once the forecast date has actually passed — see Phase 9's
    # accuracy-tracking use of this table. NULL means "not resolved yet".
    actual_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("ticker", name="uq_watchlist_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
