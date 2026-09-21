"""
Market microstructure service for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module calculates market microstructure metrics from order book and quote data.
"""

from datetime import datetime
from typing import Optional, Dict, Any
import logging

from ..schemas import MarketMicrostructure
from ..providers.base import DerivativeQuote, MarketDepth

logger = logging.getLogger("neural_market.derivatives.services.microstructure")


class MarketMicrostructureService:
    """
    Service for calculating market microstructure metrics.
    
    Calculates:
    - Bid/ask spread
    - Mid price
    - Spread percentage
    - Buy/sell-side depth imbalance
    - Volume imbalance
    - Price-to-mark difference
    - Liquidity score
    """
    
    @staticmethod
    def calculate_microstructure(quote: DerivativeQuote, 
                                  depth: Optional[MarketDepth] = None) -> MarketMicrostructure:
        """
        Calculate market microstructure metrics from quote and depth data.
        
        Args:
            quote: Derivative quote data
            depth: Optional market depth data
            
        Returns:
            MarketMicrostructure object with calculated metrics
        """
        try:
            # Calculate spread metrics
            bid_ask_spread = None
            mid_price = None
            spread_percent = None
            
            if quote.bid and quote.ask:
                bid_ask_spread = quote.ask - quote.bid
                mid_price = (quote.bid + quote.ask) / 2
                if mid_price > 0:
                    spread_percent = (bid_ask_spread / mid_price) * 100
            
            # Calculate depth metrics if available
            bid_depth = None
            ask_depth = None
            depth_imbalance = None
            
            if depth:
                bid_depth = sum(level.quantity for level in depth.bids)
                ask_depth = sum(level.quantity for level in depth.asks)
                
                if bid_depth + ask_depth > 0:
                    depth_imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
            
            # Calculate price-to-mark difference
            price_to_mark_diff = None
            if quote.mark_price and quote.last_price:
                price_to_mark_diff = quote.last_price - quote.mark_price
            
            # Calculate liquidity score (0-1, higher = more liquid)
            liquidity_score = MarketMicrostructureService._calculate_liquidity_score(
                quote, depth, bid_ask_spread, bid_depth, ask_depth
            )
            
            return MarketMicrostructure(
                instrument_id=quote.instrument_id,
                timestamp=datetime.utcnow(),
                bid_ask_spread=bid_ask_spread,
                mid_price=mid_price,
                spread_percent=spread_percent,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                depth_imbalance=depth_imbalance,
                volume_imbalance=None,  # Would need trade data
                price_to_mark_diff=price_to_mark_diff,
                liquidity_score=liquidity_score
            )
            
        except Exception as e:
            logger.error(f"Error calculating microstructure for {quote.instrument_id}: {e}")
            return MarketMicrostructure(
                instrument_id=quote.instrument_id,
                timestamp=datetime.utcnow(),
                bid_ask_spread=None,
                mid_price=None,
                spread_percent=None,
                bid_depth=None,
                ask_depth=None,
                depth_imbalance=None,
                volume_imbalance=None,
                price_to_mark_diff=None,
                liquidity_score=None
            )
    
    @staticmethod
    def _calculate_liquidity_score(quote: DerivativeQuote, depth: Optional[MarketDepth],
                                    spread: Optional[float], bid_depth: Optional[float],
                                    ask_depth: Optional[float]) -> Optional[float]:
        """
        Calculate liquidity score based on multiple factors.
        
        Score 0-1 based on:
        - Spread (lower is better)
        - Depth (higher is better)
        - Volume (higher is better)
        
        Returns:
            Liquidity score between 0 and 1, or None if insufficient data
        """
        try:
            score = 0.0
            factors = 0
            
            # Spread factor (0-30 points)
            if spread and quote.last_price:
                spread_pct = (spread / quote.last_price) * 100
                if spread_pct < 0.01:
                    score += 30
                elif spread_pct < 0.05:
                    score += 25
                elif spread_pct < 0.1:
                    score += 20
                elif spread_pct < 0.5:
                    score += 15
                elif spread_pct < 1.0:
                    score += 10
                else:
                    score += 5
                factors += 1
            
            # Depth factor (0-40 points)
            if bid_depth and ask_depth:
                total_depth = bid_depth + ask_depth
                if total_depth > 1000000:
                    score += 40
                elif total_depth > 500000:
                    score += 35
                elif total_depth > 100000:
                    score += 30
                elif total_depth > 50000:
                    score += 25
                elif total_depth > 10000:
                    score += 20
                elif total_depth > 1000:
                    score += 15
                else:
                    score += 10
                factors += 1
            
            # Volume factor (0-30 points)
            if quote.volume_24h:
                if quote.volume_24h > 1000000000:
                    score += 30
                elif quote.volume_24h > 500000000:
                    score += 25
                elif quote.volume_24h > 100000000:
                    score += 20
                elif quote.volume_24h > 10000000:
                    score += 15
                elif quote.volume_24h > 1000000:
                    score += 10
                else:
                    score += 5
                factors += 1
            
            # Normalize to 0-1
            if factors > 0:
                return min(score / 100.0, 1.0)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error calculating liquidity score: {e}")
            return None
    
    @staticmethod
    def calculate_order_book_imbalance(depth: MarketDepth) -> Dict[str, Any]:
        """
        Calculate detailed order book imbalance metrics.
        
        Args:
            depth: Market depth data
            
        Returns:
            Dictionary with imbalance metrics
        """
        try:
            if not depth or not depth.bids or not depth.asks:
                return {
                    "bid_depth": 0,
                    "ask_depth": 0,
                    "imbalance_ratio": 0,
                    "imbalance_percentage": 0,
                    "dominant_side": "NONE"
                }
            
            bid_depth = sum(level.quantity for level in depth.bids)
            ask_depth = sum(level.quantity for level in depth.asks)
            total_depth = bid_depth + ask_depth
            
            if total_depth == 0:
                return {
                    "bid_depth": 0,
                    "ask_depth": 0,
                    "imbalance_ratio": 0,
                    "imbalance_percentage": 0,
                    "dominant_side": "NONE"
                }
            
            imbalance_ratio = (bid_depth - ask_depth) / total_depth
            imbalance_percentage = imbalance_ratio * 100
            
            if imbalance_ratio > 0.1:
                dominant_side = "BID"
            elif imbalance_ratio < -0.1:
                dominant_side = "ASK"
            else:
                dominant_side = "BALANCED"
            
            return {
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
                "imbalance_ratio": imbalance_ratio,
                "imbalance_percentage": imbalance_percentage,
                "dominant_side": dominant_side
            }
            
        except Exception as e:
            logger.error(f"Error calculating order book imbalance: {e}")
            return {
                "bid_depth": 0,
                "ask_depth": 0,
                "imbalance_ratio": 0,
                "imbalance_percentage": 0,
                "dominant_side": "ERROR"
            }
    
    @staticmethod
    def calculate_spread_metrics(quote: DerivativeQuote) -> Dict[str, Any]:
        """
        Calculate detailed spread metrics.
        
        Args:
            quote: Derivative quote data
            
        Returns:
            Dictionary with spread metrics
        """
        try:
            if not quote.bid or not quote.ask:
                return {
                    "absolute_spread": None,
                    "percentage_spread": None,
                    "mid_price": None,
                    "spread_status": "UNAVAILABLE"
                }
            
            absolute_spread = quote.ask - quote.bid
            mid_price = (quote.bid + quote.ask) / 2
            percentage_spread = (absolute_spread / mid_price) * 100 if mid_price > 0 else None
            
            # Determine spread status
            if percentage_spread:
                if percentage_spread < 0.01:
                    spread_status = "TIGHT"
                elif percentage_spread < 0.05:
                    spread_status = "NORMAL"
                elif percentage_spread < 0.1:
                    spread_status = "WIDE"
                else:
                    spread_status = "VERY_WIDE"
            else:
                spread_status = "UNKNOWN"
            
            return {
                "absolute_spread": absolute_spread,
                "percentage_spread": percentage_spread,
                "mid_price": mid_price,
                "spread_status": spread_status
            }
            
        except Exception as e:
            logger.error(f"Error calculating spread metrics: {e}")
            return {
                "absolute_spread": None,
                "percentage_spread": None,
                "mid_price": None,
                "spread_status": "ERROR"
            }
