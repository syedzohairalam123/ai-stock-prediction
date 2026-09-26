"""
Configuration for Phase 19 — Advanced Market Discovery / New & Trending Engine.

Every threshold, saturation constant and weight that can influence a trend
score lives here so the ranking is tunable *and* inspectable — the API returns
the active weights/saturations alongside every response (spec §4: "never hide
arbitrary constants throughout the codebase").

Environment variables are prefixed ``DISCOVERY_`` (e.g.
``DISCOVERY_UNIVERSE_CACHE_TTL_SECONDS=60``). All defaults are deliberately
conservative; nothing here can manufacture a number that no source measured.
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscoverySettings(BaseSettings):
    """Settings for the Phase 19 discovery / trend-scoring module."""

    model_config = SettingsConfigDict(
        env_prefix="DISCOVERY_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ feeds
    feed_default_limit: int = Field(default=24, ge=1, le=200)
    feed_max_limit: int = Field(default=100, ge=1, le=500)
    #: How long the collected entity universe is reused before it is re-fetched.
    #: Quotes underneath are cached by the provider manager too — this cache
    #: only avoids re-running the aggregation/fan-out on every keystroke.
    #: Tuned to 180s so a full pass (≈40 symbols × quote/history/profile + the
    #: Polymarket batch) happens at most twice per five minutes under load,
    #: which keeps the free provider well inside its comfort zone.
    universe_cache_ttl_seconds: int = Field(default=180, ge=0, le=3600)
    #: Bounds on how many raw entities each collector may contribute. Keeping
    #: them here (not inline) means a slower machine can trade coverage for
    #: latency without touching code.
    stock_universe_limit: int = Field(default=24, ge=4, le=200)
    forecast_event_limit: int = Field(default=50, ge=5, le=200)
    news_topic_limit: int = Field(default=50, ge=5, le=300)
    instrument_limit: int = Field(default=40, ge=4, le=200)

    # ----------------------------------------------------------- trend scores
    #: Component weights for the aggregate trend score. They are normalized at
    #: use time, so they do not need to sum to 1. A component that is
    #: unavailable for an entity is excluded and the remaining weights are
    #: renormalized — an entity is never penalized for a signal nobody has.
    trend_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "recency": 0.20,
            "activity": 0.25,
            "velocity": 0.25,
            "interest": 0.15,
            "news": 0.15,
        }
    )
    #: Weights for the POPULAR feed (interest first, measured activity second).
    popularity_weights: Dict[str, float] = Field(
        default_factory=lambda: {"interest": 0.7, "activity": 0.3}
    )
    #: Recency uses exponential decay with this half-life: an entity this old
    #: scores 0.5 on the recency component.
    recency_half_life_hours: float = Field(default=72.0, ge=1.0, le=8760.0)

    #: Saturation constants: the raw value at (or above) which a component
    #: scores 1.0. One per measurable signal — documented, not magic.
    #: Day-change percent treated as "maximum meaningful single-day activity".
    activity_saturation_change_pct: float = Field(default=5.0, gt=0)
    #: Forecast-event 24h volume (USD) that counts as fully active.
    activity_saturation_event_volume: float = Field(default=250000.0, gt=0)
    #: Forecast-event participant count considered fully active.
    activity_saturation_event_participants: float = Field(default=2000.0, gt=0)
    #: News-topic mention count (whole corpus) considered fully active.
    activity_saturation_topic_mentions: float = Field(default=60.0, gt=0)
    #: Topic mention acceleration (mentions/hour) considered fully active.
    velocity_saturation_topic_per_hour: float = Field(default=6.0, gt=0)
    #: Per-hour change of any other entity's activity from its own observation
    #: history considered fully active.
    velocity_saturation_activity_per_hour: float = Field(default=5.0, gt=0)
    #: Recorded user-interest events (views + searches + watchlist adds)
    #: considered fully interesting.
    interest_saturation: float = Field(default=25.0, gt=0)
    #: Distinct publishers covering a topic (news score for news topics).
    news_saturation_source_count: float = Field(default=6.0, gt=0)
    #: News articles naming a ticker in the last 24h (news score for stocks).
    news_saturation_mentions_24h: float = Field(default=10.0, gt=0)

    # ---------------------------------------------------- observations (§12)
    #: Trend observations ({timestamp, activity, score}) are sampled at most
    #: this often per entity when the trending feed is read (and by the
    #: background sampler if enabled).
    observation_sample_interval_seconds: int = Field(default=300, ge=30, le=86400)
    #: Observations older than this are pruned (7 days of sparkline history).
    observation_retention_hours: int = Field(default=168, ge=1, le=2160)
    #: Velocity is measured between observations inside this recent window so
    #: a sample from three days ago cannot masquerade as "current" motion.
    velocity_lookback_hours: float = Field(default=6.0, ge=0.25, le=168.0)
    #: Trend history returned by GET /api/discover/trends/{id}.
    trend_history_hours: int = Field(default=72, ge=1, le=2160)
    #: Cap on observations written per sampling pass (bounded write load).
    observation_sample_top_k: int = Field(default=60, ge=1, le=500)

    # ------------------------------------------------------ interest events
    #: Real recorded engagement (views/searches) older than this is pruned.
    event_retention_days: int = Field(default=90, ge=1, le=3650)
    event_max_rows: int = Field(default=50000, ge=1000, le=1000000)

    # ------------------------------------------------------- personalization
    #: Personalization only ever uses *explicit* actions (watchlist adds,
    #: entities this client actually viewed, categories this client selected).
    #: It never infers sensitive preferences from content.
    personalization_enabled: bool = True
    #: Maximum relative score boost an explicit signal can give (0.12 = +12%).
    personalization_boost: float = Field(default=0.12, ge=0.0, le=1.0)
    #: How long an entity stays in "recently viewed" for this client.
    recently_viewed_hours: int = Field(default=168, ge=1, le=8760)
    max_recently_viewed: int = Field(default=50, ge=5, le=500)

    # --------------------------------------------------------- background job
    #: Sample trending observations on the maintenance loop even when nobody
    #: has the page open, so sparklines have history when someone arrives.
    #: 15 minutes between passes: the observations are for sparklines, not
    #: tick-by-tick surveillance, and a calmer cadence means far fewer provider
    #: fan-outs while the app is idle.
    background_sampling_enabled: bool = True
    background_sampling_interval_seconds: int = Field(default=900, ge=60, le=86400)

    # ------------------------------------------------------------- categories
    #: The full category vocabulary (spec §5). Entities map into these; a
    #: category nobody uses simply shows zero counts instead of disappearing.
    categories: List[str] = Field(
        default_factory=lambda: [
            "Politics",
            "Sports",
            "Crypto",
            "Esports",
            "Finance",
            "Geopolitics",
            "Tech",
            "Culture",
            "Economy",
            "Stocks",
            "Commodities",
            "Forex",
        ]
    )


discovery_settings = DiscoverySettings()
