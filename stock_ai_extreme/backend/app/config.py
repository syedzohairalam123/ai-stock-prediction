from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    # Application settings
    app_name: str = "Neural Market API"
    app_version: str = "2.3.0"
    debug: bool = False
    
    # CORS settings
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    
    # Core settings
    default_prediction_horizon: int = Field(default=7, ge=1, le=30)
    live_poll_seconds: int = Field(default=20, ge=5, le=300)
    model_dir: str = "artifacts/models"
    
    # Logging settings
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    
    # Provider layer (all optional — app runs fine with none of these set)
    finnhub_api_key: Optional[str] = None       # optional live-quote fallback provider
    history_cache_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    quote_cache_ttl_seconds: int = Field(default=20, ge=5, le=300)
    profile_cache_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    provider_max_retries: int = Field(default=3, ge=1, le=10)
    provider_timeout_seconds: int = Field(default=30, ge=5, le=120)

    # Phase 15 — live public forecast-market source
    forecast_market_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    forecast_market_limit: int = Field(default=60, ge=5, le=100)

    # Phase 14.1 — real probability history (Polymarket CLOB price series).
    # The Gamma market payload carries `clobTokenIds`; the CLOB REST API then
    # serves the real, tick-by-tick traded probability for that token. The
    # fidelity is the sampling granularity in minutes, TTL the cache lifetime.
    forecast_clob_url: str = "https://clob.polymarket.com"
    forecast_history_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    forecast_history_cache_ttl_seconds: int = Field(default=120, ge=15, le=3600)
    forecast_history_fidelity: int = Field(default=60, ge=1, le=1440)
    forecast_history_max_points: int = Field(default=2000, ge=60, le=10000)

    # Phase 14.2 — resolution tracking (closed markets, polled separately).
    forecast_resolution_cache_ttl_seconds: int = Field(default=600, ge=60, le=86400)
    forecast_resolution_scan_limit: int = Field(default=200, ge=10, le=1000)

    # Phase 14.3 — Monte-Carlo probability simulation.
    forecast_simulation_paths: int = Field(default=10000, ge=500, le=100000)
    forecast_simulation_max_steps: int = Field(default=180, ge=5, le=2000)

    # Phase 15 — correlation-adjusted multi-event combination analysis.
    combination_max_events: int = Field(default=12, ge=2, le=40)
    combination_min_overlap_points: int = Field(default=8, ge=4, le=500)
    combination_monte_carlo_draws: int = Field(default=20000, ge=1000, le=200000)
    combination_sensitivity_delta_pp: float = Field(default=10.0, ge=1.0, le=50.0)
    
    # Persistence (SQLite by default; point this at Postgres later)
    database_url: str = "sqlite:///./neural_market.db"
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=10, ge=0, le=50)
    
    # AI briefing (optional)
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_timeout_seconds: int = Field(default=30, ge=5, le=120)
    
    # Phase 10: AI Financial Assistant
    ai_provider: str = Field(default="openai", pattern="^(openai|openrouter|anthropic)$")
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: int = Field(default=60, ge=10, le=300)
    openai_max_tokens: int = Field(default=4000, ge=500, le=16000)
    openrouter_api_key: Optional[str] = None
    openrouter_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: int = Field(default=60, ge=10, le=300)
    ai_max_conversation_messages: int = Field(default=50, ge=10, le=200)
    ai_context_window_tokens: int = Field(default=8000, ge=2000, le=32000)
    ai_enable_streaming: bool = True
    ai_enable_voice: bool = True
    
    # Rate limiting
    rate_limit_max_requests: int = Field(default=120, ge=10, le=100000)
    rate_limit_window_seconds: int = Field(default=60, ge=10, le=600)
    
    # Background jobs + notifications (all optional)
    background_interval_seconds: int = Field(default=300, ge=60, le=3600)
    background_jobs_enabled: bool = True
    news_cache_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    
    # Telegram notifications
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_timeout_seconds: int = Field(default=10, ge=5, le=30)
    
    # Email notifications
    smtp_host: Optional[str] = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_to: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_timeout_seconds: int = Field(default=10, ge=5, le=30)
    smtp_use_tls: bool = True
    
    # Macro/events/crypto-pro/screener settings
    fred_api_key: Optional[str] = None
    macro_default_source: str = Field(default="yfinance", pattern="^(yfinance|fred)$")
    crypto_default_source: str = Field(default="coingecko", pattern="^(coingecko|yfinance)$")
    coingecko_timeout_seconds: float = Field(default=15.0, ge=5.0, le=60.0)
    screener_default_tickers: str = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,XOM,GLD,BTC-USD"
    screener_max_tickers: int = Field(default=50, ge=1, le=100)
    
    # Phase 7 — Forex & commodities center
    # Real, keyless sources: Yahoo (yfinance) supplies live FX bid/ask and COMEX
    # front-month metal futures; ExchangeRate-API's open endpoint (166 currencies)
    # is a daily-published fallback that covers PKR/AED/SAR. No key is required
    # for either, so the page works out of the box.
    fx_rates_cache_ttl_seconds: int = Field(default=120, ge=30, le=3600)
    fx_history_cache_ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    exchangerate_api_url: str = "https://open.er-api.com/v6/latest/USD"
    exchangerate_api_timeout_seconds: int = Field(default=15, ge=5, le=60)
    # Freshness thresholds (seconds), measured against the SOURCE's own
    # publication time, not when we fetched it. Calibrated against what the real
    # feeds do: majors tick within minutes, while an illiquid PKR cross can carry
    # a timestamp from that morning's interbank open — real, same-day data that
    # must be shown as DELAYED rather than dressed up as a live tick.
    fx_live_threshold_seconds: int = Field(default=900, ge=60, le=86400)         # 15 min = a live tick
    fx_aging_threshold_seconds: int = Field(default=86400, ge=900, le=604800)    # 24 h  = same-day reference
    fx_stale_threshold_seconds: int = Field(default=604800, ge=3600, le=2592000)  # 7 days = refuse to call it current

    # Phase 8 — Professional News & Financial Intelligence Desk
    # Real news APIs for comprehensive financial news coverage
    newsapi_key: Optional[str] = None  # NewsAPI.org - 100 requests/day free
    newsapi_url: str = "https://newsapi.org/v2"
    newsapi_timeout_seconds: int = Field(default=15, ge=5, le=60)
    
    alpha_vantage_key: Optional[str] = None  # Alpha Vantage - 25 requests/day free
    alpha_vantage_url: str = "https://www.alphavantage.co"
    alpha_vantage_timeout_seconds: int = Field(default=15, ge=5, le=60)
    
    # Finnhub also provides news (already have key for quotes)
    finnhub_news_cache_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    
    # News aggregation settings
    news_max_items_per_request: int = Field(default=100, ge=10, le=500)
    news_default_page_size: int = Field(default=20, ge=5, le=100)
    news_search_debounce_ms: int = Field(default=300, ge=100, le=1000)

    # Keyless publisher RSS/Atom feeds (news_sources.py). These need no API key,
    # so the desk has real headlines on a fresh install. Set
    # NEWS_RSS_ENABLED=false to rely purely on the keyed APIs.
    news_rss_enabled: bool = True
    #: "PK" | "GLOBAL" | "ALL" — which feed regions to ingest.
    news_default_region: str = "ALL"
    #: Simultaneous outbound feed requests. Bounded on purpose: fetching every
    #: feed at once is fast for us and rude to the publishers.
    news_fetch_concurrency: int = Field(default=6, ge=1, le=20)
    #: How many recent rows the near-duplicate index is built from.
    news_dedupe_scan_limit: int = Field(default=3000, ge=100, le=50000)
    #: SimHash banding: `bands` must exceed the Hamming threshold for the
    #: pigeonhole shortcut in news_analytics.SimHashIndex to stay exact.
    news_simhash_bands: int = Field(default=4, ge=2, le=8)
    news_simhash_hamming_threshold: int = Field(default=3, ge=1, le=6)
    #: MinHash signature geometry. `band_rows` must divide `rows` evenly (LSH
    #: banding); the row count sets the estimate's accuracy (~1/sqrt(rows)).
    news_minhash_rows: int = Field(default=24, ge=8, le=128)
    news_minhash_band_rows: int = Field(default=4, ge=1, le=16)
    #: Estimated Jaccard similarity at or above which two articles are treated
    #: as the same story re-published. 0.8 was picked against real syndicated
    #: text: below it, distinct stories that share a lot of market vocabulary
    #: start merging; above it, genuine re-publications slip through.
    news_dedupe_jaccard_threshold: float = Field(default=0.8, ge=0.5, le=0.99)
    #: Automatic ingestion interval for the background loop (seconds).
    news_refresh_interval_seconds: int = Field(default=1800, ge=300, le=86400)
    #: Tickers to pull company-scoped news for on every ingest. A general feed
    #: will never carry a paragraph about every listed company, so the desk
    #: asks the publisher directly for the names people actually trade. Set to
    #: an empty string to disable the extra requests.
    news_symbol_watchlist: str = (
        "OGDC,PPL,LUCK,HBL,UBL,MCB,MEBL,ENGRO,FFC,PSO,SYS,HUBC,MARI,BAFL,NETSOL"
    )
    news_symbol_max: int = Field(default=20, ge=0, le=60)
    #: Relevance ranking parameters for news search (BM25).
    news_search_title_boost: float = Field(default=2.5, ge=1.0, le=5.0)
    news_search_fuzzy: bool = True

    # Performance settings
    max_history_days: int = Field(default=3650, ge=365, le=7300)  # Max 10 years
    min_history_days: int = Field(default=30, ge=7, le=365)
    
    @field_validator('cors_origins')
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        if not v or not v.strip():
            return "http://localhost:5173"
        return v
    
    @field_validator('screener_default_tickers')
    @classmethod
    def validate_screener_tickers(cls, v: str) -> str:
        if not v or not v.strip():
            return "AAPL,MSFT,GOOGL"
        return v
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

settings = Settings()
