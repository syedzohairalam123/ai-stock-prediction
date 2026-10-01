"""
Provider abstraction for the crypto intelligence module (spec §52, §53).

One narrow contract every adapter satisfies:

    get_assets()               → catalogue the provider actually serves
    get_quote(symbol)          → latest real quote
    get_historical_candles()   → normalized OHLCV + parse statistics
    get_market_stats()         → optional market-cap/rank metadata
    subscribe_market_data()    → optional real-time stream factory
    health()                   → reachability probe for failover

Adapters return **only** data the provider published. Anything unavailable is
``None`` on the dataclass — never a default that could be mistaken for a
measurement. The parse statistics from
:func:`app.crypto.normalization.normalize_candles` ride along with every candle
response so the API can report what the provider actually sent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

from app.crypto.schemas import Candle, DataStatus, MarketTick


class ProviderError(Exception):
    """A provider could not fulfil a request (network, HTTP, malformed payload)."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


@dataclass
class CandleSeries:
    """A normalized candle response plus the audit trail of how it was built."""

    symbol: str
    timeframe: str
    interval: str
    candles: List[Candle]
    stats: Dict[str, int]
    source: str
    fetched_at: datetime
    #: Provider's own timestamp for the newest record, when it publishes one.
    source_timestamp: Optional[datetime] = None
    #: True when the candles were rolled up from a lower-resolution interval.
    aggregated: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.candles

    @property
    def last_close(self) -> Optional[float]:
        return self.candles[-1].close if self.candles else None

    def to_meta(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "interval": self.interval,
            "source": self.source,
            "count": len(self.candles),
            "fetched_at": self.fetched_at.isoformat(),
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "aggregated": self.aggregated,
            "parse_stats": dict(self.stats),
            "notes": list(self.notes),
        }


@dataclass
class ProviderQuote:
    """Latest quote as the provider reported it."""

    symbol: str
    price: Optional[float]
    source: str
    fetched_at: datetime
    source_timestamp: Optional[datetime] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: Optional[float] = None
    quote_volume_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    open_24h: Optional[float] = None
    change_24h: Optional[float] = None
    change_percent_24h: Optional[float] = None
    status: DataStatus = DataStatus.UNAVAILABLE
    #: Real provider errors encountered before this one answered (failover trail).
    errors: List[str] = field(default_factory=list)

    def to_tick(self) -> MarketTick:
        return MarketTick(
            symbol=self.symbol,
            price=self.price or 0.0,
            bid=self.bid,
            ask=self.ask,
            volume=self.volume_24h,
            timestamp=self.source_timestamp or self.fetched_at,
            source_timestamp=self.source_timestamp,
            received_at=self.fetched_at,
            source=self.source,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "volume_24h": self.volume_24h,
            "quote_volume_24h": self.quote_volume_24h,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "open_24h": self.open_24h,
            "change_24h": self.change_24h,
            "change_percent_24h": self.change_percent_24h,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "status": self.status.value,
            "errors": list(self.errors),
        }


@dataclass
class ProviderHealth:
    provider: str
    available: bool
    checked_at: datetime
    latency_ms: Optional[float] = None
    detail: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "status": "AVAILABLE" if self.available else "DOWN",
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "checked_at": self.checked_at.isoformat(),
        }


class CryptoMarketProvider(ABC):
    """Contract every crypto market-data adapter implements."""

    #: Short, stable machine name (used in cache keys and API meta).
    name: str = "base"
    #: Intervals this provider can serve natively (from the timeframe registry).
    native_intervals: Sequence[str] = ()

    def symbol_for(self, asset) -> Optional[str]:
        """
        Map a canonical asset to this provider's own symbol (spec §51).

        The default is the identity mapping, so an adapter that uses the same
        symbols internally works with no extra code; adapters with their own
        convention (Binance ``BTCUSDT``, CoinGecko ``bitcoin``) override it.
        Returns ``None`` when this provider genuinely cannot quote the asset,
        which is how the manager knows to fail over instead of guessing.
        """
        return getattr(asset, "internal", None)

    @abstractmethod
    async def get_assets(self) -> List[Dict[str, Any]]:
        """Assets this provider can actually quote."""

    @abstractmethod
    async def get_quote(self, symbol: str, provider_symbol: str) -> ProviderQuote:
        """Latest real quote for one symbol."""

    @abstractmethod
    async def get_historical_candles(
        self,
        *,
        symbol: str,
        provider_symbol: str,
        interval: str,
        limit: int,
    ) -> CandleSeries:
        """Normalized OHLCV history for one interval."""

    async def get_market_stats(self, symbol: str, coingecko_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Optional market-cap/rank metadata. ``None`` when unsupported."""
        return None

    def subscribe_market_data(
        self,
        streams: Sequence[Dict[str, str]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Optional real-time stream factory.

        ``streams`` is a list of ``{"symbol": ..., "provider_symbol": ..., "interval": ...}``.
        Default: unsupported (failover will skip this provider for streaming).
        """
        raise ProviderError(self.name, "Real-time streaming not supported")

    def supports_streaming(self) -> bool:
        return False

    async def health(self) -> ProviderHealth:
        """Default liveness probe. Adapters override with a real endpoint."""
        raise ProviderError(self.name, "No health probe implemented")

    async def close(self) -> None:
        """Release any held HTTP/WebSocket resources."""
        return None


#: Where a value in an API payload came from (spec §99).
VALUE_ORIGIN_SOURCE = "SOURCE"
