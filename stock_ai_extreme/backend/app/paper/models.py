"""
Phase 20 — persistence for the paper-trading ticket.

Two tables, both strictly simulation-facing:

* `paper_orders` — one row per simulated ticket. **Never** read by the
  portfolio tracker, and never written to it. Paper activity is deliberately
  isolated from `portfolio_holdings` so a simulation can never be mistaken for
  a real position (spec §19).
* `paper_audit` — append-only audit metadata for each action taken against a
  simulation: request id, user id (when supplied), timestamp, instrument,
  reference data and the simulation result. Nothing sensitive is stored — no
  credentials, no tokens, no payment data exists to store in the first place.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class PaperOrderRecord(Base):
    """A simulated (paper) order ticket. Displayed, never executed."""

    __tablename__ = "paper_orders"
    __table_args__ = (
        # Idempotency: one client request id maps to at most one simulation per
        # user. The unique constraint is what makes a double-submit safe even
        # when two requests race past the lookup.
        UniqueConstraint("user_id", "client_request_id", name="uq_paper_user_request"),
        Index("idx_paper_symbol_status", "symbol", "status"),
        Index("idx_paper_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=_new_id)
    user_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    #: Client-generated idempotency key (spec §25).
    client_request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    symbol: Mapped[str] = mapped_column(String(40), index=True)
    instrument_kind: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(200))
    quote_mode: Mapped[str] = mapped_column(String(20), default="PRICE")

    side: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[str] = mapped_column(String(10))
    amount_mode: Mapped[str] = mapped_column(String(12), default="NOTIONAL")
    amount: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(12), default="SIMULATED", index=True)
    data_mode: Mapped[str] = mapped_column(String(16), default="UNAVAILABLE")
    data_source: Mapped[str | None] = mapped_column(String(60), nullable=True)

    #: Snapshot captured the moment the ticket was opened (spec §9) and the
    #: snapshot captured at simulated submission — kept separately so the UI
    #: can explain what changed in between.
    opened_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    submit_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    #: Phase 14 forecast linkage (probability-mode instruments only).
    forecast_market_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    probability_at_open: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_current: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Limit-order simulation outcome (spec §12): whether a real subsequent
    #: observation would have satisfied the hypothetical condition.
    condition_met: Mapped[bool | None] = mapped_column(nullable=True)
    condition_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    condition_detail: Mapped[dict] = mapped_column(JSON, default=dict)

    #: Paper P&L (spec §13) — only ever populated from real observed prices.
    exit_reference: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PaperAuditRecord(Base):
    """Append-only audit metadata for paper-simulation activity (spec §26)."""

    __tablename__ = "paper_audit"
    __table_args__ = (Index("idx_paper_audit_order", "order_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(80), index=True)
    order_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(30))
    instrument: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: What the engine observed (source, status, prices) when it decided.
    reference: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
