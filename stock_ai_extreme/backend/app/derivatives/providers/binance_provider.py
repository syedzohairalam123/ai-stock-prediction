"""
Binance provider for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This provider uses Binance public API to fetch real market data for crypto perpetual futures.
Binance provides legitimate market data for crypto derivatives without requiring API keys for public endpoints.
"""

from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Any, Optional
import httpx
import logging

from .base import (
    DerivativeDataProvider, DerivativeQuote, MarketDepth, MarketDepthLevel,
    FundingData, OpenInterestData, DerivativeProviderError, DerivativeDataStatus
)

logger = logging.getLogger("neural_market.derivatives.providers.binance")


class BinanceDerivativesProvider(DerivativeDataProvider):
    """
    Binance-based derivatives data provider for crypto perpetual futures.
    
    Provides real market data for:
    - BTCUSDT perpetual futures
    - ETHUSDT perpetual futures
    - Other crypto perpetual futures
    
    All data is sourced from Binance public API, a legitimate crypto exchange.
    No API key required for public market data endpoints.
    """
    
    name = "binance"
    
    BASE_URL = "https://fapi.binance.com"
    
    # Common crypto perpetual futures instruments
    INSTRUMENTS = [
        {"symbol": "BTCUSDT", "display_name": "Bitcoin USDT Perpetual", "underlying": "BTC",
         "quote_currency": "USDT", "exchange": "BINANCE", "tick_size": 0.1,
         "lot_size": 0.001, "price_precision": 1, "quantity_precision": 3},
        {"symbol": "ETHUSDT", "display_name": "Ethereum USDT Perpetual", "underlying": "ETH",
         "quote_currency": "USDT", "exchange": "BINANCE", "tick_size": 0.01,
         "lot_size": 0.001, "price_precision": 2, "quantity_precision": 3},
        {"symbol": "BNBUSDT", "display_name": "Binance Coin USDT Perpetual", "underlying": "BNB",
         "quote_currency": "USDT", "exchange": "BINANCE", "tick_size": 0.001,
         "lot_size": 0.01, "price_precision": 3, "quantity_precision": 2},
        {"symbol": "SOLUSDT", "display_name": "Solana USDT Perpetual", "underlying": "SOL",
         "quote_currency": "USDT", "exchange": "BINANCE", "tick_size": 0.001,
         "lot_size": 0.01, "price_precision": 3, "quantity_precision": 2},
        {"symbol": "XRPUSDT", "display_name": "XRP USDT Perpetual", "underlying": "XRP",
         "quote_currency": "USDT", "exchange": "BINANCE", "tick_size": 0.0001,
         "lot_size": 1, "price_precision": 4, "quantity_precision": 0},
    ]
    
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        """
        Initialize Binance provider.
        
        Args:
            max_retries: Maximum number of retry attempts
            timeout: Request timeout in seconds
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def get_instruments(self, asset_class: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get available derivative instruments.
        
        Args:
            asset_class: Optional filter by asset class (only CRYPTO supported)
            
        Returns:
            List of instrument dictionaries
        """
        try:
            if asset_class and asset_class.upper() != "CRYPTO":
                return []
            
            # Fetch exchange info from Binance
            response = await self.client.get(f"{self.BASE_URL}/fapi/v1/exchangeInfo")
            response.raise_for_status()
            
            data = response.json()
            instruments = []
            
            for symbol_data in data.get('symbols', []):
                # Only include USDT perpetual futures
                if (symbol_data.get('contractType') == 'PERPETUAL' and 
                    symbol_data.get('quoteAsset') == 'USDT' and
                    symbol_data.get('status') == 'TRADING'):
                    
                    # Extract instrument info
                    symbol = symbol_data['symbol']
                    base_asset = symbol_data['baseAsset']
                    
                    # Find price precision
                    price_precision = 8
                    quantity_precision = 8
                    tick_size = 0.00000001
                    lot_size = 0.00000001
                    
                    for filter_data in symbol_data.get('filters', []):
                        if filter_data['filterType'] == 'PRICE_FILTER':
                            tick_size = float(filter_data['tickSize'])
                            price_precision = len(str(tick_size).split('.')[-1].rstrip('0'))
                        elif filter_data['filterType'] == 'LOT_SIZE':
                            lot_size = float(filter_data['stepSize'])
                            quantity_precision = len(str(lot_size).split('.')[-1].rstrip('0'))
                    
                    instrument = {
                        "id": symbol,
                        "symbol": symbol,
                        "display_name": f"{base_asset} USDT Perpetual",
                        "asset_class": "CRYPTO",
                        "underlying": base_asset,
                        "quote_currency": "USDT",
                        "exchange": "BINANCE",
                        "status": "ACTIVE",
                        "contract_type": "PERPETUAL",
                        "tick_size": tick_size,
                        "lot_size": lot_size,
                        "price_precision": price_precision,
                        "quantity_precision": quantity_precision,
                        "min_order_size": lot_size,
                        "max_order_size": 1000000.0,
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                    instruments.append(instrument)
            
            return instruments
            
        except Exception as e:
            logger.error(f"Error fetching instruments from Binance: {e}")
            # Fall back to static list if API fails
            instruments = []
            for static_inst in self.INSTRUMENTS:
                instrument = {
                    "id": static_inst["symbol"],
                    **static_inst,
                    "asset_class": "CRYPTO",
                    "status": "ACTIVE",
                    "contract_type": "PERPETUAL",
                    "min_order_size": static_inst["lot_size"],
                    "max_order_size": 1000000.0,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
                instruments.append(instrument)
            return instruments
    
    async def get_quote(self, instrument_id: str) -> DerivativeQuote:
        """
        Get current quote for an instrument.
        
        Args:
            instrument_id: Instrument symbol (e.g., BTCUSDT)
            
        Returns:
            DerivativeQuote object
        """
        try:
            # Fetch 24hr ticker data
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/ticker/24hr",
                params={"symbol": instrument_id}
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Fetch premium index for mark price
            mark_price = None
            index_price = None
            try:
                premium_response = await self.client.get(
                    f"{self.BASE_URL}/fapi/v1/premiumIndex",
                    params={"symbol": instrument_id}
                )
                premium_response.raise_for_status()
                premium_data = premium_response.json()
                mark_price = float(premium_data.get('markPrice'))
                index_price = float(premium_data.get('indexPrice'))
            except Exception as e:
                logger.debug(f"Could not fetch premium index for {instrument_id}: {e}")
            
            now = datetime.now(timezone.utc)
            
            return DerivativeQuote(
                instrument_id=instrument_id,
                timestamp=now,
                last_price=float(data.get('lastPrice')),
                source=self.name,
                status=DerivativeDataStatus.LIVE,
                bid=float(data.get('bidPrice')),
                ask=float(data.get('askPrice')),
                spread=float(data.get('askPrice')) - float(data.get('bidPrice')),
                mark_price=mark_price,
                index_price=index_price,
                change_24h=float(data.get('priceChange')),
                change_percent_24h=float(data.get('priceChangePercent')),
                high_24h=float(data.get('highPrice')),
                low_24h=float(data.get('lowPrice')),
                volume_24h=float(data.get('volume')),
                open_interest=None,
                funding_rate=None,  # Fetched separately
            )
            
        except Exception as e:
            logger.error(f"Error fetching quote for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch quote: {str(e)}")
    
    async def get_historical_data(self, instrument_id: str, start: date, 
                                   end: date, interval: str = "1d") -> List[Dict[str, Any]]:
        """
        Get historical price data for an instrument.
        
        Args:
            instrument_id: Instrument symbol
            start: Start date
            end: End date
            interval: Data interval
            
        Returns:
            List of historical data dictionaries
        """
        try:
            # Map interval strings to Binance format
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d",
                "1w": "1w",
            }
            
            binance_interval = interval_map.get(interval, "1d")
            
            # Convert dates to timestamps
            start_timestamp = int(datetime.combine(start, datetime.min.time()).timestamp() * 1000)
            end_timestamp = int(datetime.combine(end, datetime.max.time()).timestamp() * 1000)
            
            # Fetch klines (candlestick data)
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/klines",
                params={
                    "symbol": instrument_id,
                    "interval": binance_interval,
                    "startTime": start_timestamp,
                    "endTime": end_timestamp,
                    "limit": 1000
                }
            )
            response.raise_for_status()
            
            klines = response.json()
            
            # Convert to list of dictionaries
            data = []
            for kline in klines:
                data.append({
                    "timestamp": datetime.fromtimestamp(kline[0] / 1000, tz=timezone.utc),
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                })
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch historical data: {str(e)}")
    
    async def get_funding_data(self, instrument_id: str) -> FundingData:
        """
        Get funding rate data for a perpetual futures instrument.
        
        Args:
            instrument_id: Instrument symbol
            
        Returns:
            FundingData object
        """
        try:
            # Fetch current funding rate
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/premiumIndex",
                params={"symbol": instrument_id}
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Calculate next funding time (Binance funds every 8 hours)
            now = datetime.now(timezone.utc)
            hours_since_midnight = (now.hour + now.minute / 60) % 8
            next_funding = now + timedelta(hours=8 - hours_since_midnight)
            
            return FundingData(
                instrument_id=instrument_id,
                current_funding_rate=float(data.get('lastFundingRate', 0)),
                predicted_funding_rate=float(data.get('markPrice', 0)) - float(data.get('indexPrice', 0)),
                next_funding_time=next_funding,
                last_funding_rate=float(data.get('lastFundingRate', 0)),
                funding_interval_hours=8,
                source=self.name,
                status=DerivativeDataStatus.LIVE
            )
            
        except Exception as e:
            logger.error(f"Error fetching funding data for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch funding data: {str(e)}")
    
    async def get_open_interest(self, instrument_id: str) -> OpenInterestData:
        """
        Get open interest data for an instrument.
        
        Args:
            instrument_id: Instrument symbol
            
        Returns:
            OpenInterestData object
        """
        try:
            # Fetch current open interest from Binance's dedicated derivatives endpoint.
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/openInterest",
                params={"symbol": instrument_id}
            )
            response.raise_for_status()
            
            data = response.json()
            
            current_oi = float(data.get('openInterest'))
            quote = await self.get_quote(instrument_id)
            oi_value = current_oi * quote.last_price
            
            return OpenInterestData(
                instrument_id=instrument_id,
                current_open_interest=current_oi,
                open_interest_value=oi_value,
                open_interest_change_24h=None,  # Not provided in this endpoint
                open_interest_change_percent_24h=None,
                source=self.name,
                status=DerivativeDataStatus.LIVE
            )
            
        except Exception as e:
            logger.error(f"Error fetching open interest for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch open interest: {str(e)}")
    
    async def get_market_depth(self, instrument_id: str, depth: int = 20) -> MarketDepth:
        """
        Get order book / market depth for an instrument.
        
        Args:
            instrument_id: Instrument symbol
            depth: Number of price levels to return
            
        Returns:
            MarketDepth object
        """
        try:
            # Fetch order book
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/depth",
                params={"symbol": instrument_id, "limit": depth}
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Process bids
            bids = []
            cumulative_bid_qty = 0
            for bid in data.get('bids', [])[:depth]:
                price = float(bid[0])
                quantity = float(bid[1])
                cumulative_bid_qty += quantity
                bids.append(MarketDepthLevel(
                    price=price,
                    quantity=quantity,
                    cumulative_quantity=cumulative_bid_qty
                ))
            
            # Process asks
            asks = []
            cumulative_ask_qty = 0
            for ask in data.get('asks', [])[:depth]:
                price = float(ask[0])
                quantity = float(ask[1])
                cumulative_ask_qty += quantity
                asks.append(MarketDepthLevel(
                    price=price,
                    quantity=quantity,
                    cumulative_quantity=cumulative_ask_qty
                ))
            
            return MarketDepth(
                instrument_id=instrument_id,
                timestamp=datetime.now(timezone.utc),
                bids=bids,
                asks=asks,
                source=self.name,
                status=DerivativeDataStatus.LIVE
            )
            
        except Exception as e:
            logger.error(f"Error fetching market depth for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch market depth: {str(e)}")
    
    async def get_historical_funding(self, instrument_id: str, start: date, 
                                      end: date) -> List[Dict[str, Any]]:
        """
        Get historical funding rate data.
        
        Args:
            instrument_id: Instrument symbol
            start: Start date
            end: End date
            
        Returns:
            List of historical funding data dictionaries
        """
        try:
            # Convert dates to timestamps
            start_timestamp = int(datetime.combine(start, datetime.min.time()).timestamp() * 1000)
            end_timestamp = int(datetime.combine(end, datetime.max.time()).timestamp() * 1000)
            
            # Fetch funding rate history
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/fundingRate",
                params={
                    "symbol": instrument_id,
                    "startTime": start_timestamp,
                    "endTime": end_timestamp,
                    "limit": 1000
                }
            )
            response.raise_for_status()
            
            funding_history = response.json()
            
            # Convert to list of dictionaries
            data = []
            for funding in funding_history:
                data.append({
                    "timestamp": datetime.fromtimestamp(funding['fundingTime'] / 1000, tz=timezone.utc),
                    "funding_rate": float(funding['fundingRate']),
                    "symbol": funding['symbol'],
                })
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching historical funding for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch historical funding: {str(e)}")
    
    async def get_historical_open_interest(self, instrument_id: str, start: date,
                                           end: date) -> List[Dict[str, Any]]:
        """
        Get historical open interest data.
        
        Args:
            instrument_id: Instrument symbol
            start: Start date
            end: End date
            
        Returns:
            List of historical open interest data dictionaries
        """
        try:
            # Convert dates to timestamps
            start_timestamp = int(datetime.combine(start, datetime.min.time()).timestamp() * 1000)
            end_timestamp = int(datetime.combine(end, datetime.max.time()).timestamp() * 1000)
            
            # Fetch open interest history
            response = await self.client.get(
                f"{self.BASE_URL}/fapi/v1/openInterest",
                params={
                    "symbol": instrument_id,
                    "period": "1d",
                    "startTime": start_timestamp,
                    "endTime": end_timestamp,
                    "limit": 500
                }
            )
            response.raise_for_status()
            
            oi_history = response.json()
            
            # Convert to list of dictionaries
            data = []
            for oi in oi_history:
                data.append({
                    "timestamp": datetime.fromtimestamp(oi['timestamp'] / 1000, tz=timezone.utc),
                    "open_interest": float(oi['sumOpenInterest']),
                    "symbol": oi['symbol'],
                })
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching historical OI for {instrument_id} from Binance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch historical OI: {str(e)}")
    
    def is_configured(self) -> bool:
        """Binance public API requires no configuration."""
        return True
