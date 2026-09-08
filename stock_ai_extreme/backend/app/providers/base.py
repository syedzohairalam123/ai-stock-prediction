"""
Provider abstraction layer (Phase 2).

Nothing in this file talks to the network directly. It only defines the
*contract* every market-data provider must follow, so the rest of the app
(agents, routes, websocket) never depends on a specific vendor (yfinance,
Finnhub, ...). Swapping or adding a provider means writing one new class
here, not touching main.py or agents.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

import pandas as pd


class DataStatus(str, Enum):
    """How trustworthy/fresh a piece of data is, shown directly in the UI.

    Never let the frontend display CACHED or STALE data labeled as LIVE.
    """
    LIVE = "LIVE"                # from the primary provider, timestamped today/this session
    RECENT = "RECENT"            # real provider data, but a little behind (e.g. previous close)
    CACHED = "CACHED"            # served from our own TTL cache, not a fresh network call
    STALE = "STALE"              # older than the cache TTL but kept as a last-resort fallback
    UNAVAILABLE = "UNAVAILABLE"  # no provider could answer; caller must not fabricate a value


class ProviderError(Exception):
    """Raised by a provider when it cannot honestly answer a request.

    The manager catches this and tries the next provider in the chain —
    it must never be swallowed silently into a fake/default value.
    """
    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


@dataclass
class Quote:
    """A single normalized live-quote result, regardless of which provider produced it."""
    ticker: str
    price: float
    source: str
    status: DataStatus
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    previous_close: Optional[float] = None
    change_percent: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": round(self.price, 4),
            "previous_close": round(self.previous_close, 4) if self.previous_close is not None else None,
            "change_percent": round(self.change_percent, 4) if self.change_percent is not None else None,
            "source": self.source,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HistoryResult:
    """A normalized OHLCV(+indicators) history result plus its provenance."""
    frame: pd.DataFrame
    source: str
    status: DataStatus
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MarketDataProvider(ABC):
    """Every concrete provider (yfinance, Finnhub, ...) implements this."""

    #: short machine-readable name used in "source" fields and logs
    name: str = "base"

    @abstractmethod
    async def get_history(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        """Return raw OHLCV rows (no indicators). Must raise ProviderError, never return empty silently."""
        raise NotImplementedError

    @abstractmethod
    async def get_quote(self, ticker: str) -> Quote:
        """Return the latest available price for a ticker."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Providers that need an API key should override this and return False when missing,
        so the manager can skip them quietly instead of failing loudly on every request."""
        return True

    async def get_news(self, ticker: str) -> list[dict]:
        """Optional capability, same pattern as get_profile: a provider that
        can't serve news simply doesn't override this, and the manager's
        getattr() check skips it. Returns normalized headlines or [] when
        there is genuinely no news right now (never a fabricated item)."""
        raise ProviderError(self.name, f"{self.name} does not support news")
