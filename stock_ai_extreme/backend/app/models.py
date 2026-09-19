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
