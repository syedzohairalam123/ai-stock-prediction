"""
Configuration for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class DerivativesSettings(BaseSettings):
    """Settings for derivatives module."""
    
    # Provider settings
    enable_yfinance_provider: bool = True
    enable_binance_provider: bool = True
    
    # Cache settings
    quote_cache_ttl_seconds: int = Field(default=20, ge=5, le=300)
    history_cache_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    funding_cache_ttl_seconds: int = Field(default=60, ge=15, le=600)
    oi_cache_ttl_seconds: int = Field(default=60, ge=15, le=600)
    depth_cache_ttl_seconds: int = Field(default=10, ge=5, le=60)
    
    # WebSocket settings
    enable_websocket: bool = True
    ws_heartbeat_interval_seconds: int = Field(default=30, ge=10, le=300)
    ws_stale_connection_timeout_seconds: int = Field(default=300, ge=60, le=3600)
    ws_max_reconnection_attempts: int = Field(default=5, ge=1, le=20)
    ws_reconnection_backoff_base_seconds: int = Field(default=2, ge=1, le=10)
    
    # Analytics settings
    analytics_default_lookback_days: int = Field(default=30, ge=7, le=365)
    analytics_max_lookback_days: int = Field(default=365, ge=30, le=1825)
    
    # Paper simulation settings
    simulation_max_leverage: int = Field(default=100, ge=1, le=100)
    simulation_max_scenarios_per_user: int = Field(default=50, ge=1, le=500)
    
    # Data quality settings
    data_quality_max_age_seconds: int = Field(default=300, ge=60, le=3600)
    data_quality_freshness_threshold_seconds: int = Field(default=60, ge=30, le=600)
    
    model_config = {"extra": "ignore"}


derivatives_settings = DerivativesSettings()
