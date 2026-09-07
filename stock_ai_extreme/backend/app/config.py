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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
