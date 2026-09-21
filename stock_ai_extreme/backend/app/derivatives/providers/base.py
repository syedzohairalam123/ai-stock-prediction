"""
Base provider abstraction for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module defines the contract for derivatives data providers.
Following the existing provider pattern in the project for consistency.
"""

from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class DerivativeDataStatus(str, Enum):
    """Data status for derivatives market data."""
    LIVE = "LIVE"
    RECENT = "RECENT"
    DELAYED = "DELAYED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class DerivativeProviderError(Exception):
    """Error raised when a derivatives provider cannot fulfill a request."""
    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


@dataclass
class DerivativeQuote:
    """Normalized derivative quote from any provider."""
    instrument_id: str
    timestamp: datetime
    last_price: float
    source: str
    status: DerivativeDataStatus
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    change_24h: Optional[float] = None
    change_percent_24h: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    open_interest: Optional[float] = None
    funding_rate: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "instrument_id": self.instrument_id,
            "timestamp": self.timestamp.isoformat(),
            "last_price": self.last_price,
            "source": self.source,
            "status": self.status.value,
            "bid": self.bid,
            "ask": self.ask,
            "spread": self.spread,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "change_24h": self.change_24h,
            "change_percent_24h": self.change_percent_24h,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "volume_24h": self.volume_24h,
            "open_interest": self.open_interest,
            "funding_rate": self.funding_rate,
        }


@dataclass
class MarketDepthLevel:
    """Single level in order book."""
    price: float
    quantity: float
    cumulative_quantity: Optional[float] = None


@dataclass
class MarketDepth:
    """Order book / market depth data."""
    instrument_id: str
    timestamp: datetime
    bids: List[MarketDepthLevel]
    asks: List[MarketDepthLevel]
    source: str
    status: DerivativeDataStatus
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "instrument_id": self.instrument_id,
            "timestamp": self.timestamp.isoformat(),
            "bids": [
                {
                    "price": level.price,
                    "quantity": level.quantity,
                    "cumulative_quantity": level.cumulative_quantity
                }
                for level in self.bids
            ],
            "asks": [
                {
                    "price": level.price,
                    "quantity": level.quantity,
                    "cumulative_quantity": level.cumulative_quantity
                }
                for level in self.asks
            ],
            "source": self.source,
            "status": self.status.value,
        }


@dataclass
class FundingData:
    """Funding rate data."""
    instrument_id: str
    current_funding_rate: Optional[float]
    predicted_funding_rate: Optional[float]
    next_funding_time: Optional[datetime]
    last_funding_rate: Optional[float]
    funding_interval_hours: Optional[int]
    source: str
    status: DerivativeDataStatus
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "instrument_id": self.instrument_id,
            "current_funding_rate": self.current_funding_rate,
            "predicted_funding_rate": self.predicted_funding_rate,
            "next_funding_time": self.next_funding_time.isoformat() if self.next_funding_time else None,
            "last_funding_rate": self.last_funding_rate,
            "funding_interval_hours": self.funding_interval_hours,
            "source": self.source,
            "status": self.status.value,
        }


@dataclass
class OpenInterestData:
    """Open interest data."""
    instrument_id: str
    current_open_interest: Optional[float]
    open_interest_value: Optional[float]
    open_interest_change_24h: Optional[float]
    open_interest_change_percent_24h: Optional[float]
    source: str
    status: DerivativeDataStatus
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "instrument_id": self.instrument_id,
            "current_open_interest": self.current_open_interest,
            "open_interest_value": self.open_interest_value,
            "open_interest_change_24h": self.open_interest_change_24h,
            "open_interest_change_percent_24h": self.open_interest_change_percent_24h,
            "source": self.source,
            "status": self.status.value,
        }


class DerivativeDataProvider(ABC):
    """
    Abstract base class for derivatives data providers.
    
    All derivatives data providers must implement this interface.
    This ensures consistent behavior across different data sources.
    """
    
    #: Short machine-readable name
    name: str = "base"
    
    @abstractmethod
    async def get_instruments(self, asset_class: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get available derivative instruments.
        
        Args:
            asset_class: Optional filter by asset class (STOCKS, CRYPTO, INDICES, COMMODITIES)
            
        Returns:
            List of instrument dictionaries
            
        Raises:
            DerivativeProviderError: If the request fails
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_quote(self, instrument_id: str) -> DerivativeQuote:
        """
        Get current quote for an instrument.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            DerivativeQuote object
            
        Raises:
            DerivativeProviderError: If the request fails
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_historical_data(self, instrument_id: str, start: date, 
                                   end: date, interval: str = "1d") -> List[Dict[str, Any]]:
        """
        Get historical price data for an instrument.
        
        Args:
            instrument_id: Instrument identifier
            start: Start date
            end: End date
            interval: Data interval (1m, 5m, 15m, 1h, 4h, 1d)
            
        Returns:
            List of historical data dictionaries
            
        Raises:
            DerivativeProviderError: If the request fails
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_funding_data(self, instrument_id: str) -> FundingData:
        """
        Get funding rate data for a perpetual futures instrument.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            FundingData object
            
        Raises:
            DerivativeProviderError: If the request fails
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_open_interest(self, instrument_id: str) -> OpenInterestData:
        """
        Get open interest data for an instrument.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            OpenInterestData object
            
        Raises:
            DerivativeProviderError: If the request fails
        """
        raise NotImplementedError
    
    async def get_market_depth(self, instrument_id: str, depth: int = 20) -> MarketDepth:
        """
        Get order book / market depth for an instrument.
        
        This is an optional capability - providers that don't support it
        should raise DerivativeProviderError.
        
        Args:
            instrument_id: Instrument identifier
            depth: Number of price levels to return
            
        Returns:
            MarketDepth object
            
        Raises:
            DerivativeProviderError: If the request fails or not supported
        """
        raise DerivativeProviderError(self.name, "Market depth not supported")
    
    async def subscribe_quotes(self, instrument_ids: List[str], callback):
        """
        Subscribe to real-time quote updates.
        
        This is an optional capability for WebSocket-based providers.
        
        Args:
            instrument_ids: List of instrument IDs to subscribe to
            callback: Async callback function for quote updates
            
        Raises:
            DerivativeProviderError: If subscription fails or not supported
        """
        raise DerivativeProviderError(self.name, "Real-time subscription not supported")
    
    def is_configured(self) -> bool:
        """
        Check if the provider is properly configured.
        
        Providers that require API keys should override this and return
        False when the key is missing.
        
        Returns:
            True if configured, False otherwise
        """
        return True
    
    async def get_historical_funding(self, instrument_id: str, start: date, 
                                      end: date) -> List[Dict[str, Any]]:
        """
        Get historical funding rate data.
        
        This is an optional capability.
        
        Args:
            instrument_id: Instrument identifier
            start: Start date
            end: End date
            
        Returns:
            List of historical funding data dictionaries
            
        Raises:
            DerivativeProviderError: If the request fails or not supported
        """
        raise DerivativeProviderError(self.name, "Historical funding data not supported")
    
    async def get_historical_open_interest(self, instrument_id: str, start: date,
                                           end: date) -> List[Dict[str, Any]]:
        """
        Get historical open interest data.
        
        This is an optional capability.
        
        Args:
            instrument_id: Instrument identifier
            start: Start date
            end: End date
            
        Returns:
            List of historical open interest data dictionaries
            
        Raises:
            DerivativeProviderError: If the request fails or not supported
        """
        raise DerivativeProviderError(self.name, "Historical open interest data not supported")
