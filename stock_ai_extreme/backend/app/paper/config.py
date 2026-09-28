"""
Phase 20 — paper-trading configuration.

Every tunable lives here (mirroring `discovery/config.py` and
`derivatives/config.py`) so there are no hidden constants: the same numbers the
engine validates against are the ones published by `GET /api/paper/config`.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PaperSettings(BaseSettings):
    """Simulation-only settings. None of these can cause a real transaction."""

    #: How long a quote may be before it is labelled STALE and the ticket
    #: refuses to present it as the current price.
    paper_stale_after_seconds: int = Field(default=900, ge=60, le=86400)
    #: How long an unfilled LIMIT simulation stays open before it EXPIRES.
    paper_order_ttl_seconds: int = Field(default=604800, ge=300, le=7776000)

    #: Hard caps (server-side, never trusted from the client).
    paper_max_notional: float = Field(default=1_000_000.0, gt=0.0, le=1e12)
    paper_min_notional: float = Field(default=0.01, gt=0.0, le=1000.0)
    paper_max_quantity: float = Field(default=1_000_000.0, gt=0.0, le=1e12)
    #: Decimal places accepted for a notional amount (currency-like).
    paper_amount_precision: int = Field(default=2, ge=0, le=8)
    #: Decimal places accepted for a raw quantity.
    paper_quantity_precision: int = Field(default=8, ge=0, le=12)
    #: Decimal places accepted for a limit price.
    paper_price_precision: int = Field(default=8, ge=0, le=12)

    #: A client-supplied timestamp further in the future than this is rejected
    #: (clock skew / tampering).
    paper_max_clock_skew_seconds: int = Field(default=300, ge=30, le=3600)

    #: Daily bars used for the historical-volatility readout on the risk panel.
    paper_volatility_lookback_days: int = Field(default=60, ge=20, le=400)
    #: Annualisation factor for daily returns (trading days per year).
    paper_trading_days_per_year: int = Field(default=252, ge=200, le=366)

    #: How many rows `GET /api/paper/orders` returns when no limit is given.
    paper_default_history_limit: int = Field(default=50, ge=1, le=200)
    paper_max_history_limit: int = Field(default=200, ge=1, le=1000)
    #: Rows of audit trail kept per order listing.
    paper_audit_limit: int = Field(default=100, ge=1, le=1000)

    #: Fake-ordering latency budget: the frontend uses this to bound its
    #: "SUBMITTING…" state so the panel can never get stuck.
    paper_submit_timeout_seconds: int = Field(default=20, ge=3, le=120)

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


paper_settings = PaperSettings()
