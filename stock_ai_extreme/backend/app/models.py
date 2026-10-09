"""
Phase 3 (persistence) + Phase 16 (watchlist) ORM models.

Kept intentionally small: this app has no auth yet (that's a later phase),
so these tables are single-tenant for now. Adding a `user_id` foreign key
later is a small migration, not a redesign — nothing here assumes there's
only ever one user, it just doesn't enforce multi-user separation yet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PredictionRecord(Base):
    """One row per prediction ever generated. This is what Phase 9's
    backtesting and any future 'how accurate has this model really been'
    view reads from — real historical predictions, not simulated ones."""
    __tablename__ = "prediction_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    model: Mapped[str] = mapped_column(String(20))
    horizon: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    data_source: Mapped[str] = mapped_column(String(40))
    data_status: Mapped[str] = mapped_column(String(20))
    predictions: Mapped[list] = mapped_column(JSON)   # the list of {date, price, lower, upper, ...}
    metrics: Mapped[dict] = mapped_column(JSON)        # {mae, rmse, ...}
    # Filled in later, once the forecast date has actually passed — see Phase 9's
    # accuracy-tracking use of this table. NULL means "not resolved yet".
    actual_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("ticker", name="uq_watchlist_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    #: Phase 9 — explicit manual ordering. 0 = "never reordered" so existing rows
    #: keep their added_at order; any reorder assigns 1..n. Exposed as `sort_order`
    #: in the API (spec WatchlistItem shape) while the column keeps the short name.
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base):
    """Phase 17 — smart alerts. `alert_type` is one of: price_above,
    price_below, pct_change, rsi_overbought, rsi_oversold."""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    alert_type: Mapped[str] = mapped_column(String(30))
    threshold: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    triggered_value: Mapped[float | None] = mapped_column(Float, nullable=True)


class PortfolioHolding(Base):
    """Phase 10 — portfolio tracker. One row per tracked position: how many
    shares were bought at what average cost. Current price is always fetched
    live at read time (never stored), so P&L is always honest and current."""
    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    shares: Mapped[float] = mapped_column(Float)
    avg_cost: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class NewsArticle(Base):
    """Phase 8 — Professional News & Financial Intelligence Desk.
    
    Stores news articles from multiple real sources (NewsAPI, Finnhub, Alpha Vantage,
    yfinance). Articles are deduplicated by source URL. Related symbols are stored
    as JSON array for flexible ticker linking. Categories follow financial news
    taxonomy. Priority and source type prepare for advanced filtering."""
    __tablename__ = "news_articles"
    __table_args__ = (UniqueConstraint("source_url", name="uq_news_source_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    slug: Mapped[str] = mapped_column(String(600), index=True)
    publisher: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[str | None] = mapped_column(String(10000), nullable=True)
    category: Mapped[str] = mapped_column(String(50), index=True)  # PSX, Stocks, Economy, etc.
    tags: Mapped[list] = mapped_column(JSON, default=list)  # ["earnings", "dividend"]
    related_symbols: Mapped[list] = mapped_column(JSON, default=list)  # ["OGDC", "HBL"]
    related_indices: Mapped[list] = mapped_column(JSON, default=list)  # ["KSE100", "KSE30"]
    source_url: Mapped[str] = mapped_column(String(1000), unique=True)
    source_type: Mapped[str] = mapped_column(String(30))  # ARTICLE, PRESS_RELEASE, PSX_FILING, etc.
    priority: Mapped[str] = mapped_column(String(10), default="NORMAL")  # HIGH, NORMAL, LOW
    data_source: Mapped[str] = mapped_column(String(40))  # newsapi, finnhub, alpha_vantage, yfinance, rss:<feed>
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_label: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Phase 8 analytics layer -------------------------------------------
    # Every field below is computed by `news_analytics` from the article's own
    # text; none of it is imported from the publisher, invented, or defaulted
    # to a fake value. All are nullable on purpose: an article ingested before
    # the analyser existed simply has no analysis, which is honest.
    data_mode: Mapped[str] = mapped_column(String(12), default="LIVE")  # LIVE | DELAYED | DEMO
    event_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    impact_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    entities: Mapped[list] = mapped_column(JSON, default=list)  # [{type,value,label}]
    topics: Mapped[list] = mapped_column(JSON, default=list)
    #: 64-bit Charikar SimHash of the headline+lede. Signed 64-bit so SQLite and
    #: Postgres agree; used for near-duplicate suppression, never displayed.
    simhash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: MinHash shingle signature (fixed-width hex, comma-separated). This is the
    #: signal near-duplicate suppression actually decides on — see
    #: `news_analytics.minhash_signature` for why SimHash alone is not enough on
    #: article-length text.
    shingle_signature: Mapped[str | None] = mapped_column(String(600), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feed_key: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Transaction(Base):
    """Phase 9 — Portfolio transaction tracking with full accounting.
    
    Records all BUY and SELL transactions for portfolio positions. Supports
    multiple transaction types, fees, and complete audit trail. Average cost
    and P&L are calculated from these transactions, not stored directly.
    This enables FIFO, LIFO, or weighted average cost basis methods."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # Future: auth support
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    transaction_type: Mapped[str] = mapped_column(String(10))  # BUY, SELL
    quantity: Mapped[float] = mapped_column(Float)  # Number of shares
    price: Mapped[float] = mapped_column(Float)  # Price per share at transaction
    fees: Mapped[float] = mapped_column(Float, default=0.0)  # Brokerage, taxes, etc.
    total_amount: Mapped[float] = mapped_column(Float)  # Calculated: (quantity * price) + fees for BUY, - fees for SELL
    transaction_date: Mapped[datetime] = mapped_column(DateTime, index=True)  # User-specified date
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    broker: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Optional broker name
    account: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Optional account identifier
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)




class Conversation(Base):
    """Phase 10 — AI Financial Assistant conversations.
    
    Stores complete conversation history with context snapshots. Each conversation
    has a title, timestamp, and associated messages. Context snapshot preserves
    what the user was viewing when they started the conversation."""
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))  # Auto-generated or user-edited
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # {symbol, entityType, page, etc.}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Message(Base):
    """Phase 10 — AI conversation messages.
    
    Individual messages within a conversation. Stores role (user/assistant/system),
    content, optional citations, and processing metadata like token usage."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(20))  # user, assistant, system
    content: Mapped[str] = mapped_column(String(10000))
    context_used: Mapped[dict] = mapped_column(JSON, default=dict)  # What context was sent with this message
    citations: Mapped[list] = mapped_column(JSON, default=list)  # Sources referenced in response
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {prompt_tokens, completion_tokens, total}
    model: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Which model generated this
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class CombinationRecord(Base):
    """Phase 15.2 — a persisted multi-event combination analysis.

    Stores the selected events (with the probability each was captured at),
    the independence product and the correlation-adjusted probability. Rows are
    addressable by a client-generated stable id so the frontend's localStorage
    records can be mirrored server-side without id churn."""
    __tablename__ = "combination_records"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    selections: Mapped[list] = mapped_column(JSON, default=list)  # [{marketId, outcome, probability, ...}]
    combined_probability: Mapped[float] = mapped_column(Float, default=0.0)
    correlation_adjusted_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    correlation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CombinationSnapshot(Base):
    """Phase 15.2 — append-only probability snapshots for a combination.

    Each row is one captured reading of a combination's probabilities, so a
    saved analysis gains a real history over time (the same idea as
    `prediction_history`, applied to combined events)."""
    __tablename__ = "combination_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    combination_id: Mapped[str] = mapped_column(String(80), index=True)
    combined_probability: Mapped[float] = mapped_column(Float)
    correlation_adjusted_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    selections: Mapped[list] = mapped_column(JSON, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class WorkspaceBlob(Base):
    """Phase 11/12 — generic JSON document store keyed by a stable string.

    Used by the workspace and chart-workspace persistence routes. A single
    key/value table keeps the schema additive: new document kinds need only a
    new key, never a new table."""
    __tablename__ = "workspace_blobs"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    #: Always a JSON object; callers that hold a list wrap it as `{"items": [...]}`
    #: so this column's type stays a plain dict.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AgentTask(Base):
    """Phase 10 — AI agent task execution history.
    
    Tracks specialized agent tasks like market analysis, sentiment analysis, stock
    comparison. Records task type, status, input parameters, and results for
    observability and debugging."""
    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(50), index=True)  # MARKET_ANALYSIS, STOCK_COMPARISON, etc.
    agent_name: Mapped[str] = mapped_column(String(50))  # Which agent handled it
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, RUNNING, COMPLETED, FAILED
    input_params: Mapped[dict] = mapped_column(JSON, default=dict)  # Request parameters
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Agent output
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # Error message if failed
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TrendObservation(Base):
    """Phase 19 — one real trend observation for one discoverable entity.

    Rows are appended whenever the trending feed is computed (throttled per
    entity) and by the background sampler. Each row is a genuine measurement
    taken at that moment — {timestamp, activity, score} — so sparklines draw
    observed history only. An entity with fewer than two rows honestly has
    "no history yet" rather than a fabricated curve."""
    __tablename__ = "trend_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    #: The entity's real activity metric at observation time (unit depends on
    #: the entity type — never mixed between types in one series).
    activity: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The aggregate trend score (0–100) computed from real signals then.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    popularity: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="sample")


class DiscoveryEvent(Base):
    """Phase 19 — one recorded real interest event (view or search match).

    These rows *are* the interest signal: they count actions users actually
    took in this app. Nothing here is estimated, and a brand-new install has
    zero rows — which the API reports as 0 recorded interest, not as a made-up
    popularity number."""
    __tablename__ = "discovery_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    #: "view" (an entity page/card was opened) or "search" (a query matched).
    kind: Mapped[str] = mapped_column(String(20), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class CentralBank(Base):
    """Phase 23A — Central Bank registry.

    Stores metadata for major central banks worldwide. Each bank has a unique
    identifier, country, currency, timezone, and data source configuration.
    The architecture supports adding new banks without engine redesign."""
    __tablename__ = "central_banks"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g., "FED", "BOJ", "ECB"
    name: Mapped[str] = mapped_column(String(100), index=True)  # e.g., "Federal Reserve", "Bank of Japan"
    country: Mapped[str] = mapped_column(String(100))  # e.g., "United States", "Japan"
    currency: Mapped[str] = mapped_column(String(10))  # e.g., "USD", "JPY"
    timezone: Mapped[str] = mapped_column(String(50))  # e.g., "America/New_York", "Asia/Tokyo"
    source: Mapped[str] = mapped_column(String(50))  # Data source: "federal_reserve", "boj", "ecb", etc.
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PolicyMeeting(Base):
    """Phase 23A — Central bank policy meeting schedule and status.

    Stores scheduled monetary policy meetings with status tracking. Meetings
    are sourced from official central bank publications (FOMC calendar, BOJ
    monetary policy meetings, etc.). Dates are stored in UTC for consistent
    countdown calculations."""
    __tablename__ = "policy_meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    central_bank_id: Mapped[str] = mapped_column(String(20), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    timezone: Mapped[str] = mapped_column(String(50))  # Meeting's local timezone
    status: Mapped[str] = mapped_column(String(20), index=True)  # UPCOMING, IN_PROGRESS, COMPLETED, CANCELLED, UNKNOWN
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # Official source URL
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # When source published this
    meeting_type: Mapped[str] = mapped_column(String(50))  # REGULAR, EMERGENCY, UNSCHEDULED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PolicyDecision(Base):
    """Phase 23A — Monetary policy decision records.

    Stores actual policy rate decisions made at meetings. Includes previous
    rate, new rate, and calculated basis point change. Direction is derived
    from the change (HIKE, CUT, UNCHANGED). Never hardcodes bps values."""
    __tablename__ = "policy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(Integer, index=True)
    previous_rate: Mapped[float] = mapped_column(Float)  # Rate before decision (e.g., 5.25)
    new_rate: Mapped[float] = mapped_column(Float)  # Rate after decision (e.g., 5.50)
    change_bps: Mapped[int] = mapped_column(Integer)  # Calculated: (new_rate - previous_rate) * 100
    direction: Mapped[str] = mapped_column(String(20))  # HIKE, CUT, UNCHANGED
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(50))  # Source of decision data
    source_document: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # Link to official statement
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class PolicyExpectation(Base):
    """Phase 23A — Market-implied policy expectations from legitimate sources.

    Stores sourced expectations (not predictions) where available from reputable
    providers. Clearly labeled as SOURCE-DERIVED EXPECTATION. Never manufactures
    probabilities. Records methodology and observation timestamp."""
    __tablename__ = "policy_expectations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(50))  # Source name (e.g., "CME FedWatch", "Bloomberg")
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    expected_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)  # HIKE, CUT, UNCHANGED
    expected_rate_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_rate_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_hike: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_cut: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_unchanged: Mapped[float | None] = mapped_column(Float, nullable=True)
    methodology: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Real link to the observation's source (e.g. the exact decision market).
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class MacroSeries(Base):
    """Phase 23A — Macroeconomic time-series data with revision tracking.

    Stores economic indicators with observation date, release date, and
    revision history. Critical for backtesting correctness — observation date
    is when the economic activity occurred, release date is when it was published.
    Supports data revisions with timestamp tracking."""
    __tablename__ = "macro_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(String(50), index=True)  # e.g., "CPIAUCSL", "UNRATE"
    observation_date: Mapped[datetime] = mapped_column(DateTime, index=True)  # Economic activity date
    release_date: Mapped[datetime] = mapped_column(DateTime, index=True)  # Publication date
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))  # e.g., "Percent", "Index", "Billions USD"
    frequency: Mapped[str] = mapped_column(String(20))  # DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL
    source: Mapped[str] = mapped_column(String(50))  # e.g., "FRED", "BLS", "BEA"
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    initial_release: Mapped[bool] = mapped_column(default=True)  # True if this is the first published value
    revision: Mapped[int] = mapped_column(Integer, default=0)  # Revision number (0 = initial)
    revision_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # Value before revision
    data_freshness: Mapped[str] = mapped_column(String(20), default="HISTORICAL")  # LIVE, RECENT, DELAYED, HISTORICAL, STALE, UNAVAILABLE
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
