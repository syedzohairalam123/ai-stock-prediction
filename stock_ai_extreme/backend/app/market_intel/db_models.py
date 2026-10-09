"""Phase 23B — corporate market-cap persistence (spec §9, §11, §14, §15).

Additive tables registered through the existing ``Base`` so ``init_db()``
creates them on the same database as every other phase (no second store).
Every row keeps its source and timestamp, and a value that is missing is simply
absent rather than zero-filled.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    """Registry of the companies the market-cap engine covers (spec §8, §15).

    ``company_id`` is a stable slug (e.g. ``nvidia``); ``ticker`` is the primary
    listed security. ``share_classes`` holds the additional class tickers for a
    multi-class issuer so company-wide logic never silently assumes one class.
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    exchange: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(80), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: Comma-separated additional share-class tickers (e.g. "GOOGL" for GOOG).
    additional_tickers: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CompanyMarketObservation(Base):
    """One real observation of a company's price and market capitalisation.

    Keeps price and share count with their own timestamps and sources (spec §9):
    if the two are not from the same date the row is flagged, never presented
    as if they were aligned. This table is also the
    ``shares_outstanding_observations`` store.
    """

    __tablename__ = "company_market_observations"
    __table_args__ = (
        Index("ix_cmo_company_observed", "company_id", "observation_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: PROVIDER_REPORTED | PRICE_X_SHARES | UNAVAILABLE
    market_cap_methodology: Mapped[str] = mapped_column(String(40), default="UNAVAILABLE")
    price_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    shares_source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: VERIFIED | COMPUTED | ESTIMATED | STALE | UNAVAILABLE
    data_quality: Mapped[str] = mapped_column(String(20), default="UNAVAILABLE")
    observation_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    price_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shares_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_document: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MarketCapRankHistory(Base):
    """Stored ranking snapshots so rank changes over time are real history."""

    __tablename__ = "market_cap_rank_history"
    __table_args__ = (
        Index("ix_mcrh_observed_rank", "observed_at", "rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), index=True)
    ticker: Mapped[str] = mapped_column(String(20))
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column(Integer)
    data_quality: Mapped[str] = mapped_column(String(20), default="UNAVAILABLE")
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SharesOutstandingObservation(Base):
    """Explicit share-count observations (spec §15).

    ``company_market_observations`` already carries a share count alongside the
    price, but a share count has its own as-of date and source that can move
    independently of the quote (buybacks, issuance, class conversions). Keeping
    it in its own append-only table means a market-cap comparison can never mix
    a fresh price with a stale share count without that being visible.
    """

    __tablename__ = "shares_outstanding_observations"
    __table_args__ = (
        Index("ix_soo_company_observed", "company_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    data_quality: Mapped[str] = mapped_column(String(20), default="UNAVAILABLE")
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CompanySecurityMapping(Base):
    """Maps a company to every listed security it issues (spec §15).

    A company can trade as several tickers (share classes, cross-listings).
    Keeping the mapping as its own table means the engine never has to assume a
    single ticker per issuer, and a company-wide market-cap figure can be traced
    back to exactly which securities it aggregated (spec §10). Rows are
    upserted from the declared watch universe — nothing is inferred at runtime.
    """

    __tablename__ = "company_security_mappings"
    __table_args__ = (
        UniqueConstraint("company_id", "ticker", name="uq_csm_company_ticker"),
        Index("ix_csm_company", "company_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    exchange: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: COMMON | CLASS_A | CLASS_B | CLASS_C | ADR | OTHER — how the listing is issued.
    security_type: Mapped[str] = mapped_column(String(20), default="COMMON")
    #: True for the ticker the engine treats as the canonical listing.
    is_primary: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class MarketCapSnapshot(Base):
    """A materialised, verifiable market-cap observation (spec §15, §14).

    ``company_market_observations`` is the raw input store (price + shares,
    with their own timestamps). This table is the derived snapshot: the exact
    inputs, the cap actually used, the methodology and the source, frozen
    together so a historical ranking can always be recomputed and audited. A
    missing input leaves the derived column null rather than zero.
    """

    __tablename__ = "market_cap_snapshots"
    __table_args__ = (
        Index("ix_mcs_observed", "observed_at"),
        Index("ix_mcs_company_observed", "company_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), index=True)
    ticker: Mapped[str] = mapped_column(String(20))
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_methodology: Mapped[str] = mapped_column(String(40), default="UNAVAILABLE")
    data_quality: Mapped[str] = mapped_column(String(20), default="UNAVAILABLE")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    shares_source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CorporateActionEvent(Base):
    """Corporate actions that make raw price/share comparisons invalid.

    A split/buyback/issuance recorded here is what lets the engine flag a
    ranking change as action-driven rather than presenting it as pure growth
    (spec §10). Nothing here is inferred — an action is only stored when a
    source reports it.
    """

    __tablename__ = "corporate_action_events"
    __table_args__ = (
        UniqueConstraint("company_id", "action_type", "effective_date", name="uq_cae_company_action_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(60), index=True)
    action_type: Mapped[str] = mapped_column(String(40))  # SPLIT | BUYBACK | ISSUANCE | OTHER
    ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
