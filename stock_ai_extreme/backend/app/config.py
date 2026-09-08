from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    # Application settings
    app_name: str = "Neural Market API"
    app_version: str = "2.3.0"
    debug: bool = False
    
    # CORS settings
    cors_origins: str = "http://localhost:5173"
    
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
    
    # Persistence (SQLite by default; point this at Postgres later)
    database_url: str = "sqlite:///./neural_market.db"
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=10, ge=0, le=50)
    
    # AI briefing (optional)
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_timeout_seconds: int = Field(default=30, ge=5, le=120)
    
    # Rate limiting
    rate_limit_max_requests: int = Field(default=120, ge=10, le=1000)
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
