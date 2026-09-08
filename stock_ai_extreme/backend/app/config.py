from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    cors_origins: str = "http://localhost:5173"
    default_prediction_horizon: int = 7
    live_poll_seconds: int = 20
    model_dir: str = "artifacts/models"
    # --- Phase 2: provider layer (all optional — app runs fine with none of these set) ---
    finnhub_api_key: Optional[str] = None       # optional live-quote fallback provider
    history_cache_ttl_seconds: int = 300         # how long OHLCV history is cached
    quote_cache_ttl_seconds: int = 20            # how long a live quote is cached
    profile_cache_ttl_seconds: int = 3600        # company profile info changes rarely
    provider_max_retries: int = 3
    # --- Phase 3: persistence (SQLite by default; point this at Postgres later
    # with zero code changes — SQLAlchemy handles both through the same URL) ---
    database_url: str = "sqlite:///./neural_market.db"
    # --- Phase 14: optional AI briefing (skipped cleanly if no key is set) ---
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    # --- Phase 19: basic API rate limiting ---
    rate_limit_max_requests: int = 120
    rate_limit_window_seconds: int = 60
    # --- Phase 10/14+: background jobs + notifications (all optional) ---
    background_interval_seconds: int = 300     # how often the background maintenance loop runs
    background_jobs_enabled: bool = True        # set false to disable the background loop entirely
    news_cache_ttl_seconds: int = 600           # how long fetched news headlines are cached
    telegram_bot_token: Optional[str] = None    # optional Telegram alert notifications
    telegram_chat_id: Optional[str] = None
    smtp_host: Optional[str] = None             # optional email alert notifications (stdlib smtplib)
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_to: Optional[str] = None
    smtp_from: Optional[str] = None
    # --- Macro/events/crypto-pro/screener additions (all optional — the app runs with none set) ---
    fred_api_key: Optional[str] = None          # official FRED macro data (free key at fred.stlouisfed.org)
    macro_default_source: str = "yfinance"      # "fred" or "yfinance" — the user-selectable macro source
    crypto_default_source: str = "coingecko"    # "coingecko" or "yfinance" — the user-selectable crypto source
    coingecko_timeout_seconds: float = 15.0
    screener_default_tickers: str = "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,XOM,GLD,BTC-USD"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
