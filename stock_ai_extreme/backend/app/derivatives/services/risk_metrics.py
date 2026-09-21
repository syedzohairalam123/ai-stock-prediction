"""
Risk metrics service for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides risk visualization metrics for educational purposes.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging
import numpy as np
import pandas as pd

from ..schemas import RiskMetrics

logger = logging.getLogger("neural_market.derivatives.services.risk_metrics")


class RiskMetricsService:
    """
    Service for risk metrics calculation and visualization.
    
    Provides educational risk metrics without guaranteed profit claims:
    - Historical volatility
    - Maximum historical drawdown
    - Recent price range
    - Value at Risk (VaR)
    - Expected Shortfall
    - Data quality score
    - Market liquidity indicators
    - Market stress indicators
    """
    
    @staticmethod
    def calculate_risk_metrics(historical_data: List[Dict[str, Any]],
                               current_price: Optional[float] = None,
                               benchmark_data: Optional[List[Dict[str, Any]]] = None) -> RiskMetrics:
        """
        Calculate comprehensive risk metrics from historical data.
        
        Args:
            historical_data: Historical price data
            current_price: Current market price (optional)
            benchmark_data: Benchmark data for correlation/beta (optional)
            
        Returns:
            RiskMetrics object with calculated metrics
        """
        try:
            if not historical_data or len(historical_data) < 2:
                return RiskMetrics(
                    instrument_id="unknown",
                    timestamp=datetime.utcnow(),
                    historical_volatility=None,
                    max_historical_drawdown=None,
                    recent_price_range=None,
                    value_at_risk_95=None,
                    expected_shortfall_95=None,
                    data_quality_score=0.0,
                    liquidity_indicator=None,
                    market_stress_indicator=None,
                    correlation_benchmark=None,
                    beta=None,
                    disclaimer="Educational risk metrics - not investment advice"
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
                return RiskMetrics(
                    instrument_id="unknown",
                    timestamp=datetime.utcnow(),
                    historical_volatility=None,
                    max_historical_drawdown=None,
                    recent_price_range=None,
                    value_at_risk_95=None,
                    expected_shortfall_95=None,
                    data_quality_score=0.0,
                    liquidity_indicator=None,
                    market_stress_indicator=None,
                    correlation_benchmark=None,
                    beta=None,
                    disclaimer="Educational risk metrics - not investment advice"
                )
            
            # Calculate returns
            returns = prices.pct_change().dropna()
            
            # Historical volatility (annualized)
            historical_volatility = returns.std() * np.sqrt(252) if len(returns) > 0 else None
            
            # Maximum historical drawdown
            max_historical_drawdown = RiskMetricsService._calculate_max_drawdown(prices)
            
            # Recent price range (last 30 days)
            recent_price_range = RiskMetricsService._calculate_recent_price_range(prices, days=30)
            
            # Value at Risk (95% confidence)
            var_95 = RiskMetricsService._calculate_var(returns, confidence_level=0.95)
            
            # Expected Shortfall (95% confidence)
            es_95 = RiskMetricsService._calculate_expected_shortfall(returns, confidence_level=0.95)
            
            # Data quality score
            data_quality_score = RiskMetricsService._calculate_data_quality_score(df)
            
            # Liquidity indicator
            liquidity_indicator = RiskMetricsService._calculate_liquidity_indicator(df)
            
            # Market stress indicator
            market_stress_indicator = RiskMetricsService._calculate_market_stress_indicator(returns)
            
            # Correlation with benchmark
            correlation_benchmark = None
            beta = None
            if benchmark_data:
                correlation_benchmark, beta = RiskMetricsService._calculate_benchmark_metrics(
                    prices, benchmark_data
                )
            
            return RiskMetrics(
                instrument_id="unknown",
                timestamp=datetime.utcnow(),
                historical_volatility=float(historical_volatility) if historical_volatility is not None else None,
                max_historical_drawdown=float(max_historical_drawdown) if max_historical_drawdown is not None else None,
                recent_price_range=float(recent_price_range) if recent_price_range is not None else None,
                value_at_risk_95=float(var_95) if var_95 is not None else None,
                expected_shortfall_95=float(es_95) if es_95 is not None else None,
                data_quality_score=float(data_quality_score),
                liquidity_indicator=float(liquidity_indicator) if liquidity_indicator is not None else None,
                market_stress_indicator=float(market_stress_indicator) if market_stress_indicator is not None else None,
                correlation_benchmark=float(correlation_benchmark) if correlation_benchmark is not None else None,
                beta=float(beta) if beta is not None else None,
                disclaimer="Educational risk metrics - not investment advice"
            )
            
        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return RiskMetrics(
                instrument_id="unknown",
                timestamp=datetime.utcnow(),
                historical_volatility=None,
                max_historical_drawdown=None,
                recent_price_range=None,
                value_at_risk_95=None,
                expected_shortfall_95=None,
                data_quality_score=0.0,
                liquidity_indicator=None,
                market_stress_indicator=None,
                correlation_benchmark=None,
                beta=None,
                disclaimer="Educational risk metrics - not investment advice"
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
    def _calculate_recent_price_range(prices: pd.Series, days: int = 30) -> Optional[float]:
        """Calculate price range over recent period."""
        try:
            if len(prices) < days:
                days = len(prices)
            
            recent_prices = prices.tail(days)
            return recent_prices.max() - recent_prices.min()
        except Exception:
            return None
    
    @staticmethod
    def _calculate_var(returns: pd.Series, confidence_level: float = 0.95) -> Optional[float]:
        """Calculate Value at Risk using historical method."""
        try:
            if len(returns) < 2:
                return None
            
            var = np.percentile(returns, (1 - confidence_level) * 100)
            return float(var)
        except Exception:
            return None
    
    @staticmethod
    def _calculate_expected_shortfall(returns: pd.Series, confidence_level: float = 0.95) -> Optional[float]:
        """Calculate Expected Shortfall (Conditional VaR)."""
        try:
            if len(returns) < 2:
                return None
            
            var = RiskMetricsService._calculate_var(returns, confidence_level)
            if var is None:
                return None
            
            tail_losses = returns[returns <= var]
            if len(tail_losses) == 0:
                return None
            
            es = tail_losses.mean()
            return float(es)
        except Exception:
            return None
    
    @staticmethod
    def _calculate_data_quality_score(df: pd.DataFrame) -> float:
        """
        Calculate data quality score (0-1).
        
        Factors:
        - Data completeness (no missing values)
        - Data consistency (no outliers)
        - Data freshness (recent timestamps)
        - Data frequency (regular intervals)
        """
        try:
            score = 0.0
            
            # Completeness score (0-40 points)
            total_cells = df.size
            missing_cells = df.isnull().sum().sum()
            completeness = 1 - (missing_cells / total_cells) if total_cells > 0 else 0
            score += completeness * 0.4
            
            # Consistency score (0-30 points)
            # Check for extreme outliers using IQR method
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                outlier_count = 0
                total_numeric = 0
                for col in numeric_cols:
                    Q1 = df[col].quantile(0.25)
                    Q3 = df[col].quantile(0.75)
                    IQR = Q3 - Q1
                    lower_bound = Q1 - 3 * IQR
                    upper_bound = Q3 + 3 * IQR
                    outliers = ((df[col] < lower_bound) | (df[col] > upper_bound)).sum()
                    outlier_count += outliers
                    total_numeric += len(df[col])
                
                consistency = 1 - (outlier_count / total_numeric) if total_numeric > 0 else 1
                score += consistency * 0.3
            else:
                score += 0.3  # No numeric columns to check
            
            # Freshness score (0-20 points)
            if 'timestamp' in df.columns:
                latest_timestamp = df['timestamp'].max()
                age_days = (datetime.utcnow() - latest_timestamp).days
                freshness = max(0, 1 - (age_days / 30))  # 30 days threshold
                score += freshness * 0.2
            else:
                score += 0.2  # No timestamp info
            
            # Frequency score (0-10 points)
            if len(df) > 1:
                time_diffs = df['timestamp'].diff().dropna()
                if len(time_diffs) > 0:
                    # Check if time differences are consistent
                    std_diff = time_diffs.std()
                    mean_diff = time_diffs.mean()
                    cv = std_diff / mean_diff if mean_diff > 0 else 0
                    frequency = max(0, 1 - cv)  # Lower coefficient of variation = better
                    score += frequency * 0.1
                else:
                    score += 0.1
            else:
                score += 0.0
            
            return min(score, 1.0)
            
        except Exception as e:
            logger.debug(f"Error calculating data quality score: {e}")
            return 0.5  # Default moderate score
    
    @staticmethod
    def _calculate_liquidity_indicator(df: pd.DataFrame) -> Optional[float]:
        """
        Calculate liquidity indicator (0-1).
        
        Factors:
        - Volume (if available)
        - Price spread (if bid/ask available)
        - Trade frequency
        """
        try:
            score = 0.0
            factors = 0
            
            # Volume factor
            if 'volume' in df.columns:
                volumes = df['volume'].dropna()
                if len(volumes) > 0:
                    avg_volume = volumes.mean()
                    # Normalize volume (log scale)
                    volume_score = min(np.log10(avg_volume + 1) / 10, 1.0)
                    score += volume_score * 0.5
                    factors += 1
            
            # Price movement factor (less volatile = more liquid)
            if 'close' in df.columns or 'last_price' in df.columns:
                price_col = 'close' if 'close' in df.columns else 'last_price'
                prices = df[price_col].dropna()
                if len(prices) > 1:
                    returns = prices.pct_change().dropna()
                    volatility = returns.std()
                    # Lower volatility = higher liquidity
                    vol_score = max(0, 1 - volatility * 10)  # 10% vol threshold
                    score += vol_score * 0.3
                    factors += 1
            
            # Data frequency factor
            if len(df) > 1:
                freq_score = min(len(df) / 100, 1.0)  # More data points = more liquid
                score += freq_score * 0.2
                factors += 1
            
            if factors > 0:
                return min(score / factors, 1.0)
            return None
            
        except Exception as e:
            logger.debug(f"Error calculating liquidity indicator: {e}")
            return None
    
    @staticmethod
    def _calculate_market_stress_indicator(returns: pd.Series) -> Optional[float]:
        """
        Calculate market stress indicator (0-1).
        
        Higher values indicate more market stress.
        Factors:
        - Volatility spikes
        - Downward momentum
        - Tail risk
        """
        try:
            if len(returns) < 10:
                return None
            
            score = 0.0
            
            # Volatility spike
            recent_vol = returns.tail(10).std()
            historical_vol = returns.std()
            vol_ratio = recent_vol / historical_vol if historical_vol > 0 else 1
            vol_stress = min(vol_ratio - 1, 1)  # 0 = normal, 1 = high stress
            score += vol_stress * 0.4
            
            # Downward momentum
            recent_return = returns.tail(5).mean()
            momentum_stress = max(0, -recent_return * 10)  # Negative returns = stress
            score += min(momentum_stress, 1) * 0.3
            
            # Tail risk (frequency of large negative returns)
            large_losses = (returns < returns.quantile(0.05)).sum()
            tail_stress = min(large_losses / len(returns) * 10, 1)
            score += tail_stress * 0.3
            
            return min(score, 1.0)
            
        except Exception as e:
            logger.debug(f"Error calculating market stress indicator: {e}")
            return None
    
    @staticmethod
    def _calculate_benchmark_metrics(prices: pd.Series, 
                                    benchmark_data: List[Dict[str, Any]]) -> tuple[Optional[float], Optional[float]]:
        """
        Calculate correlation and beta with benchmark.
        
        Args:
            prices: Asset price series
            benchmark_data: Benchmark price data
            
        Returns:
            Tuple of (correlation, beta)
        """
        try:
            if not benchmark_data or len(benchmark_data) < 2:
                return None, None
            
            # Convert benchmark to DataFrame
            bench_df = pd.DataFrame(benchmark_data)
            bench_df['timestamp'] = pd.to_datetime(bench_df['timestamp'])
            bench_df = bench_df.sort_values('timestamp')
            
            # Get benchmark price column
            if 'close' in bench_df.columns:
                bench_price_col = 'close'
            elif 'last_price' in bench_df.columns:
                bench_price_col = 'last_price'
            else:
                return None, None
            
            bench_prices = bench_df[bench_price_col].dropna()
            
            # Calculate returns
            asset_returns = prices.pct_change().dropna()
            bench_returns = bench_prices.pct_change().dropna()
            
            # Align series
            min_len = min(len(asset_returns), len(bench_returns))
            asset_returns = asset_returns.tail(min_len)
            bench_returns = bench_returns.tail(min_len)
            
            if len(asset_returns) < 2:
                return None, None
            
            # Calculate correlation
            correlation = asset_returns.corr(bench_returns)
            
            # Calculate beta
            covariance = asset_returns.cov(bench_returns)
            bench_variance = bench_returns.var()
            beta = covariance / bench_variance if bench_variance > 0 else None
            
            return float(correlation) if not pd.isna(correlation) else None, float(beta) if beta is not None and not pd.isna(beta) else None
            
        except Exception as e:
            logger.debug(f"Error calculating benchmark metrics: {e}")
            return None, None
    
    @staticmethod
    def generate_risk_report(risk_metrics: RiskMetrics) -> Dict[str, Any]:
        """
        Generate a human-readable risk report.
        
        Args:
            risk_metrics: RiskMetrics object
            
        Returns:
            Dictionary with risk assessment
        """
        try:
            risk_level = "LOW"
            risk_factors = []
            
            # Assess volatility
            if risk_metrics.historical_volatility:
                if risk_metrics.historical_volatility > 0.5:
                    risk_level = "HIGH"
                    risk_factors.append("High historical volatility")
                elif risk_metrics.historical_volatility > 0.3:
                    risk_level = "MEDIUM"
                    risk_factors.append("Moderate historical volatility")
            
            # Assess drawdown
            if risk_metrics.max_historical_drawdown:
                if risk_metrics.max_historical_drawdown < -0.5:
                    risk_level = "HIGH"
                    risk_factors.append("Severe historical drawdown")
                elif risk_metrics.max_historical_drawdown < -0.3:
                    if risk_level != "HIGH":
                        risk_level = "MEDIUM"
                    risk_factors.append("Significant historical drawdown")
            
            # Assess market stress
            if risk_metrics.market_stress_indicator:
                if risk_metrics.market_stress_indicator > 0.7:
                    risk_level = "HIGH"
                    risk_factors.append("High market stress")
                elif risk_metrics.market_stress_indicator > 0.4:
                    if risk_level != "HIGH":
                        risk_level = "MEDIUM"
                    risk_factors.append("Moderate market stress")
            
            # Assess liquidity
            if risk_metrics.liquidity_indicator:
                if risk_metrics.liquidity_indicator < 0.3:
                    risk_factors.append("Low liquidity")
            
            return {
                "risk_level": risk_level,
                "risk_factors": risk_factors,
                "data_quality": "EXCELLENT" if risk_metrics.data_quality_score > 0.8 else 
                              "GOOD" if risk_metrics.data_quality_score > 0.6 else
                              "FAIR" if risk_metrics.data_quality_score > 0.4 else "POOR",
                "liquidity_status": "HIGH" if risk_metrics.liquidity_indicator and risk_metrics.liquidity_indicator > 0.7 else
                                  "MODERATE" if risk_metrics.liquidity_indicator and risk_metrics.liquidity_indicator > 0.4 else
                                  "LOW",
                "market_stress": "HIGH" if risk_metrics.market_stress_indicator and risk_metrics.market_stress_indicator > 0.7 else
                               "MODERATE" if risk_metrics.market_stress_indicator and risk_metrics.market_stress_indicator > 0.4 else
                               "LOW",
                "disclaimer": "Educational risk assessment - not investment advice"
            }
            
        except Exception as e:
            logger.error(f"Error generating risk report: {e}")
            return {
                "risk_level": "UNKNOWN",
                "risk_factors": [],
                "disclaimer": "Educational risk assessment - not investment advice"
            }
