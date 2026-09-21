"""
YFinance provider for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This provider uses yfinance to fetch real market data for derivatives including futures and crypto.
YFinance provides legitimate market data from Yahoo Finance without requiring API keys.
"""

from datetime import datetime, date, timezone, timedelta
from typing import List, Dict, Any, Optional
import yfinance as yf
import pandas as pd
import logging

from .base import (
    DerivativeDataProvider, DerivativeQuote, MarketDepth, MarketDepthLevel,
    FundingData, OpenInterestData, DerivativeProviderError, DerivativeDataStatus
)

logger = logging.getLogger("neural_market.derivatives.providers.yfinance")


class YFinanceDerivativesProvider(DerivativeDataProvider):
    """
    YFinance-based derivatives data provider.
    
    Provides real market data for:
    - Commodity futures (GC=F, SI=F, CL=F, etc.)
    - Index futures (ES=F, NQ=F, YM=F, etc.)
    - Crypto futures (BTC-USD, ETH-USD, etc.)
    - Some stock futures where available
    
    All data is sourced from Yahoo Finance, a legitimate market data provider.
    """
    
    name = "yfinance"
    
    # Instrument mappings for common derivatives
    INSTRUMENTS = {
        "CRYPTO": [
            {"symbol": "BTC-USD", "display_name": "Bitcoin US Dollar", "underlying": "BTC", 
             "quote_currency": "USD", "exchange": "CRYPTO", "tick_size": 0.01, 
             "lot_size": 0.0001, "price_precision": 2, "quantity_precision": 8},
            {"symbol": "ETH-USD", "display_name": "Ethereum US Dollar", "underlying": "ETH",
             "quote_currency": "USD", "exchange": "CRYPTO", "tick_size": 0.01,
             "lot_size": 0.0001, "price_precision": 2, "quantity_precision": 8},
            {"symbol": "BNB-USD", "display_name": "Binance Coin US Dollar", "underlying": "BNB",
             "quote_currency": "USD", "exchange": "CRYPTO", "tick_size": 0.01,
             "lot_size": 0.0001, "price_precision": 2, "quantity_precision": 8},
            {"symbol": "SOL-USD", "display_name": "Solana US Dollar", "underlying": "SOL",
             "quote_currency": "USD", "exchange": "CRYPTO", "tick_size": 0.01,
             "lot_size": 0.0001, "price_precision": 2, "quantity_precision": 8},
            {"symbol": "XRP-USD", "display_name": "XRP US Dollar", "underlying": "XRP",
             "quote_currency": "USD", "exchange": "CRYPTO", "tick_size": 0.0001,
             "lot_size": 0.0001, "price_precision": 4, "quantity_precision": 8},
        ],
        "COMMODITIES": [
            {"symbol": "GC=F", "display_name": "Gold Futures", "underlying": "Gold",
             "quote_currency": "USD", "exchange": "COMEX", "tick_size": 0.1,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
            {"symbol": "SI=F", "display_name": "Silver Futures", "underlying": "Silver",
             "quote_currency": "USD", "exchange": "COMEX", "tick_size": 0.005,
             "lot_size": 1, "price_precision": 3, "quantity_precision": 0},
            {"symbol": "CL=F", "display_name": "Crude Oil Futures", "underlying": "Crude Oil",
             "quote_currency": "USD", "exchange": "NYMEX", "tick_size": 0.01,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
            {"symbol": "NG=F", "display_name": "Natural Gas Futures", "underlying": "Natural Gas",
             "quote_currency": "USD", "exchange": "NYMEX", "tick_size": 0.001,
             "lot_size": 1, "price_precision": 3, "quantity_precision": 0},
        ],
        "INDICES": [
            {"symbol": "ES=F", "display_name": "S&P 500 Futures", "underlying": "S&P 500",
             "quote_currency": "USD", "exchange": "CME", "tick_size": 0.25,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
            {"symbol": "NQ=F", "display_name": "Nasdaq 100 Futures", "underlying": "Nasdaq 100",
             "quote_currency": "USD", "exchange": "CME", "tick_size": 0.25,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
            {"symbol": "YM=F", "display_name": "Dow Jones Futures", "underlying": "Dow Jones",
             "quote_currency": "USD", "exchange": "CBOT", "tick_size": 1,
             "lot_size": 1, "price_precision": 0, "quantity_precision": 0},
            {"symbol": "RTY=F", "display_name": "Russell 2000 Futures", "underlying": "Russell 2000",
             "quote_currency": "USD", "exchange": "CME", "tick_size": 0.1,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
        ],
        "STOCKS": [
            {"symbol": "AAPL", "display_name": "Apple Inc.", "underlying": "AAPL",
             "quote_currency": "USD", "exchange": "NASDAQ", "tick_size": 0.01,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
            {"symbol": "MSFT", "display_name": "Microsoft Corporation", "underlying": "MSFT",
             "quote_currency": "USD", "exchange": "NASDAQ", "tick_size": 0.01,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
            {"symbol": "GOOGL", "display_name": "Alphabet Inc.", "underlying": "GOOGL",
             "quote_currency": "USD", "exchange": "NASDAQ", "tick_size": 0.01,
             "lot_size": 1, "price_precision": 2, "quantity_precision": 0},
        ]
    }
    
    def __init__(self, max_retries: int = 3, timeout: int = 30):
        """
        Initialize YFinance provider.
        
        Args:
            max_retries: Maximum number of retry attempts
            timeout: Request timeout in seconds
        """
        self.max_retries = max_retries
        self.timeout = timeout
    
    async def get_instruments(self, asset_class: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get available derivative instruments.
        
        Args:
            asset_class: Optional filter by asset class
            
        Returns:
            List of instrument dictionaries
        """
        try:
            if asset_class:
                instruments = self.INSTRUMENTS.get(asset_class.upper(), [])
            else:
                # Return all instruments
                instruments = []
                for asset_class_instruments in self.INSTRUMENTS.values():
                    instruments.extend(asset_class_instruments)
            
            # Add metadata
            for instrument in instruments:
                instrument["id"] = instrument["symbol"]
                instrument["asset_class"] = self._get_asset_class_for_symbol(instrument["symbol"])
                instrument["status"] = "ACTIVE"
                instrument["contract_type"] = "FUTURE" if "=F" in instrument["symbol"] else "SPOT"
                instrument["min_order_size"] = instrument["lot_size"]
                instrument["max_order_size"] = 1000000.0
                instrument["created_at"] = datetime.now(timezone.utc)
                instrument["updated_at"] = datetime.now(timezone.utc)
            
            return instruments
            
        except Exception as e:
            logger.error(f"Error fetching instruments from YFinance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch instruments: {str(e)}")
    
    def _get_asset_class_for_symbol(self, symbol: str) -> str:
        """Determine asset class from symbol."""
        if "=F" in symbol:
            if symbol in ["GC=F", "SI=F", "CL=F", "NG=F"]:
                return "COMMODITIES"
            elif symbol in ["ES=F", "NQ=F", "YM=F", "RTY=F"]:
                return "INDICES"
        elif "-USD" in symbol:
            return "CRYPTO"
        return "STOCKS"
    
    async def get_quote(self, instrument_id: str) -> DerivativeQuote:
        """
        Get current quote for an instrument.
        
        Args:
            instrument_id: Instrument symbol
            
        Returns:
            DerivativeQuote object
        """
        try:
            ticker = yf.Ticker(instrument_id)
            info = ticker.info
            
            if not info or 'regularMarketPrice' not in info:
                raise DerivativeProviderError(self.name, f"No data available for {instrument_id}")
            
            now = datetime.now(timezone.utc)
            last_price = info.get('regularMarketPrice')
            previous_close = info.get('previousClose')
            
            # Calculate 24h change
            change_24h = None
            change_percent_24h = None
            if previous_close and last_price:
                change_24h = last_price - previous_close
                change_percent_24h = (change_24h / previous_close) * 100 if previous_close != 0 else None
            
            # Get recent data for high/low/volume
            hist = ticker.history(period="2d", interval="1d")
            high_24h = None
            low_24h = None
            volume_24h = None
            
            if not hist.empty:
                latest = hist.iloc[-1]
                high_24h = latest.get('High')
                low_24h = latest.get('Low')
                volume_24h = latest.get('Volume')
            
            # Determine data status based on data freshness
            status = self._determine_data_status(info)
            
            return DerivativeQuote(
                instrument_id=instrument_id,
                timestamp=now,
                last_price=last_price,
                source=self.name,
                status=status,
                bid=info.get('bid'),
                ask=info.get('ask'),
                spread=self._calculate_spread(info.get('bid'), info.get('ask')),
                mark_price=last_price,  # YFinance doesn't provide separate mark price
                index_price=None,  # Not available from YFinance
                change_24h=change_24h,
                change_percent_24h=change_percent_24h,
                high_24h=high_24h,
                low_24h=low_24h,
                volume_24h=volume_24h,
                open_interest=None,  # Not available from YFinance
                funding_rate=None,  # Not available from YFinance
            )
            
        except Exception as e:
            logger.error(f"Error fetching quote for {instrument_id} from YFinance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch quote: {str(e)}")
    
    def _determine_data_status(self, info: Dict[str, Any]) -> DerivativeDataStatus:
        """Determine data status based on info metadata."""
        # Check if market is open
        market_state = info.get('marketState', 'CLOSED')
        if market_state == 'REGULAR':
            return DerivativeDataStatus.LIVE
        elif market_state in ['PRE', 'POST']:
            return DerivativeDataStatus.RECENT
        else:
            return DerivativeDataStatus.DELAYED
    
    def _calculate_spread(self, bid: Optional[float], ask: Optional[float]) -> Optional[float]:
        """Calculate spread from bid and ask."""
        if bid and ask:
            return ask - bid
        return None
    
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
            ticker = yf.Ticker(instrument_id)
            
            # Map interval strings to yfinance format
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "4h": "1h",  # YFinance doesn't have 4h, use 1h
                "1d": "1d",
                "1w": "1wk",
                "1M": "1mo"
            }
            
            yf_interval = interval_map.get(interval, "1d")
            
            # Calculate period for yfinance
            days_diff = (end - start).days
            if days_diff <= 7:
                period = "1wk"
            elif days_diff <= 30:
                period = "1mo"
            elif days_diff <= 90:
                period = "3mo"
            elif days_diff <= 180:
                period = "6mo"
            elif days_diff <= 365:
                period = "1y"
            else:
                period = "max"
            
            hist = ticker.history(period=period, interval=yf_interval)
            
            if hist.empty:
                return []
            
            # Filter by date range
            hist = hist[(hist.index.date >= start) & (hist.index.date <= end)]
            
            # Convert to list of dictionaries
            data = []
            for timestamp, row in hist.iterrows():
                data.append({
                    "timestamp": timestamp.to_pydatetime(),
                    "open": row.get('Open'),
                    "high": row.get('High'),
                    "low": row.get('Low'),
                    "close": row.get('Close'),
                    "volume": row.get('Volume'),
                })
            
            return data
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {instrument_id} from YFinance: {e}")
            raise DerivativeProviderError(self.name, f"Failed to fetch historical data: {str(e)}")
    
    async def get_funding_data(self, instrument_id: str) -> FundingData:
        """
        Get funding rate data.
        
        YFinance does not provide funding rates, so this returns None values
        with appropriate status.
        """
        return FundingData(
            instrument_id=instrument_id,
            current_funding_rate=None,
            predicted_funding_rate=None,
            next_funding_time=None,
            last_funding_rate=None,
            funding_interval_hours=None,
            source=self.name,
            status=DerivativeDataStatus.UNAVAILABLE
        )
    
    async def get_open_interest(self, instrument_id: str) -> OpenInterestData:
        """
        Get open interest data.
        
        YFinance does not provide open interest, so this returns None values
        with appropriate status.
        """
        return OpenInterestData(
            instrument_id=instrument_id,
            current_open_interest=None,
            open_interest_value=None,
            open_interest_change_24h=None,
            open_interest_change_percent_24h=None,
            source=self.name,
            status=DerivativeDataStatus.UNAVAILABLE
        )
    
    async def get_market_depth(self, instrument_id: str, depth: int = 20) -> MarketDepth:
        """
        Get order book / market depth.
        
        YFinance does not provide order book data, so this raises an error.
        """
        raise DerivativeProviderError(self.name, "Market depth not supported by YFinance")
    
    def is_configured(self) -> bool:
        """YFinance requires no configuration, always available."""
        return True
