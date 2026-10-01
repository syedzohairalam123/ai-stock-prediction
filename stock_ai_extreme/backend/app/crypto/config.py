"""
Crypto Volatility & Forecasting Intelligence — configuration.

All tunables live here (never scattered in components): analytics windows,
regime percentiles, forecast/validation parameters, query caps, cache TTLs,
WebSocket limits and rate limits. Environment variables use the ``CRYPTO_``
prefix (e.g. ``CRYPTO_PRIMARY_PROVIDER``).

Real-data policy: every setting here shapes *how* real provider data is queried
and computed. None of them can introduce a fabricated value.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class CryptoSettings(BaseSettings):
    enabled: bool = True

    # ---- providers (public, keyless) --------------------------------------
    #: Real-time klines/quote provider (REST + WebSocket).
    primary_provider: str = "binance"
    #: Market metadata provider (market cap / rank / supply). Optional.
    market_provider: str = "coingecko"
    binance_rest_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    request_timeout_seconds: float = Field(default=15.0, ge=3.0, le=60.0)

    # ---- cache TTLs (seconds) --------------------------------------------
    quote_cache_ttl_seconds: int = Field(default=5, ge=1, le=120)
    candles_cache_ttl_seconds: int = Field(default=45, ge=5, le=600)
    market_cache_ttl_seconds: int = Field(default=120, ge=30, le=1800)
    forecast_cache_ttl_seconds: int = Field(default=600, ge=60, le=7200)

    # ---- analytics windows -------------------------------------------------
    realized_vol_window: int = Field(default=20, ge=5, le=200)
    atr_period: int = Field(default=14, ge=2, le=100)
    rsi_period: int = Field(default=14, ge=2, le=100)
    ema_fast: int = Field(default=12, ge=2, le=100)
    ema_slow: int = Field(default=26, ge=3, le=300)
    momentum_lookback: int = Field(default=10, ge=2, le=100)

    #: Volatility-regime percentiles, computed from the asset's own history.
    regime_low_percentile: float = Field(default=20.0, ge=1.0, le=49.0)
    regime_high_percentile: float = Field(default=80.0, ge=51.0, le=99.0)
    regime_extreme_percentile: float = Field(default=95.0, ge=90.0, le=99.9)

    # ---- forecasting -------------------------------------------------------
    #: Below this many training rows a forecast is reported UNAVAILABLE.
    min_training_samples: int = Field(default=120, ge=30, le=2000)
    default_horizon: int = Field(default=5, ge=1, le=60)
    walk_forward_folds: int = Field(default=5, ge=2, le=20)
    #: Isolation-Forest-style multivariate gating is not used; classical models only.

    # ---- query / range control --------------------------------------------
    #: Hard server-side cap on candles returned for one request.
    max_history_candles: int = Field(default=1500, ge=100, le=5000)
    max_query_span_days: int = Field(default=365, ge=1, le=1825)
    #: Display-downsampling target for chart payloads (extrema preserved).
    display_target_points: int = Field(default=600, ge=100, le=2000)

    # ---- targets -----------------------------------------------------------
    max_targets_per_symbol: int = Field(default=50, ge=1, le=500)
    target_touch_lookback_days: int = Field(default=365, ge=7, le=1825)
    target_default_ladder: int = Field(default=3, ge=1, le=10)

    # ---- websocket ---------------------------------------------------------
    ws_heartbeat_seconds: int = Field(default=30, ge=10, le=120)
    #: One client may watch a bounded set of symbols (subscription channels).
    ws_max_symbols_per_client: int = Field(default=8, ge=1, le=50)
    #: Coalescing window for high tick rates (ms) so a slow client can't be
    #: flooded and one slow client cannot degrade the fan-out.
    ws_coalesce_ms: int = Field(default=250, ge=0, le=2000)

    # ---- rate limits -------------------------------------------------------
    rate_limit_max_requests: int = Field(default=300, ge=10, le=100000)
    rate_limit_window_seconds: int = Field(default=60, ge=10, le=600)
    ws_max_connections: int = Field(default=30, ge=1, le=10000)

    # ---- background workers -------------------------------------------------
    workers_enabled: bool = True
    worker_interval_seconds: int = Field(default=120, ge=15, le=3600)
    #: How many symbols a worker pass evaluates targets/forecasts for.
    worker_symbol_batch: int = Field(default=4, ge=1, le=50)

    model_config = {"extra": "ignore", "env_prefix": "CRYPTO_"}


crypto_settings = CryptoSettings()
