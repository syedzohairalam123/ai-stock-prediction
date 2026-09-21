"""
SQLAlchemy ORM models for Phase 17 — Real-Time Breaking News + Trending Topics +
Market Impact Intelligence.

Design rules (the same honesty contract the rest of the app follows):

* Every row is derived from a **real** stored article, a **real** market bar, or
  a **real** Phase 14 forecast point. There is no seed row and no column that
  exists only to be filled with a plausible-looking number.
* Timestamps are naive UTC in the database (see :mod:`..timeutil`) because
  SQLAlchemy's SQLite DATETIME type drops tzinfo; the API layer re-attaches UTC
  on the way out.
* Nothing here is destructive: tables are create-only, and ``init_db`` already
  handles append-only column additions for older databases.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from ...db import Base
from ..timeutil import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class BreakingNews(Base):
    """One breaking-news event, keyed to the underlying stored article.

    ``cluster_size`` / ``related_articles`` are how the same event reported by
    five outlets is presented once, with the other four attached — never as five
    independent stories.
    """

    __tablename__ = "breaking_news"

    id = Column(String, primary_key=True, default=_uuid)
    #: FK to the real stored article this event canonicalises.
    article_id = Column(
        Integer, ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=True
    )
    #: The article's own URL — retained so the row stays identifiable even if the
    #: article is later pruned from the corpus.
    article_url = Column(String(1000))

    # --- normalized article fields (spec §3) -----------------------------
    title = Column(String(600), nullable=False, index=True)
    publisher = Column(String(150), nullable=False)
    published_at = Column(DateTime, nullable=False, index=True)
    url = Column(String(1000), nullable=False)
    image = Column(String(1000))
    excerpt = Column(Text)
    category = Column(String(60))
    #: Which feeder the article came from (``rss:dawn_business``, ``newsapi``, …).
    source = Column(String(80), index=True)
    #: LIVE | RECENT | STALE | UNKNOWN — computed from the publisher timestamp.
    data_mode = Column(String(12), default="UNKNOWN")

    # --- breaking detection ---------------------------------------------
    breaking_score = Column(Float, nullable=False, index=True)
    breaking_level = Column(String(20), nullable=False, index=True)
    entity_importance = Column(Float)
    mention_velocity = Column(Float)
    topic_acceleration = Column(Float)
    source_reliability = Column(Float)
    #: Full component breakdown of the score, so the number is inspectable.
    score_components = Column(JSON)
    #: The weights that were active when the score was computed.
    score_weights = Column(JSON)

    # --- clustering ------------------------------------------------------
    cluster_id = Column(String(80), index=True)
    cluster_size = Column(Integer, default=1)
    related_articles = Column(JSON, default=list)  # [article_id, ...]

    # --- entity / market association ------------------------------------
    affected_entities = Column(JSON, default=list)  # ["OGDC", "KSE100", ...]
    affected_indices = Column(JSON, default=list)
    topics = Column(JSON, default=list)
    market_associations = Column(JSON, default=dict)
    impact_detected = Column(Boolean, default=False)
    impact_data = Column(JSON)

    # --- AI summarization (clearly labelled when present) ---------------
    ai_summary = Column(Text)
    ai_summary_model = Column(String(80))
    ai_summary_generated_at = Column(DateTime)
    ai_summary_error = Column(Text)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_breaking_score_created", "breaking_score", "created_at"),
        Index("idx_bn_publisher_created", "publisher", "created_at"),
        Index("idx_bn_cluster", "cluster_id"),
        Index("idx_bn_level_published", "breaking_level", "published_at"),
    )


class NewsTopic(Base):
    """A trending topic derived from measurable activity in the stored corpus."""

    __tablename__ = "news_topics"

    id = Column(String, primary_key=True, default=_uuid)
    topic_name = Column(String(200), nullable=False, index=True)
    normalized_name = Column(String(200), nullable=False, unique=True, index=True)
    #: "LEXICON" (curated finance topic), "SYMBOL" or "KEYWORD" (TF-IDF term).
    topic_type = Column(String(20), default="LEXICON")
    category = Column(String(60))
    mention_count = Column(Integer, default=0)
    article_count = Column(Integer, default=0)
    article_velocity = Column(Float)  # mentions per hour inside the velocity window
    source_count = Column(Integer, default=0)
    recency_score = Column(Float)
    related_activity = Column(Float)
    trend_score = Column(Float, nullable=False, index=True)
    trend_direction = Column(String(20), default="STABLE")
    trend_velocity = Column(Float)
    #: Trend-score components, for the same "no black box" reason as above.
    trend_components = Column(JSON)
    trend_weights = Column(JSON)
    related_entities = Column(JSON, default=list)
    related_stocks = Column(JSON, default=list)
    related_indices = Column(JSON, default=list)
    sample_article_ids = Column(JSON, default=list)
    first_seen = Column(DateTime, index=True)
    last_seen = Column(DateTime, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("idx_topic_trend_last_seen", "trend_score", "last_seen"),)


class TopicTimeline(Base):
    """An hourly bucket of a topic's measurable activity (spec §14 timeline)."""

    __tablename__ = "topic_timeline"

    id = Column(String, primary_key=True, default=_uuid)
    topic_id = Column(String, ForeignKey("news_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    mention_count = Column(Integer, default=0)
    article_count = Column(Integer, default=0)
    source_count = Column(Integer, default=0)
    trend_score = Column(Float)
    related_activity = Column(Float)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (Index("idx_topic_ts", "topic_id", "timestamp"),)


class MarketImpactEvent(Base):
    """An *observed* market movement in a window around a news publication.

    This row never claims causation. ``notes`` repeats the label on every record
    so a consumer that reads a single row still sees it.
    """

    __tablename__ = "market_impact_events"

    id = Column(String, primary_key=True, default=_uuid)
    article_id = Column(Integer, ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=True)
    breaking_news_id = Column(String, ForeignKey("breaking_news.id", ondelete="CASCADE"), nullable=True, index=True)
    entity = Column(String(40), nullable=False, index=True)
    entity_type = Column(String(20), default="STOCK")  # STOCK | INDEX | COMMODITY | FOREX | CRYPTO | FORECAST
    #: Provider symbol actually queried (``OGDC.KA``, ``BTC-USD``, ``GC=F`` …).
    provider_symbol = Column(String(40))
    data_source = Column(String(40))

    news_published_at = Column(DateTime, nullable=False, index=True)
    observation_window = Column(String(6), nullable=False)  # 5m|15m|30m|1h|4h|24h
    observation_started_at = Column(DateTime)
    observation_ended_at = Column(DateTime)
    bars_before = Column(Integer, default=0)
    bars_after = Column(Integer, default=0)
    #: True only when the window held at least ``min_bars_for_window`` real bars
    #: on BOTH sides. A window with too little data is reported unavailable.
    window_available = Column(Boolean, default=False)

    market_data_before = Column(JSON)  # {"close":…,"volume":…,"as_of":…}
    market_data_after = Column(JSON)
    #: Real timestamped bars spanning the window — what the sparkline draws.
    series = Column(JSON, default=list)

    price_change = Column(Float)
    price_change_percent = Column(Float)
    volume_change = Column(Float)
    volume_change_percent = Column(Float)
    max_favorable_excursion_percent = Column(Float)
    max_adverse_excursion_percent = Column(Float)
    realized_volatility_percent = Column(Float)

    impact_magnitude = Column(String(10), default="NONE")
    correlation_score = Column(Float)
    confidence = Column(Float)
    source_reliability = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("idx_impact_entity_published", "entity", "news_published_at"),
        Index("idx_impact_magnitude", "impact_magnitude"),
        Index("idx_impact_window", "observation_window", "news_published_at"),
    )


class ProbabilityMovement(Base):
    """Observed probability movement for a Phase 14 forecast market.

    Only ever populated from real CLOB trade history; a market with no traded
    history produces no row (never a synthetic ``before``/``after`` pair).
    """

    __tablename__ = "probability_movements"

    id = Column(String, primary_key=True, default=_uuid)
    article_id = Column(Integer, ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=True)
    breaking_news_id = Column(String, ForeignKey("breaking_news.id", ondelete="CASCADE"), nullable=True, index=True)
    market_id = Column(String(160), nullable=False, index=True)
    market_name = Column(String(400))
    market_url = Column(String(1000))
    news_published_at = Column(DateTime, nullable=False)
    observation_window = Column(String(6), default="1h")
    probability_before = Column(Float)  # percent 0-100
    probability_after = Column(Float)
    probability_change = Column(Float)  # percentage points
    movement_direction = Column(String(10), default="FLAT")
    impact_magnitude = Column(String(10), default="NONE")
    source_name = Column(String(120))
    source_url = Column(String(1000))
    series = Column(JSON, default=list)  # [{"timestamp":…, "yesProbability":…}]
    source_reliability = Column(Float)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (Index("idx_prob_market_published", "market_id", "news_published_at"),)


class SourceMetadata(Base):
    """Publisher reliability / health tracking (spec §16).

    A publisher's ``reliability_score`` starts from the ranked quality prior in
    ``news_analytics.SOURCE_TIERS`` and is then adjusted by *observed* behaviour
    (share of high-impact coverage, ingestion failures). A social post is
    therefore never treated as equivalent to an official filing: its prior is
    lower to begin with and its errors are recorded here.
    """

    __tablename__ = "source_metadata"

    id = Column(String, primary_key=True, default=_uuid)
    publisher = Column(String(150), nullable=False, unique=True, index=True)
    source_url = Column(String(1000))
    source_type = Column(String(30), default="RSS")  # RSS | API | OFFICIAL | SOCIAL
    region = Column(String(10))
    category = Column(String(60))
    #: The registry key of the feed this publisher was first seen on.
    feed_key = Column(String(80))
    reliability_score = Column(Float, nullable=False, index=True)  # 0-1
    accuracy_score = Column(Float)
    timeliness_score = Column(Float)
    completeness_score = Column(Float)
    article_count = Column(Integer, default=0)
    breaking_count = Column(Integer, default=0)
    last_published = Column(DateTime)
    last_retrieved = Column(DateTime)
    status = Column(String(20), default="ACTIVE")  # ACTIVE | DEGRADED | INACTIVE
    error_count = Column(Integer, default=0)
    consecutive_errors = Column(Integer, default=0)
    last_error = Column(Text)
    additional_data = Column(JSON)  # named to avoid the reserved `metadata` attr
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (Index("idx_source_reliability_status", "reliability_score", "status"),)


__all__ = [
    "BreakingNews",
    "NewsTopic",
    "TopicTimeline",
    "MarketImpactEvent",
    "ProbabilityMovement",
    "SourceMetadata",
]
