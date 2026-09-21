"""
Advanced analytics service for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides advanced statistical analytics using NumPy, Pandas, and SciPy.
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import logging
import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import norm

from ..schemas import AdvancedAnalytics

logger = logging.getLogger("neural_market.derivatives.services.analytics")


class DerivativesAnalyticsService:
    """
    Service for advanced derivatives analytics.
    
    Provides:
    - Volatility calculations
    - Returns analysis
    - Moving averages
    - Drawdown analysis
    - Correlation analysis
    - Z-score calculations
    - Volume anomaly detection
    - Technical indicators
    """
    
    @staticmethod
    def calculate_advanced_analytics(historical_data: List[Dict[str, Any]]) -> AdvancedAnalytics:
        """
        Calculate comprehensive advanced analytics from historical data.
        
        Args:
            historical_data: List of historical price data dictionaries
            
        Returns:
            AdvancedAnalytics object with calculated metrics
        """
        try:
            if not historical_data or len(historical_data) < 2:
                return AdvancedAnalytics(
                    instrument_id="unknown",
                    timestamp=datetime.utcnow(),
                    volatility=None,
                    returns_mean=None,
                    returns_std=None,
                    rolling_volatility_7d=None,
                    rolling_volatility_30d=None,
                    moving_average_7d=None,
                    moving_average_30d=None,
                    max_drawdown=None,
                    sharpe_ratio=None,
                    sortino_ratio=None,
                    z_score=None,
                    volume_anomaly_score=None,
                    price_momentum=None,
                    rsi=None,
                    bollinger_upper=None,
                    bollinger_lower=None,
                    bollinger_middle=None
                )
            
            # Convert to DataFrame
            df = pd.DataFrame(historical_data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            # Get price column
            if 'close' in df.columns:
                price_col = 'close'
            elif 'last_price' in df.columns:
                price_col = 'last_price'
            else:
                raise ValueError("No price column found in historical data")
            
            prices = df[price_col].dropna()
            
            if len(prices) < 2:
                return AdvancedAnalytics(
                    instrument_id="unknown",
                    timestamp=datetime.utcnow(),
                    volatility=None,
                    returns_mean=None,
                    returns_std=None,
                    rolling_volatility_7d=None,
                    rolling_volatility_30d=None,
                    moving_average_7d=None,
                    moving_average_30d=None,
                    max_drawdown=None,
                    sharpe_ratio=None,
                    sortino_ratio=None,
                    z_score=None,
                    volume_anomaly_score=None,
                    price_momentum=None,
                    rsi=None,
                    bollinger_upper=None,
                    bollinger_lower=None,
                    bollinger_middle=None
                )
            
            # Calculate returns
            returns = prices.pct_change().dropna()
            
            # Calculate basic statistics
            volatility = returns.std() * np.sqrt(252) if len(returns) > 0 else None  # Annualized
            returns_mean = returns.mean()
            returns_std = returns.std()
            
            # Calculate rolling volatility
            rolling_vol_7d = None
            rolling_vol_30d = None
            if len(returns) >= 7:
                rolling_vol_7d = returns.rolling(window=7).std().iloc[-1] * np.sqrt(252)
            if len(returns) >= 30:
                rolling_vol_30d = returns.rolling(window=30).std().iloc[-1] * np.sqrt(252)
            
            # Calculate moving averages
            ma_7d = prices.rolling(window=7).mean().iloc[-1] if len(prices) >= 7 else None
            ma_30d = prices.rolling(window=30).mean().iloc[-1] if len(prices) >= 30 else None
            
            # Calculate max drawdown
            max_drawdown = DerivativesAnalyticsService._calculate_max_drawdown(prices)
            
            # Calculate Sharpe ratio (assuming 0% risk-free rate for simplicity)
            sharpe_ratio = (returns_mean / returns_std * np.sqrt(252)) if returns_std > 0 else None
            
            # Calculate Sortino ratio
            sortino_ratio = DerivativesAnalyticsService._calculate_sortino_ratio(returns)
            
            # Calculate Z-score of current price
            z_score = DerivativesAnalyticsService._calculate_z_score(prices)
            
            # Calculate volume anomaly score
            volume_anomaly_score = None
            if 'volume' in df.columns:
                volume_anomaly_score = DerivativesAnalyticsService._calculate_volume_anomaly(df['volume'])
            
            # Calculate price momentum
            price_momentum = DerivativesAnalyticsService._calculate_momentum(prices)
            
            # Calculate RSI
            rsi = DerivativesAnalyticsService._calculate_rsi(prices)
            
            # Calculate Bollinger Bands
            bollinger_upper, bollinger_middle, bollinger_lower = DerivativesAnalyticsService._calculate_bollinger_bands(prices)
            
            return AdvancedAnalytics(
                instrument_id="unknown",
                timestamp=datetime.utcnow(),
                volatility=float(volatility) if volatility is not None else None,
                returns_mean=float(returns_mean) if returns_mean is not None else None,
                returns_std=float(returns_std) if returns_std is not None else None,
                rolling_volatility_7d=float(rolling_vol_7d) if rolling_vol_7d is not None else None,
                rolling_volatility_30d=float(rolling_vol_30d) if rolling_vol_30d is not None else None,
                moving_average_7d=float(ma_7d) if ma_7d is not None else None,
                moving_average_30d=float(ma_30d) if ma_30d is not None else None,
                max_drawdown=float(max_drawdown) if max_drawdown is not None else None,
                sharpe_ratio=float(sharpe_ratio) if sharpe_ratio is not None else None,
                sortino_ratio=float(sortino_ratio) if sortino_ratio is not None else None,
                z_score=float(z_score) if z_score is not None else None,
                volume_anomaly_score=float(volume_anomaly_score) if volume_anomaly_score is not None else None,
                price_momentum=float(price_momentum) if price_momentum is not None else None,
                rsi=float(rsi) if rsi is not None else None,
                bollinger_upper=float(bollinger_upper) if bollinger_upper is not None else None,
                bollinger_lower=float(bollinger_lower) if bollinger_lower is not None else None,
                bollinger_middle=float(bollinger_middle) if bollinger_middle is not None else None
            )
            
        except Exception as e:
            logger.error(f"Error calculating advanced analytics: {e}")
            return AdvancedAnalytics(
                instrument_id="unknown",
                timestamp=datetime.utcnow(),
                volatility=None,
                returns_mean=None,
                returns_std=None,
                rolling_volatility_7d=None,
                rolling_volatility_30d=None,
                moving_average_7d=None,
                moving_average_30d=None,
                max_drawdown=None,
                sharpe_ratio=None,
                sortino_ratio=None,
                z_score=None,
                volume_anomaly_score=None,
                price_momentum=None,
                rsi=None,
                bollinger_upper=None,
                bollinger_lower=None,
                bollinger_middle=None
            )
    
    @staticmethod
    def _calculate_max_drawdown(prices: pd.Series) -> Optional[float]:
        """Calculate maximum drawdown from price series."""
        try:
            cumulative = (1 + prices.pct_change()).cumprod()
            running_max = cumulative.expanding().max()
            drawdown = (cumulative - running_max) / running_max
            return drawdown.min()
        except Exception:
            return None
    
    @staticmethod
    def _calculate_sortino_ratio(returns: pd.Series) -> Optional[float]:
        """Calculate Sortino ratio (downside risk-adjusted return)."""
        try:
            if len(returns) < 2:
                return None
            
            mean_return = returns.mean()
            downside_returns = returns[returns < 0]
            downside_std = downside_returns.std()
            
            if downside_std == 0:
                return None
            
            return (mean_return / downside_std * np.sqrt(252))
        except Exception:
            return None
    
    @staticmethod
    def _calculate_z_score(prices: pd.Series) -> Optional[float]:
        """Calculate Z-score of current price relative to historical mean."""
        try:
            if len(prices) < 2:
                return None
            
            current_price = prices.iloc[-1]
            historical_mean = prices.mean()
            historical_std = prices.std()
            
            if historical_std == 0:
                return None
            
            return (current_price - historical_mean) / historical_std
        except Exception:
            return None
    
    @staticmethod
    def _calculate_volume_anomaly(volumes: pd.Series) -> Optional[float]:
        """Calculate volume anomaly score using Z-score method."""
        try:
            volumes = volumes.dropna()
            if len(volumes) < 2:
                return None
            
            current_volume = volumes.iloc[-1]
            historical_mean = volumes.mean()
            historical_std = volumes.std()
            
            if historical_std == 0:
                return 0.5  # Neutral
            
            z_score = abs((current_volume - historical_mean) / historical_std)
            
            # Convert Z-score to 0-1 scale (capped at 3 sigma)
            anomaly_score = min(z_score / 3.0, 1.0)
            return anomaly_score
        except Exception:
            return None
    
    @staticmethod
    def _calculate_momentum(prices: pd.Series, periods: int = 14) -> Optional[float]:
        """Calculate price momentum."""
        try:
            if len(prices) < periods + 1:
                return None
            
            current_price = prices.iloc[-1]
            past_price = prices.iloc[-(periods + 1)]
            
            return ((current_price - past_price) / past_price) * 100
        except Exception:
            return None
    
    @staticmethod
    def _calculate_rsi(prices: pd.Series, periods: int = 14) -> Optional[float]:
        """Calculate Relative Strength Index (RSI)."""
        try:
            if len(prices) < periods + 1:
                return None
            
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=periods).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=periods).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1]
        except Exception:
            return None
    
    @staticmethod
    def _calculate_bollinger_bands(prices: pd.Series, periods: int = 20, std_dev: int = 2) -> tuple:
        """Calculate Bollinger Bands."""
        try:
            if len(prices) < periods:
                return None, None, None
            
            sma = prices.rolling(window=periods).mean()
            std = prices.rolling(window=periods).std()
            
            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)
            
            return upper.iloc[-1], sma.iloc[-1], lower.iloc[-1]
        except Exception:
            return None, None, None
    
    @staticmethod
    def calculate_correlation(series1: List[float], series2: List[float]) -> Optional[float]:
        """
        Calculate correlation between two price series.
        
        Args:
            series1: First price series
            series2: Second price series
            
        Returns:
            Correlation coefficient or None if calculation fails
        """
        try:
            if len(series1) != len(series2) or len(series1) < 2:
                return None
            
            correlation = np.corrcoef(series1, series2)[0, 1]
            return float(correlation) if not np.isnan(correlation) else None
        except Exception as e:
            logger.error(f"Error calculating correlation: {e}")
            return None
    
    @staticmethod
    def calculate_value_at_risk(returns: pd.Series, confidence_level: float = 0.95) -> Optional[float]:
        """
        Calculate Value at Risk (VaR) at given confidence level.
        
        Args:
            returns: Series of returns
            confidence_level: Confidence level (e.g., 0.95 for 95% VaR)
            
        Returns:
            VaR value or None if calculation fails
        """
        try:
            if len(returns) < 2:
                return None
            
            # Historical VaR
            var = np.percentile(returns, (1 - confidence_level) * 100)
            return float(var)
        except Exception as e:
            logger.error(f"Error calculating VaR: {e}")
            return None
    
    @staticmethod
    def calculate_expected_shortfall(returns: pd.Series, confidence_level: float = 0.95) -> Optional[float]:
        """
        Calculate Expected Shortfall (ES) / Conditional VaR at given confidence level.
        
        Args:
            returns: Series of returns
            confidence_level: Confidence level (e.g., 0.95 for 95% ES)
            
        Returns:
            Expected Shortfall value or None if calculation fails
        """
        try:
            if len(returns) < 2:
                return None
            
            var = DerivativesAnalyticsService.calculate_value_at_risk(returns, confidence_level)
            if var is None:
                return None
            
            # Average of returns worse than VaR
            tail_losses = returns[returns <= var]
            if len(tail_losses) == 0:
                return None
            
            es = tail_losses.mean()
            return float(es)
        except Exception as e:
            logger.error(f"Error calculating Expected Shortfall: {e}")
            return None
