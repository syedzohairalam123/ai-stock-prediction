"""
Derivatives provider manager for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module manages multiple derivatives data providers with fallback and caching.
Following the existing provider manager pattern in the project for consistency.
"""

from datetime import date, datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import logging

from .base import (
    DerivativeDataProvider, DerivativeQuote, MarketDepth, FundingData, OpenInterestData,
    DerivativeProviderError, DerivativeDataStatus
)
from ..validators import DataValidator
from ..schemas import DataFreshness

logger = logging.getLogger("neural_market.derivatives.providers.manager")


class DerivativesDataManager:
    """
    Manager for derivatives data providers.
    
    Provides a unified interface to fetch derivatives data from multiple providers
    with automatic fallback, caching, and data quality validation.
    """
    
    def __init__(self, providers: List[DerivativeDataProvider], 
                 quote_cache_ttl: int = 20,
                 history_cache_ttl: int = 300,
                 funding_cache_ttl: int = 60,
                 oi_cache_ttl: int = 60,
                 depth_cache_ttl: int = 10):
        """
        Initialize the derivatives data manager.
        
        Args:
            providers: List of derivative data providers
            quote_cache_ttl: Cache TTL for quotes in seconds
            history_cache_ttl: Cache TTL for historical data in seconds
            funding_cache_ttl: Cache TTL for funding data in seconds
            oi_cache_ttl: Cache TTL for open interest data in seconds
            depth_cache_ttl: Cache TTL for market depth in seconds
        """
        # Keep only configured providers
        self.providers = [p for p in providers if p.is_configured()]
        if not self.providers:
            logger.warning("No configured derivatives providers - some features may be unavailable")
        
        # Simple in-memory caches
        self._quote_cache = {}
        self._history_cache = {}
        self._funding_cache = {}
        self._oi_cache = {}
        self._depth_cache = {}
        
        # Cache TTLs
        self.quote_cache_ttl = quote_cache_ttl
        self.history_cache_ttl = history_cache_ttl
        self.funding_cache_ttl = funding_cache_ttl
        self.oi_cache_ttl = oi_cache_ttl
        self.depth_cache_ttl = depth_cache_ttl
        
        # Data validator
        self.validator = DataValidator(max_age_seconds=quote_cache_ttl)
    
    async def get_instruments(self, asset_class: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get available derivative instruments.
        
        Args:
            asset_class: Optional filter by asset class
            
        Returns:
            List of instrument dictionaries
        """
        last_error = None
        
        providers = self._providers_for_asset_class(asset_class)
        for provider in providers:
            try:
                instruments = await provider.get_instruments(asset_class)
                return instruments
            except DerivativeProviderError as exc:
                logger.warning(f"Instruments provider {provider.name} failed: {exc}")
                last_error = exc
                continue
        
        # All providers failed
        error_msg = f"All providers failed for instruments: {last_error}" if last_error else "No providers available"
        logger.error(error_msg)
        raise DerivativeProviderError("manager", error_msg)

    def _providers_for_asset_class(self, asset_class: Optional[str]) -> List[DerivativeDataProvider]:
        """Prefer a native derivatives venue for crypto while retaining fallbacks."""
        if asset_class and asset_class.upper() == "CRYPTO":
            return sorted(self.providers, key=lambda provider: 0 if provider.name == "binance" else 1)
        return self.providers
    
    async def get_quote(self, instrument_id: str) -> DerivativeQuote:
        """
        Get current quote for an instrument with caching and validation.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            DerivativeQuote object
        """
        # Check cache
        cache_key = f"quote:{instrument_id}"
        cached = self._get_from_cache(self._quote_cache, cache_key, self.quote_cache_ttl)
        if cached:
            logger.debug(f"Quote cache hit for {instrument_id}")
            return cached
        
        last_error = None
        for provider in self.providers:
            try:
                quote = await provider.get_quote(instrument_id)
                
                # Validate data quality
                quote_dict = quote.to_dict()
                is_valid, quality_report = self.validator.validate_quote(quote_dict, provider.name)
                
                if not is_valid:
                    logger.warning(f"Quote validation failed for {instrument_id}: {quality_report.issues}")
                    # Still return the quote but mark status appropriately
                    if quality_report.freshness == DataFreshness.UNAVAILABLE:
                        quote.status = DerivativeDataStatus.UNAVAILABLE
                    elif quality_report.freshness == DataFreshness.STALE:
                        quote.status = DerivativeDataStatus.STALE
                
                # Cache the validated quote
                self._set_cache(self._quote_cache, cache_key, quote, self.quote_cache_ttl)
                return quote
                
            except DerivativeProviderError as exc:
                logger.warning(f"Quote provider {provider.name} failed for {instrument_id}: {exc}")
                last_error = exc
                continue
        
        # All providers failed - return unavailable quote
        logger.error(f"All providers failed for quote {instrument_id}: {last_error}")
        return DerivativeQuote(
            instrument_id=instrument_id,
            timestamp=datetime.now(timezone.utc),
            last_price=0.0,
            source="none",
            status=DerivativeDataStatus.UNAVAILABLE
        )
    
    async def get_historical_data(self, instrument_id: str, start: date, 
                                   end: date, interval: str = "1d") -> List[Dict[str, Any]]:
        """
        Get historical price data with caching.
        
        Args:
            instrument_id: Instrument identifier
            start: Start date
            end: End date
            interval: Data interval
            
        Returns:
            List of historical data dictionaries
        """
        # Check cache
        cache_key = f"history:{instrument_id}:{start}:{end}:{interval}"
        cached = self._get_from_cache(self._history_cache, cache_key, self.history_cache_ttl)
        if cached:
            logger.debug(f"History cache hit for {instrument_id}")
            return cached
        
        last_error = None
        for provider in self.providers:
            try:
                data = await provider.get_historical_data(instrument_id, start, end, interval)
                self._set_cache(self._history_cache, cache_key, data, self.history_cache_ttl)
                return data
            except DerivativeProviderError as exc:
                logger.warning(f"History provider {provider.name} failed for {instrument_id}: {exc}")
                last_error = exc
                continue
        
        # All providers failed
        error_msg = f"All providers failed for history {instrument_id}: {last_error}" if last_error else "No providers available"
        logger.error(error_msg)
        raise DerivativeProviderError("manager", error_msg)
    
    async def get_funding_data(self, instrument_id: str) -> FundingData:
        """
        Get funding rate data with caching.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            FundingData object
        """
        # Check cache
        cache_key = f"funding:{instrument_id}"
        cached = self._get_from_cache(self._funding_cache, cache_key, self.funding_cache_ttl)
        if cached:
            logger.debug(f"Funding cache hit for {instrument_id}")
            return cached
        
        last_error = None
        for provider in self.providers:
            try:
                funding = await provider.get_funding_data(instrument_id)
                self._set_cache(self._funding_cache, cache_key, funding, self.funding_cache_ttl)
                return funding
            except DerivativeProviderError as exc:
                logger.warning(f"Funding provider {provider.name} failed for {instrument_id}: {exc}")
                last_error = exc
                continue
        
        # All providers failed - return unavailable
        logger.error(f"All providers failed for funding {instrument_id}: {last_error}")
        return FundingData(
            instrument_id=instrument_id,
            current_funding_rate=None,
            predicted_funding_rate=None,
            next_funding_time=None,
            last_funding_rate=None,
            funding_interval_hours=None,
            source="none",
            status=DerivativeDataStatus.UNAVAILABLE
        )
    
    async def get_open_interest(self, instrument_id: str) -> OpenInterestData:
        """
        Get open interest data with caching.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            OpenInterestData object
        """
        # Check cache
        cache_key = f"oi:{instrument_id}"
        cached = self._get_from_cache(self._oi_cache, cache_key, self.oi_cache_ttl)
        if cached:
            logger.debug(f"OI cache hit for {instrument_id}")
            return cached
        
        last_error = None
        for provider in self.providers:
            try:
                oi = await provider.get_open_interest(instrument_id)
                self._set_cache(self._oi_cache, cache_key, oi, self.oi_cache_ttl)
                return oi
            except DerivativeProviderError as exc:
                logger.warning(f"OI provider {provider.name} failed for {instrument_id}: {exc}")
                last_error = exc
                continue
        
        # All providers failed - return unavailable
        logger.error(f"All providers failed for OI {instrument_id}: {last_error}")
        return OpenInterestData(
            instrument_id=instrument_id,
            current_open_interest=None,
            open_interest_value=None,
            open_interest_change_24h=None,
            open_interest_change_percent_24h=None,
            source="none",
            status=DerivativeDataStatus.UNAVAILABLE
        )
    
    async def get_market_depth(self, instrument_id: str, depth: int = 20) -> MarketDepth:
        """
        Get market depth with caching.
        
        Args:
            instrument_id: Instrument identifier
            depth: Number of price levels
            
        Returns:
            MarketDepth object
        """
        # Check cache
        cache_key = f"depth:{instrument_id}:{depth}"
        cached = self._get_from_cache(self._depth_cache, cache_key, self.depth_cache_ttl)
        if cached:
            logger.debug(f"Depth cache hit for {instrument_id}")
            return cached
        
        last_error = None
        for provider in self.providers:
            try:
                depth_data = await provider.get_market_depth(instrument_id, depth)
                self._set_cache(self._depth_cache, cache_key, depth_data, self.depth_cache_ttl)
                return depth_data
            except DerivativeProviderError as exc:
                logger.warning(f"Depth provider {provider.name} failed for {instrument_id}: {exc}")
                last_error = exc
                continue
        
        # All providers failed
        error_msg = f"All providers failed for depth {instrument_id}: {last_error}" if last_error else "No providers available"
        logger.error(error_msg)
        raise DerivativeProviderError("manager", error_msg)
    
    async def get_historical_funding(self, instrument_id: str, start: date, 
                                      end: date) -> List[Dict[str, Any]]:
        """
        Get historical funding rate data.
        
        Args:
            instrument_id: Instrument identifier
            start: Start date
            end: End date
            
        Returns:
            List of historical funding data dictionaries
        """
        last_error = None
        for provider in self.providers:
            try:
                return await provider.get_historical_funding(instrument_id, start, end)
            except DerivativeProviderError as exc:
                logger.warning(f"Historical funding provider {provider.name} failed: {exc}")
                last_error = exc
                continue
        
        # All providers failed
        error_msg = f"All providers failed for historical funding {instrument_id}: {last_error}" if last_error else "No providers available"
        logger.error(error_msg)
        raise DerivativeProviderError("manager", error_msg)
    
    async def get_historical_open_interest(self, instrument_id: str, start: date,
                                           end: date) -> List[Dict[str, Any]]:
        """
        Get historical open interest data.
        
        Args:
            instrument_id: Instrument identifier
            start: Start date
            end: End date
            
        Returns:
            List of historical open interest data dictionaries
        """
        last_error = None
        for provider in self.providers:
            try:
                return await provider.get_historical_open_interest(instrument_id, start, end)
            except DerivativeProviderError as exc:
                logger.warning(f"Historical OI provider {provider.name} failed: {exc}")
                last_error = exc
                continue
        
        # All providers failed
        error_msg = f"All providers failed for historical OI {instrument_id}: {last_error}" if last_error else "No providers available"
        logger.error(error_msg)
        raise DerivativeProviderError("manager", error_msg)
    
    def _get_from_cache(self, cache: Dict[str, Any], key: str, ttl: int) -> Optional[Any]:
        """Get item from cache if not expired."""
        if key in cache:
            item, timestamp = cache[key]
            if datetime.now(timezone.utc) - timestamp < timedelta(seconds=ttl):
                return item
            else:
                # Remove expired item
                del cache[key]
        return None
    
    def _set_cache(self, cache: Dict[str, Any], key: str, value: Any, ttl: int):
        """Set item in cache with timestamp."""
        cache[key] = (value, datetime.now(timezone.utc))
    
    def purge_expired_caches(self) -> int:
        """Remove expired cache entries."""
        now = datetime.now(timezone.utc)
        removed = 0
        
        for cache, ttl in [
            (self._quote_cache, self.quote_cache_ttl),
            (self._history_cache, self.history_cache_ttl),
            (self._funding_cache, self.funding_cache_ttl),
            (self._oi_cache, self.oi_cache_ttl),
            (self._depth_cache, self.depth_cache_ttl),
        ]:
            expired_keys = [
                key for key, (_, timestamp) in cache.items()
                if now - timestamp > timedelta(seconds=ttl)
            ]
            for key in expired_keys:
                del cache[key]
                removed += 1
        
        return removed
    
    def cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "quote_entries": len(self._quote_cache),
            "history_entries": len(self._history_cache),
            "funding_entries": len(self._funding_cache),
            "oi_entries": len(self._oi_cache),
            "depth_entries": len(self._depth_cache),
        }
    
    def provider_status(self) -> List[Dict[str, Any]]:
        """Get status of all providers."""
        return [
            {"name": p.name, "configured": p.is_configured()}
            for p in self.providers
        ]
