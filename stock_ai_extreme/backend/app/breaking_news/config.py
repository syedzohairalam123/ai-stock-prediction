"""
Configuration for Phase 17 — Real-Time Breaking News + Trending Topics +
Market Impact Intelligence.

Every weight and threshold the breaking/news/topic engines use lives here
rather than being hard-coded inside a scoring function, so the ranking is
*configurable* (an explicit requirement of the phase) and so a deployment can
tune it without a code change. Environment variables are prefixed with
``BREAKING_NEWS_`` (e.g. ``BREAKING_NEWS_BREAKING_THRESHOLD=70``).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BreakingNewsSettings(BaseSettings):
    """Settings for the Phase 17 breaking-news intelligence engine."""

    model_config = SettingsConfigDict(
        env_prefix="BREAKING_NEWS_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Breaking detection
    # ------------------------------------------------------------------
    breaking_threshold: float = Field(default=75.0, ge=0, le=100)
    significant_threshold: float = Field(default=50.0, ge=0, le=100)
    recency_window_hours: int = Field(default=24, ge=1, le=168)
    breaking_recency_minutes: int = Field(default=30, ge=1, le=1440)
    significant_recency_hours: int = Field(default=6, ge=1, le=168)

    #: Weights of the breaking score. Kept as a mapping so the detector can be
    #: reconfigured wholesale (and so the response can echo the active weights).
    detection_weights: dict = Field(
        default_factory=lambda: {
            "recency": 0.25,
            "source_reliability": 0.20,
            "entity_importance": 0.15,
            "mention_velocity": 0.15,
            "topic_acceleration": 0.10,
            "market_association": 0.15,
        }
    )

    # ------------------------------------------------------------------
    # Deduplication / clustering
    # ------------------------------------------------------------------
    simhash_threshold: int = Field(default=3, ge=1, le=12)
    similarity_threshold: float = Field(default=0.30, ge=0.05, le=0.99)
    min_sources_for_cluster: int = Field(default=2, ge=1, le=20)
    max_clusters: int = Field(default=60, ge=1, le=500)
    cluster_window_hours: int = Field(default=72, ge=1, le=336)

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------
    topic_trend_window_hours: int = Field(default=24, ge=1, le=336)
    topic_velocity_window_hours: int = Field(default=6, ge=1, le=72)
    min_topic_mentions: int = Field(default=2, ge=1, le=100)
    #: Higher bar for free-text TF-IDF keyword topics: they are noisier than the
    #: curated lexicon or a validated ticker, so a keyword needs more
    #: corroboration before it is presented as a "hot topic".
    min_keyword_mentions: int = Field(default=3, ge=1, le=100)
    max_topics: int = Field(default=60, ge=1, le=500)
    topic_keywords_per_article: int = Field(default=8, ge=3, le=25)
    topic_trend_weights: dict = Field(
        default_factory=lambda: {
            "mention_velocity": 0.35,
            "source_count": 0.25,
            "recency": 0.20,
            "related_activity": 0.20,
        }
    )

    # ------------------------------------------------------------------
    # Market impact
    # ------------------------------------------------------------------
    default_observation_window: str = "1h"
    observation_windows: List[str] = Field(default_factory=lambda: ["5m", "15m", "30m", "1h", "4h", "24h"])
    #: Minimum number of timestamped bars required inside a window before that
    #: window may be reported. Below this the window is reported UNAVAILABLE
    #: rather than measured off a single point.
    min_bars_for_window: int = Field(default=3, ge=1, le=60)
    #: Cap on how many entities are analysed per news event (each one costs a
    #: provider round-trip; the ranking already puts the most important first).
    max_entities_per_event: int = Field(default=3, ge=1, le=10)
    #: Intraday interval requested per observation window. yfinance supports
    #: 1m (7d history), 5m/15m/30m (60d) and 1h (730d).
    window_intervals: dict = Field(
        default_factory=lambda: {
            "5m": "1m",
            "15m": "5m",
            "30m": "5m",
            "1h": "5m",
            "4h": "15m",
            "24h": "1h",
        }
    )
    market_impact_enabled: bool = True
    #: Minimum number of *measured* observations a group in the observed-movement
    #: event study (``GET /impact/study``) needs before its averages are
    #: presented as meaningful. Below this the group is reported with
    #: ``sufficient_sample: false`` rather than hidden or silently averaged.
    impact_study_min_sample: int = Field(default=5, ge=1, le=1000)
    #: Cap on how many groups each breakdown of the event study returns, so a
    #: corpus that mentions thousands of entities cannot produce a huge payload.
    impact_study_max_groups: int = Field(default=25, ge=1, le=500)
    #: Cap on how many stored movement rows one event-study request reads, so the
    #: endpoint stays a bounded, fast read as the impact table grows.
    impact_study_max_rows: int = Field(default=5000, ge=100, le=100000)

    # ------------------------------------------------------------------
    # Forecast probability movement (Phase 14 integration)
    # ------------------------------------------------------------------
    probability_movement_enabled: bool = True
    #: When true, news is matched to Phase 14 markets by keyword overlap between
    #: the headline and the market question. Purely local — no extra network.
    probability_match_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
    probability_max_markets: int = Field(default=3, ge=1, le=20)

    # ------------------------------------------------------------------
    # Real-time updates
    # ------------------------------------------------------------------
    enable_websocket: bool = True
    enable_sse: bool = True
    ws_heartbeat_interval_seconds: int = Field(default=30, ge=5, le=300)
    ws_stale_connection_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    ws_max_reconnection_attempts: int = Field(default=5, ge=1, le=20)
    ws_reconnection_backoff_base_seconds: int = Field(default=2, ge=1, le=60)
    stream_broadcast_interval_seconds: int = Field(default=20, ge=5, le=300)

    # ------------------------------------------------------------------
    # Caches
    # ------------------------------------------------------------------
    breaking_news_cache_ttl_seconds: int = Field(default=60, ge=5, le=3600)
    topics_cache_ttl_seconds: int = Field(default=300, ge=10, le=3600)
    market_impact_cache_ttl_seconds: int = Field(default=120, ge=10, le=3600)
    feed_max_items: int = Field(default=200, ge=10, le=1000)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    #: How many of the newest stored articles are considered when building the
    #: breaking feed. Bounded so a huge corpus cannot turn a request into a
    #: multi-second scan.
    ingest_scan_limit: int = Field(default=1200, ge=50, le=10000)
    #: Region passed to the keyless RSS layer. None / "ALL" means every feed.
    ingest_region: Optional[str] = None
    #: How long a persisted breaking row is kept. Anything older can never be
    #: shown by any feed window (max 168h), so it is pruned on the next build.
    retention_hours: int = Field(default=168, ge=24, le=720)
    #: How often the background maintenance loop rebuilds the breaking feed.
    refresh_interval_seconds: int = Field(default=600, ge=120, le=86400)
    #: Top-scoring events that get market-impact / probability analysis during a
    #: background ingest. Each costs provider round-trips, so this is bounded.
    top_events_for_impact: int = Field(default=5, ge=0, le=25)
    #: Cap on how many events trigger market-impact work inside one request.
    max_impact_events_per_run: int = Field(default=10, ge=0, le=50)

    # ------------------------------------------------------------------
    # AI summarization
    # ------------------------------------------------------------------
    enable_ai_summarization: bool = True
    ai_summary_max_length: int = Field(default=200, ge=40, le=1000)
    #: AI summaries are only generated for events at/above this breaking score,
    #: so a deployment never spends tokens on routine market wrap-ups.
    ai_summary_min_score: float = Field(default=65.0, ge=0, le=100)

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    #: A provider is marked DEGRADED after this many consecutive failures.
    source_degraded_error_threshold: int = Field(default=3, ge=1, le=100)


breaking_news_settings = BreakingNewsSettings()
