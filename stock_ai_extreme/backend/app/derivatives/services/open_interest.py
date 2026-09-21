"""
Open interest analytics service for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides open interest analytics and correlation analysis for derivative instruments.
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import logging
import pandas as pd

from ..schemas import OpenInterestData
from ..providers.base import OpenInterestData as ProviderOpenInterestData

logger = logging.getLogger("neural_market.derivatives.services.open_interest")


class OpenInterestAnalyticsService:
    """
    Service for open interest analytics.
    
    Provides:
    - Current open interest analysis
    - Historical open interest trends
    - Open interest vs price correlation
    - Market sentiment analysis from OI changes
    """
    
    @staticmethod
    def analyze_oi_trend(historical_oi: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze open interest trends from historical data.
        
        Args:
            historical_oi: List of historical open interest data dictionaries
            
        Returns:
            Dictionary with trend analysis
        """
        try:
            if not historical_oi:
                return {
                    "trend": "NO_DATA",
                    "average_oi": None,
                    "min_oi": None,
                    "max_oi": None,
                    "oi_change": None,
                    "oi_change_percent": None,
                    "direction": "UNKNOWN"
                }
            
            # Convert to DataFrame for analysis
            df = pd.DataFrame(historical_oi)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            oi_values = df['open_interest'].dropna()
            
            if len(oi_values) == 0:
                return {
                    "trend": "NO_DATA",
                    "average_oi": None,
                    "min_oi": None,
                    "max_oi": None,
                    "oi_change": None,
                    "oi_change_percent": None,
                    "direction": "UNKNOWN"
                }
            
            # Calculate statistics
            average_oi = oi_values.mean()
            min_oi = oi_values.min()
            max_oi = oi_values.max()
            
            # Calculate change
            if len(oi_values) >= 2:
                oi_change = oi_values.iloc[-1] - oi_values.iloc[0]
                oi_change_percent = (oi_change / oi_values.iloc[0]) * 100 if oi_values.iloc[0] != 0 else None
                recent_change = oi_values.iloc[-1] - oi_values.iloc[-min(5, len(oi_values))]
            else:
                oi_change = None
                oi_change_percent = None
                recent_change = None
            
            # Determine direction
            if recent_change is not None:
                if recent_change > 0:
                    direction = "INCREASING"
                elif recent_change < 0:
                    direction = "DECREASING"
                else:
                    direction = "STABLE"
            else:
                direction = "UNKNOWN"
            
            # Determine overall trend
            if len(oi_values) >= 3:
                # Simple linear regression slope
                x = range(len(oi_values))
                slope = pd.Series(oi_values).values.cov(pd.Series(x)) / pd.Series(x).var()
                if slope > 0:
                    trend = "UPTREND"
                elif slope < 0:
                    trend = "DOWNTREND"
                else:
                    trend = "SIDEWAYS"
            else:
                trend = "INSUFFICIENT_DATA"
            
            return {
                "trend": trend,
                "average_oi": float(average_oi) if pd.notna(average_oi) else None,
                "min_oi": float(min_oi) if pd.notna(min_oi) else None,
                "max_oi": float(max_oi) if pd.notna(max_oi) else None,
                "oi_change": float(oi_change) if oi_change is not None else None,
                "oi_change_percent": float(oi_change_percent) if oi_change_percent is not None else None,
                "recent_change": float(recent_change) if recent_change is not None else None,
                "direction": direction,
                "data_points": len(oi_values)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing OI trend: {e}")
            return {
                "trend": "ERROR",
                "average_oi": None,
                "min_oi": None,
                "max_oi": None,
                "oi_change": None,
                "oi_change_percent": None,
                "direction": "ERROR"
            }
    
    @staticmethod
    def analyze_price_oi_correlation(historical_data: List[Dict[str, Any]], 
                                    historical_oi: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze correlation between price changes and open interest changes.
        
        This is educational analytics - not guaranteed predictive power.
        
        Args:
            historical_data: Historical price data
            historical_oi: Historical open interest data
            
        Returns:
            Dictionary with correlation analysis
        """
        try:
            if not historical_data or not historical_oi:
                return {
                    "correlation": None,
                    "interpretation": "INSUFFICIENT_DATA",
                    "price_trend": "UNKNOWN",
                    "oi_trend": "UNKNOWN",
                    "combined_signal": "UNKNOWN"
                }
            
            # Convert to DataFrames
            price_df = pd.DataFrame(historical_data)
            price_df['timestamp'] = pd.to_datetime(price_df['timestamp'])
            price_df = price_df.sort_values('timestamp')
            
            oi_df = pd.DataFrame(historical_oi)
            oi_df['timestamp'] = pd.to_datetime(oi_df['timestamp'])
            oi_df = oi_df.sort_values('timestamp')
            
            # Calculate price changes
            if 'close' in price_df.columns:
                price_df['price_change'] = price_df['close'].pct_change()
            elif 'last_price' in price_df.columns:
                price_df['price_change'] = price_df['last_price'].pct_change()
            else:
                return {
                    "correlation": None,
                    "interpretation": "NO_PRICE_DATA",
                    "price_trend": "UNKNOWN",
                    "oi_trend": "UNKNOWN",
                    "combined_signal": "UNKNOWN"
                }
            
            # Calculate OI changes
            oi_df['oi_change'] = oi_df['open_interest'].pct_change()
            
            # Merge on timestamp (approximate match)
            merged = pd.merge_asof(
                price_df[['timestamp', 'price_change']],
                oi_df[['timestamp', 'oi_change']],
                on='timestamp',
                direction='nearest'
            )
            
            # Drop NaN values
            merged = merged.dropna()
            
            if len(merged) < 3:
                return {
                    "correlation": None,
                    "interpretation": "INSUFFICIENT_DATA_POINTS",
                    "price_trend": "UNKNOWN",
                    "oi_trend": "UNKNOWN",
                    "combined_signal": "UNKNOWN"
                }
            
            # Calculate correlation
            correlation = merged['price_change'].corr(merged['oi_change'])
            
            # Determine trends
            price_trend = "UP" if merged['price_change'].mean() > 0 else "DOWN"
            oi_trend = "UP" if merged['oi_change'].mean() > 0 else "DOWN"
            
            # Interpret correlation
            if correlation is None or pd.isna(correlation):
                interpretation = "NO_CORRELATION"
                combined_signal = "UNKNOWN"
            elif correlation > 0.3:
                interpretation = "STRONG_POSITIVE"
                # Price up + OI up = bullish (new money entering)
                # Price down + OI down = bearish (position closing)
                if price_trend == "UP" and oi_trend == "UP":
                    combined_signal = "BULLISH_STRENGTH"
                elif price_trend == "DOWN" and oi_trend == "DOWN":
                    combined_signal = "BEARISH_WEAKNESS"
                else:
                    combined_signal = "MIXED"
            elif correlation > 0.1:
                interpretation = "MODERATE_POSITIVE"
                combined_signal = "SLIGHTLY_BULLISH" if price_trend == "UP" else "SLIGHTLY_BEARISH"
            elif correlation < -0.3:
                interpretation = "STRONG_NEGATIVE"
                # Price up + OI down = short covering (bearish reversal signal)
                # Price down + OI up = new shorting (bearish continuation)
                if price_trend == "UP" and oi_trend == "DOWN":
                    combined_signal = "SHORT_COVERING"
                elif price_trend == "DOWN" and oi_trend == "UP":
                    combined_signal = "NEW_SHORTING"
                else:
                    combined_signal = "MIXED"
            elif correlation < -0.1:
                interpretation = "MODERATE_NEGATIVE"
                combined_signal = "POTENTIAL_REVERSAL"
            else:
                interpretation = "NO_SIGNIFICANT_CORRELATION"
                combined_signal = "NEUTRAL"
            
            return {
                "correlation": float(correlation) if correlation is not None and pd.notna(correlation) else None,
                "interpretation": interpretation,
                "price_trend": price_trend,
                "oi_trend": oi_trend,
                "combined_signal": combined_signal,
                "data_points": len(merged),
                "disclaimer": "Educational analytics only - not guaranteed predictive power"
            }
            
        except Exception as e:
            logger.error(f"Error analyzing price-OI correlation: {e}")
            return {
                "correlation": None,
                "interpretation": "ERROR",
                "price_trend": "UNKNOWN",
                "oi_trend": "UNKNOWN",
                "combined_signal": "ERROR"
            }
    
    @staticmethod
    def analyze_oi_sentiment(historical_oi: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze market sentiment from open interest changes.
        
        Args:
            historical_oi: List of historical open interest data
            
        Returns:
            Dictionary with sentiment analysis
        """
        try:
            if not historical_oi:
                return {
                    "sentiment": "NO_DATA",
                    "confidence": 0,
                    "accumulation_rate": None,
                    "distribution_rate": None
                }
            
            df = pd.DataFrame(historical_oi)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            oi_values = df['open_interest'].dropna()
            
            if len(oi_values) < 2:
                return {
                    "sentiment": "INSUFFICIENT_DATA",
                    "confidence": 0,
                    "accumulation_rate": None,
                    "distribution_rate": None
                }
            
            # Calculate changes
            oi_changes = oi_values.diff().dropna()
            
            # Count accumulation vs distribution periods
            accumulation_periods = (oi_changes > 0).sum()
            distribution_periods = (oi_changes < 0).sum()
            total_periods = len(oi_changes)
            
            # Calculate rates
            accumulation_rate = accumulation_periods / total_periods if total_periods > 0 else 0
            distribution_rate = distribution_periods / total_periods if total_periods > 0 else 0
            
            # Determine sentiment
            if accumulation_rate > 0.6:
                sentiment = "ACCUMULATION"  # Positions being built
                confidence = accumulation_rate
            elif distribution_rate > 0.6:
                sentiment = "DISTRIBUTION"  # Positions being closed
                confidence = distribution_rate
            else:
                sentiment = "NEUTRAL"
                confidence = max(accumulation_rate, distribution_rate)
            
            return {
                "sentiment": sentiment,
                "confidence": float(confidence),
                "accumulation_rate": float(accumulation_rate),
                "distribution_rate": float(distribution_rate),
                "total_periods": int(total_periods)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing OI sentiment: {e}")
            return {
                "sentiment": "ERROR",
                "confidence": 0,
                "accumulation_rate": None,
                "distribution_rate": None
            }
    
    @staticmethod
    def enhance_oi_data(provider_data: ProviderOpenInterestData,
                       historical_oi: Optional[List[Dict[str, Any]]] = None) -> OpenInterestData:
        """
        Enhance provider open interest data with analytics.
        
        Args:
            provider_data: Raw OI data from provider
            historical_oi: Optional historical OI data for trend analysis
            
        Returns:
            Enhanced OpenInterestData object
        """
        try:
            # Calculate 24h change if historical data available
            oi_change_24h = None
            oi_change_percent_24h = None
            
            if historical_oi and len(historical_oi) >= 2:
                df = pd.DataFrame(historical_oi)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.sort_values('timestamp')
                
                recent_oi = df['open_interest'].iloc[-1]
                previous_oi = df['open_interest'].iloc[-2]
                
                if recent_oi is not None and previous_oi is not None and previous_oi != 0:
                    oi_change_24h = recent_oi - previous_oi
                    oi_change_percent_24h = (oi_change_24h / previous_oi) * 100
            
            # Build enhanced OI data
            enhanced_data = OpenInterestData(
                instrument_id=provider_data.instrument_id,
                current_open_interest=provider_data.current_open_interest,
                open_interest_value=provider_data.open_interest_value,
                open_interest_change_24h=oi_change_24h,
                open_interest_change_percent_24h=oi_change_percent_24h,
                historical_oi=historical_oi or [],
                source=provider_data.source,
                data_mode=provider_data.status.value if hasattr(provider_data, 'status') else "LIVE"
            )
            
            return enhanced_data
            
        except Exception as e:
            logger.error(f"Error enhancing OI data: {e}")
            # Return original data if enhancement fails
            return OpenInterestData(
                instrument_id=provider_data.instrument_id,
                current_open_interest=provider_data.current_open_interest,
                open_interest_value=provider_data.open_interest_value,
                open_interest_change_24h=None,
                open_interest_change_percent_24h=None,
                historical_oi=[],
                source=provider_data.source,
                data_mode="LIVE"
            )
