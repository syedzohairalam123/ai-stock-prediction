"""
Pydantic schemas for Phase 17 — Real-Time Breaking News + Trending Topics +
Market Impact Intelligence.

Every response model here is an explicit contract, and every optional field is
optional because the underlying value can genuinely be absent (a publisher that
supplies no image, a market that has not traded since publication). Nothing is
defaulted to a plausible-looking number.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

class BreakingLevel(str, Enum):
    BREAKING = "BREAKING"
    SIGNIFICANT = "SIGNIFICANT"
    NORMAL = "NORMAL"


class TrendDirection(str, Enum):
    RISING = "RISING"
    FALLING = "FALLING"
    STABLE = "STABLE"


class ImpactMagnitude(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class DataMode(str, Enum):
    LIVE = "LIVE"
    RECENT = "RECENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class SourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# normalized article (spec §3)
# ---------------------------------------------------------------------------

class EntitySchema(BaseModel):
    type: str
    value: str
    label: str


class NormalizedArticleSchema(BaseModel):
    """The one article shape every source is normalized into.

    ``missing`` names the required fields the publisher did not provide, so the
    UI can say "image unavailable" instead of rendering a broken box.
    """

    id: Optional[int] = None
    title: str
    publisher: str
    published_at: Optional[datetime] = None
    url: str
    image: Optional[str] = None
    excerpt: Optional[str] = None
    category: Optional[str] = None
    entities: List[EntitySchema] = Field(default_factory=list)
    symbols: List[str] = Field(default_factory=list)
    indices: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    source: str
    data_mode: DataMode = DataMode.UNKNOWN
    event_type: Optional[str] = None
    impact_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    missing: List[str] = Field(default_factory=list)
    age_minutes: Optional[float] = None


# ---------------------------------------------------------------------------
# breaking news (spec §4, §5)
# ---------------------------------------------------------------------------

class ScoreBreakdownSchema(BaseModel):
    score: float
    level: BreakingLevel
    components: Dict[str, float] = Field(default_factory=dict)
    weights: Dict[str, float] = Field(default_factory=dict)


class BreakingNewsSchema(BaseModel):
    """A breaking-news event, canonical for its cluster."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    article_id: Optional[int] = None
    article_url: Optional[str] = None
    title: str
    publisher: str
    published_at: datetime
    url: str
    image: Optional[str] = None
    excerpt: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    data_mode: DataMode = DataMode.UNKNOWN

    breaking_score: float = Field(..., ge=0, le=100)
    breaking_level: BreakingLevel
    entity_importance: Optional[float] = None
    mention_velocity: Optional[float] = None
    topic_acceleration: Optional[float] = None
    source_reliability: Optional[float] = None
    score_components: Optional[Dict[str, float]] = None
    score_weights: Optional[Dict[str, float]] = None

    cluster_id: Optional[str] = None
    cluster_size: int = 1
    related_articles: List[int] = Field(default_factory=list)

    affected_entities: List[str] = Field(default_factory=list)
    affected_indices: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    market_associations: Dict[str, Any] = Field(default_factory=dict)
    impact_detected: bool = False
    impact_data: Optional[Dict[str, Any]] = None

    ai_summary: Optional[str] = None
    ai_summary_model: Optional[str] = None
    ai_summary_generated_at: Optional[datetime] = None
    ai_summary_is_ai_generated: bool = True

    #: Display-ready relative age, computed from the publisher timestamp.
    time_ago: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BreakingFeedMeta(BaseModel):
    hours: int
    min_score: float
    generated_at: datetime
    total_events: int
    breaking_count: int
    significant_count: int
    articles_analyzed: int
    clusters_found: int
    sources_consulted: int
    providers: List[Dict[str, Any]] = Field(default_factory=list)
    disclaimer: str = (
        "News events are ranked from real publisher timestamps and content. "
        "Market movements shown are observed after publication and do not imply causation."
    )


class BreakingFeedResponse(BaseModel):
    items: List[BreakingNewsSchema]
    meta: BreakingFeedMeta


# ---------------------------------------------------------------------------
# topics (spec §11, §12, §13, §14)
# ---------------------------------------------------------------------------

class NewsTopicSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_name: str
    normalized_name: str
    topic_type: str = "LEXICON"
    category: Optional[str] = None
    mention_count: int = 0
    article_count: int = 0
    article_velocity: Optional[float] = None
    source_count: int = 0
    recency_score: Optional[float] = None
    related_activity: Optional[float] = None
    trend_score: float = Field(..., ge=0, le=100)
    trend_direction: TrendDirection = TrendDirection.STABLE
    trend_velocity: Optional[float] = None
    trend_components: Optional[Dict[str, float]] = None
    trend_weights: Optional[Dict[str, float]] = None
    related_entities: List[str] = Field(default_factory=list)
    related_stocks: List[str] = Field(default_factory=list)
    related_indices: List[str] = Field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TopicTimelineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    topic_id: str
    timestamp: datetime
    mention_count: int = 0
    article_count: int = 0
    source_count: int = 0
    trend_score: Optional[float] = None
    related_activity: Optional[float] = None


class TopicArticleSchema(BaseModel):
    """A compact article row used inside topic detail."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    publisher: Optional[str] = None
    published_at: Optional[datetime] = None
    url: str
    excerpt: Optional[str] = None
    impact_score: Optional[float] = None
    event_type: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    data_mode: DataMode = DataMode.UNKNOWN


class TopicDetailResponse(BaseModel):
    topic: NewsTopicSchema
    timeline: List[TopicTimelineSchema] = Field(default_factory=list)
    articles: List[TopicArticleSchema] = Field(default_factory=list)
    impact_events: List["MarketImpactEventSchema"] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    generated_at: datetime


class TopicsResponse(BaseModel):
    topics: List[NewsTopicSchema]
    meta: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# market impact (spec §7, §9, §10)
# ---------------------------------------------------------------------------

class ImpactSeriesPoint(BaseModel):
    timestamp: datetime
    close: Optional[float] = None
    volume: Optional[float] = None


class MarketImpactEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    #: Absent for an ad-hoc analysis that was measured on request and not stored.
    id: Optional[str] = None
    article_id: Optional[int] = None
    breaking_news_id: Optional[str] = None
    entity: str
    entity_type: str = "STOCK"
    provider_symbol: Optional[str] = None
    data_source: Optional[str] = None

    news_published_at: datetime
    observation_window: str
    observation_started_at: Optional[datetime] = None
    observation_ended_at: Optional[datetime] = None
    bars_before: int = 0
    bars_after: int = 0
    window_available: bool = False

    market_data_before: Optional[Dict[str, Any]] = None
    market_data_after: Optional[Dict[str, Any]] = None
    series: List[ImpactSeriesPoint] = Field(default_factory=list)

    price_change: Optional[float] = None
    price_change_percent: Optional[float] = None
    volume_change: Optional[float] = None
    volume_change_percent: Optional[float] = None
    max_favorable_excursion_percent: Optional[float] = None
    max_adverse_excursion_percent: Optional[float] = None
    realized_volatility_percent: Optional[float] = None

    impact_magnitude: ImpactMagnitude = ImpactMagnitude.NONE
    correlation_score: Optional[float] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ProbabilityMovementSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    article_id: Optional[int] = None
    breaking_news_id: Optional[str] = None
    market_id: str
    market_name: Optional[str] = None
    market_url: Optional[str] = None
    news_published_at: datetime
    observation_window: str = "1h"
    probability_before: Optional[float] = None
    probability_after: Optional[float] = None
    probability_change: Optional[float] = None
    movement_direction: str = "FLAT"
    impact_magnitude: ImpactMagnitude = ImpactMagnitude.NONE
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    series: List[Dict[str, Any]] = Field(default_factory=list)
    source_reliability: Optional[float] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# sources (spec §16)
# ---------------------------------------------------------------------------

class SourceMetadataSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    publisher: str
    source_url: Optional[str] = None
    source_type: str = "RSS"
    region: Optional[str] = None
    category: Optional[str] = None
    feed_key: Optional[str] = None
    reliability_score: float = Field(..., ge=0, le=1)
    accuracy_score: Optional[float] = None
    timeliness_score: Optional[float] = None
    completeness_score: Optional[float] = None
    article_count: int = 0
    breaking_count: int = 0
    last_published: Optional[datetime] = None
    last_retrieved: Optional[datetime] = None
    status: SourceStatus = SourceStatus.ACTIVE
    error_count: int = 0
    consecutive_errors: int = 0
    last_error: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SourcesResponse(BaseModel):
    sources: List[SourceMetadataSchema]
    summary: Dict[str, Any] = Field(default_factory=dict)
    feed_health: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime


# ---------------------------------------------------------------------------
# ingestion (spec §1, §2, §19)
# ---------------------------------------------------------------------------

class ProviderReportSchema(BaseModel):
    name: str
    ok: bool
    fetched: int = 0
    normalized: int = 0
    rejected: int = 0
    duplicates: int = 0
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    missing_fields: Dict[str, int] = Field(default_factory=dict)


class IngestReportSchema(BaseModel):
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    stored_articles: int
    corpus_articles: int
    breaking_events: int
    topics_updated: int
    impact_events: int
    probability_movements: int
    providers: List[ProviderReportSchema] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ClusterSchema(BaseModel):
    cluster_id: str
    canonical_article_id: Optional[int] = None
    title: str
    publisher: Optional[str] = None
    cluster_size: int
    publishers: List[str] = Field(default_factory=list)
    article_ids: List[int] = Field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    time_span_hours: float = 0.0
    symbols: List[str] = Field(default_factory=list)
    terms: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------

class BreakingNewsRequest(BaseModel):
    hours: int = Field(default=24, ge=1, le=168)
    min_score: float = Field(default=0, ge=0, le=100)
    category: Optional[str] = None
    entity: Optional[str] = None
    level: Optional[BreakingLevel] = None
    limit: int = Field(default=50, ge=1, le=200)


class TopicsRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    min_trend_score: float = Field(default=0, ge=0, le=100)
    category: Optional[str] = None
    topic_type: Optional[str] = None


class MarketImpactRequest(BaseModel):
    article_id: Optional[int] = None
    url: Optional[str] = None
    entity: Optional[str] = None
    entity_type: str = Field(default="STOCK", pattern="^(STOCK|INDEX|COMMODITY|FOREX|CRYPTO|FORECAST|AUTO)$")
    observation_window: Optional[str] = Field(default=None, pattern="^(5m|15m|30m|1h|4h|24h)$")
    #: Explicit anchor for an ad-hoc analysis when there is no stored event to
    #: link to. Must be a real publication timestamp — the analyzer never
    #: substitutes "now", because that would fabricate a window.
    published_at: Optional[datetime] = None
    refresh: bool = False


class ImpactWindowAnalysis(BaseModel):
    """All observation windows that hold enough data for one entity."""

    entity: str
    entity_type: str
    news_published_at: datetime
    windows: List[MarketImpactEventSchema] = Field(default_factory=list)
    unavailable_windows: List[str] = Field(default_factory=list)
    disclaimer: str = (
        "Windows are only reported when real timestamped bars exist on both sides "
        "of publication. Movements are observed, not causal."
    )


class ProbabilityMovementRequest(BaseModel):
    market_id: Optional[str] = None
    article_id: Optional[int] = None
    observation_window: str = Field(default="1h", pattern="^(5m|15m|30m|1h|4h|24h)$")
    refresh: bool = False


TopicDetailResponse.model_rebuild()


__all__ = [
    "BreakingLevel",
    "TrendDirection",
    "ImpactMagnitude",
    "DataMode",
    "SourceStatus",
    "EntitySchema",
    "NormalizedArticleSchema",
    "ScoreBreakdownSchema",
    "BreakingNewsSchema",
    "BreakingFeedMeta",
    "BreakingFeedResponse",
    "NewsTopicSchema",
    "TopicTimelineSchema",
    "TopicArticleSchema",
    "TopicDetailResponse",
    "TopicsResponse",
    "ImpactSeriesPoint",
    "MarketImpactEventSchema",
    "ProbabilityMovementSchema",
    "SourceMetadataSchema",
    "SourcesResponse",
    "ProviderReportSchema",
    "IngestReportSchema",
    "ClusterSchema",
    "BreakingNewsRequest",
    "TopicsRequest",
    "MarketImpactRequest",
    "ImpactWindowAnalysis",
    "ProbabilityMovementRequest",
]
