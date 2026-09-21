"""
Funding analytics service for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides funding rate analytics and trend analysis for perpetual futures.
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import logging
import pandas as pd

from ..schemas import FundingData
from ..providers.base import FundingData as ProviderFundingData

logger = logging.getLogger("neural_market.derivatives.services.funding")


class FundingAnalyticsService:
    """
    Service for funding rate analytics.
    
    Provides:
    - Current funding rate analysis
    - Historical funding trends
    - Funding rate predictions
    - Funding rate impact analysis
    """
    
    @staticmethod
    def analyze_funding_trend(historical_funding: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze funding rate trends from historical data.
        
        Args:
            historical_funding: List of historical funding data dictionaries
            
        Returns:
            Dictionary with trend analysis
        """
        try:
            if not historical_funding:
                return {
                    "trend": "NO_DATA",
                    "average_rate": None,
                    "min_rate": None,
                    "max_rate": None,
                    "std_dev": None,
                    "rate_of_change": None,
                    "direction": "UNKNOWN"
                }
            
            # Convert to DataFrame for analysis
            df = pd.DataFrame(historical_funding)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            rates = df['funding_rate'].dropna()
            
            if len(rates) == 0:
                return {
                    "trend": "NO_DATA",
                    "average_rate": None,
                    "min_rate": None,
                    "max_rate": None,
                    "std_dev": None,
                    "rate_of_change": None,
                    "direction": "UNKNOWN"
                }
            
            # Calculate statistics
            average_rate = rates.mean()
            min_rate = rates.min()
            max_rate = rates.max()
            std_dev = rates.std()
            
            # Calculate rate of change
            if len(rates) >= 2:
                rate_of_change = rates.iloc[-1] - rates.iloc[0]
                recent_change = rates.iloc[-1] - rates.iloc[-min(5, len(rates))]
            else:
                rate_of_change = None
                recent_change = None
            
            # Determine trend direction
            if recent_change is not None:
                if recent_change > 0.0001:
                    direction = "RISING"
                elif recent_change < -0.0001:
                    direction = "FALLING"
                else:
                    direction = "STABLE"
            else:
                direction = "UNKNOWN"
            
            # Determine overall trend
            if len(rates) >= 3:
                # Simple linear regression slope
                x = range(len(rates))
                slope = pd.Series(rates).values.cov(pd.Series(x)) / pd.Series(x).var()
                if slope > 0.00001:
                    trend = "UPTREND"
                elif slope < -0.00001:
                    trend = "DOWNTREND"
                else:
                    trend = "SIDEWAYS"
            else:
                trend = "INSUFFICIENT_DATA"
            
            return {
                "trend": trend,
                "average_rate": float(average_rate) if pd.notna(average_rate) else None,
                "min_rate": float(min_rate) if pd.notna(min_rate) else None,
                "max_rate": float(max_rate) if pd.notna(max_rate) else None,
                "std_dev": float(std_dev) if pd.notna(std_dev) else None,
                "rate_of_change": float(rate_of_change) if rate_of_change is not None else None,
                "recent_change": float(recent_change) if recent_change is not None else None,
                "direction": direction,
                "data_points": len(rates)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing funding trend: {e}")
            return {
                "trend": "ERROR",
                "average_rate": None,
                "min_rate": None,
                "max_rate": None,
                "std_dev": None,
                "rate_of_change": None,
                "direction": "ERROR"
            }
    
    @staticmethod
    def calculate_funding_impact(funding_rate: float, position_size: float, 
                                hours: int = 8) -> Dict[str, Any]:
        """
        Calculate funding impact on a position.
        
        This is for educational analysis only - not trading advice.
        
        Args:
            funding_rate: Current funding rate (as decimal, e.g., 0.0001 for 0.01%)
            position_size: Position size in base currency
            hours: Number of hours to calculate impact for
            
        Returns:
            Dictionary with funding impact calculations
        """
        try:
            if funding_rate is None or position_size is None:
                return {
                    "hourly_funding": None,
                    "total_funding": None,
                    "funding_percentage": None,
                    "impact_direction": "NONE"
                }
            
            # Calculate hourly funding
            hourly_funding = position_size * funding_rate
            
            # Calculate total funding for specified hours
            total_funding = hourly_funding * hours
            
            # Calculate as percentage of position
            funding_percentage = (total_funding / position_size) * 100 if position_size != 0 else None
            
            # Determine impact direction
            if total_funding > 0:
                impact_direction = "PAY"  # Longs pay shorts
            elif total_funding < 0:
                impact_direction = "RECEIVE"  # Longs receive from shorts
            else:
                impact_direction = "NEUTRAL"
            
            return {
                "hourly_funding": float(hourly_funding),
                "total_funding": float(total_funding),
                "funding_percentage": float(funding_percentage) if funding_percentage is not None else None,
                "impact_direction": impact_direction,
                "disclaimer": "Educational calculation only - not trading advice"
            }
            
        except Exception as e:
            logger.error(f"Error calculating funding impact: {e}")
            return {
                "hourly_funding": None,
                "total_funding": None,
                "funding_percentage": None,
                "impact_direction": "ERROR"
            }
    
    @staticmethod
    def analyze_funding_regime(historical_funding: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze funding rate regime (bullish/bearish/neutral).
        
        Args:
            historical_funding: List of historical funding data
            
        Returns:
            Dictionary with regime analysis
        """
        try:
            if not historical_funding:
                return {
                    "regime": "NO_DATA",
                    "confidence": 0,
                    "average_abs_rate": None,
                    "positive_periods": 0,
                    "negative_periods": 0,
                    "neutral_periods": 0
                }
            
            df = pd.DataFrame(historical_funding)
            rates = df['funding_rate'].dropna()
            
            if len(rates) == 0:
                return {
                    "regime": "NO_DATA",
                    "confidence": 0,
                    "average_abs_rate": None,
                    "positive_periods": 0,
                    "negative_periods": 0,
                    "neutral_periods": 0
                }
            
            # Count periods by sign
            positive_periods = (rates > 0.00001).sum()
            negative_periods = (rates < -0.00001).sum()
            neutral_periods = len(rates) - positive_periods - negative_periods
            
            # Calculate average absolute rate
            average_abs_rate = rates.abs().mean()
            
            # Determine regime
            total_periods = len(rates)
            if positive_periods / total_periods > 0.6:
                regime = "BULLISH"  # Positive funding = longs pay shorts = bullish sentiment
                confidence = positive_periods / total_periods
            elif negative_periods / total_periods > 0.6:
                regime = "BEARISH"  # Negative funding = longs receive = bearish sentiment
                confidence = negative_periods / total_periods
            else:
                regime = "NEUTRAL"
                confidence = max(positive_periods, negative_periods) / total_periods
            
            return {
                "regime": regime,
                "confidence": float(confidence),
                "average_abs_rate": float(average_abs_rate) if pd.notna(average_abs_rate) else None,
                "positive_periods": int(positive_periods),
                "negative_periods": int(negative_periods),
                "neutral_periods": int(neutral_periods),
                "total_periods": int(total_periods)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing funding regime: {e}")
            return {
                "regime": "ERROR",
                "confidence": 0,
                "average_abs_rate": None,
                "positive_periods": 0,
                "negative_periods": 0,
                "neutral_periods": 0
            }
    
    @staticmethod
    def enhance_funding_data(provider_data: ProviderFundingData, 
                            historical_funding: Optional[List[Dict[str, Any]]] = None) -> FundingData:
        """
        Enhance provider funding data with analytics.
        
        Args:
            provider_data: Raw funding data from provider
            historical_funding: Optional historical funding data for trend analysis
            
        Returns:
            Enhanced FundingData object
        """
        try:
            # Calculate trend if historical data available
            trend_analysis = None
            if historical_funding:
                trend_analysis = FundingAnalyticsService.analyze_funding_trend(historical_funding)
            
            # Build enhanced funding data
            enhanced_data = FundingData(
                instrument_id=provider_data.instrument_id,
                current_funding_rate=provider_data.current_funding_rate,
                predicted_funding_rate=provider_data.predicted_funding_rate,
                next_funding_time=provider_data.next_funding_time,
                last_funding_rate=provider_data.last_funding_rate,
                funding_interval_hours=provider_data.funding_interval_hours,
                historical_rates=historical_funding or [],
                source=provider_data.source,
                data_mode=provider_data.status.value if hasattr(provider_data, 'status') else "LIVE"
            )
            
            return enhanced_data
            
        except Exception as e:
            logger.error(f"Error enhancing funding data: {e}")
            # Return original data if enhancement fails
            return FundingData(
                instrument_id=provider_data.instrument_id,
                current_funding_rate=provider_data.current_funding_rate,
                predicted_funding_rate=provider_data.predicted_funding_rate,
                next_funding_time=provider_data.next_funding_time,
                last_funding_rate=provider_data.last_funding_rate,
                funding_interval_hours=provider_data.funding_interval_hours,
                historical_rates=[],
                source=provider_data.source,
                data_mode="LIVE"
            )
