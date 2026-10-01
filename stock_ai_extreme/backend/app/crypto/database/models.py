"""
Database models for the crypto intelligence module (spec §63, §64).

Ten tables mirror the module's real data flow:

    crypto_assets           curated catalogue + provider mappings
    crypto_quotes           last real quotes seen per (symbol, provider)
    crypto_candles          normalized OHLCV actually received from a provider
    crypto_forecasts        versioned modelled forecasts (never deleted)
    crypto_forecast_evaluations  a stored forecast scored against the outcome
    crypto_targets          analytical milestones
    crypto_target_events    the real observation that changed a target's status
    crypto_categories       provider + internal taxonomy snapshots
    crypto_data_sources     configured provider registry
    crypto_provider_health  observed health/latency per provider

Indexes cover the access paths the API actually uses: ``symbol``, ``timestamp``,
``timeframe``, ``target_date``, ``provider`` and ``forecast_generated_at``.

Nothing here is a source of truth for prices — the tables store what a provider
really published (or a value computed from it), so a restart never invents data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CryptoAsset(Base):
    """Curated asset with its per-provider symbol mapping and industry tag."""

    __tablename__ = "crypto_assets"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_crypto_asset_symbol"),
        Index("idx_crypto_assets_industry", "industry"),
    )

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_symbol: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    binance_symbol: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    coingecko_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CryptoQuote(Base):
    """Latest real quote observed for one (symbol, provider)."""

    __tablename__ = "crypto_quotes"
    __table_args__ = (
        UniqueConstraint("symbol", "provider", name="uq_crypto_quote_symbol_provider"),
        Index("idx_crypto_quotes_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ask: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_percent_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    data_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CryptoCandle(Base):
    """
    Normalized OHLCV actually received from a provider.

    The unique constraint is (symbol, timeframe, provider, timestamp), so a
    repeated fetch updates the same real bar instead of duplicating it.
    Historical depth is bounded by the retention worker (spec §64): the frontend
    only ever receives the range it asked for.
    """

    __tablename__ = "crypto_candles"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "provider", "timestamp", name="uq_crypto_candle_key"
        ),
        Index("idx_crypto_candles_symbol_timeframe", "symbol", "timeframe", "timestamp"),
        Index("idx_crypto_candles_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CryptoForecast(Base):
    """
    A stored, versioned forecast (spec §28, §29, §30).

    Forecasts are append-only: a failed forecast is retained so its error can be
    evaluated retrospectively rather than being quietly deleted.
    """

    __tablename__ = "crypto_forecasts"
    __table_args__ = (
        Index("idx_crypto_forecasts_symbol", "symbol", "timeframe", "forecast_generated_at"),
        Index("idx_crypto_forecasts_generated", "forecast_generated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    target_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    last_close: Mapped[float] = mapped_column(Float, nullable=False)
    prediction: Mapped[float] = mapped_column(Float, nullable=False)
    lower_bound: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(80), nullable=False)
    training_window: Mapped[int] = mapped_column(Integer, default=0)
    training_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    baseline_metrics: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    beats_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    data_source: Mapped[str] = mapped_column(String(40), nullable=False)
    data_quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    limitations: Mapped[dict] = mapped_column(JSON, default=lambda: [])
    #: Populated by the evaluation worker once the horizon has elapsed.
    evaluated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class CryptoForecastEvaluation(Base):
    """Retrospective score of a stored forecast against the realised outcome."""

    __tablename__ = "crypto_forecast_evaluations"
    __table_args__ = (Index("idx_crypto_eval_forecast", "forecast_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    predicted: Mapped[float] = mapped_column(Float, nullable=False)
    actual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    absolute_error: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    percentage_error: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    directional_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    within_interval: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class CryptoTarget(Base):
    """An analytical price milestone (spec §33)."""

    __tablename__ = "crypto_targets"
    __table_args__ = (
        Index("idx_crypto_targets_symbol", "symbol", "status"),
        Index("idx_crypto_targets_date", "target_date"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    source: Mapped[str] = mapped_column(String(40), default="user")
    methodology: Mapped[str] = mapped_column(String(300), default="User-defined analytical milestone.")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    first_reached_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CryptoTargetEvent(Base):
    """A real observation that changed a target's state (spec §34, §40)."""

    __tablename__ = "crypto_target_events"
    __table_args__ = (Index("idx_crypto_target_events_target", "target_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    observed_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=lambda: {})


class CryptoCategory(Base):
    """A provider (or internal) category snapshot with its real market cap."""

    __tablename__ = "crypto_categories"
    __table_args__ = (
        UniqueConstraint("category_id", "provider", name="uq_crypto_category_key"),
        Index("idx_crypto_categories_market_cap", "market_cap"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_cap_change_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    top_coins: Mapped[dict] = mapped_column(JSON, default=lambda: [])
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class CryptoDataSource(Base):
    """Registry of the configured providers and what each can serve."""

    __tablename__ = "crypto_data_sources"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), default="market-data")
    base_url: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    native_intervals: Mapped[dict] = mapped_column(JSON, default=lambda: [])
    streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CryptoProviderHealth(Base):
    """Observed provider health/latency, one row per probe."""

    __tablename__ = "crypto_provider_health"
    __table_args__ = (Index("idx_crypto_health_provider", "provider", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


__all__ = [
    "CryptoAsset",
    "CryptoCandle",
    "CryptoCategory",
    "CryptoDataSource",
    "CryptoForecast",
    "CryptoForecastEvaluation",
    "CryptoProviderHealth",
    "CryptoQuote",
    "CryptoTarget",
    "CryptoTargetEvent",
]
