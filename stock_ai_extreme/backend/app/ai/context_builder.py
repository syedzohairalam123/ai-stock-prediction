"""
Context Builder Service (Phase 10)

Builds normalized AI context from application state. Reads current route, stock/index,
timeframe, market data, sentiment, news, and announcements to provide comprehensive
context to the AI assistant.

SECURITY:
- Only includes data required for the user's request
- Validates authorization before including portfolio data
- Never exposes sensitive/private data unnecessarily

INTEGRATION:
- Uses the real provider layer (yfinance) for live market/price data
- Reads stored NewsArticle records for news + headline sentiment
- Reads the PSX announcements feed (live or simulated) via get_announcements_feed
- Reads PortfolioHolding records for portfolio context (single-tenant app)
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
from datetime import datetime, date, timedelta, timezone
import asyncio
import structlog
import yfinance as yf
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import NewsArticle, PortfolioHolding, Transaction
from ..announcements import get_announcements_feed, AnnouncementFiltersModel
from ..news import score_text as score_headline
from ..symbols import symbol_candidates, to_yahoo_symbol

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Local helpers — yfinance price fetch executed off the event loop
# ---------------------------------------------------------------------------

def _yf_quote(ticker: str) -> Optional[dict]:
    """Fetch the latest close + previous close for *ticker* through yfinance.

    PSX tickers must go through the app's symbol map: bare ``OGDC`` returns
    *no data at all* on Yahoo while ``OGDC.KA`` returns the real quote, and
    the rest of the app resolves symbols via ``app.symbols`` — the assistant's
    private quote path must resolve identically. Every candidate from
    ``symbol_candidates`` is tried before giving up.

    Returns None when no candidate has data (the caller decides how to surface
    that). Never raises — a quote that cannot be fetched is reported as
    unavailable, never as a fabricated number.
    """
    for candidate in symbol_candidates(ticker):
        try:
            t = yf.Ticker(candidate)
            hist = t.history(period="5d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            hist = hist.dropna(subset=["Close"])
            if hist.empty:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else None
            return {
                "price": round(last, 4),
                "previous_close": round(prev, 4) if prev is not None else None,
                "change": round(last - prev, 4) if prev is not None else None,
                "change_percent": round((last - prev) / prev * 100.0, 4) if prev else None,
                "last_date": str(hist.index[-1].date()),
                "yahoo_symbol": candidate,
            }
        except Exception:
            continue
    return None


def _yf_index_quote(symbol: str) -> Optional[dict]:
    """Fetch a market index quote (tries the bare and ``^``-prefixed symbol;
    the ``.KA`` variant is covered inside ``_yf_quote``)."""
    for candidate in (symbol, f"^{symbol}"):
        result = _yf_quote(candidate)
        if result:
            return result
    return None


async def _fetch_price(ticker: str) -> Optional[dict]:
    """Async wrapper around the blocking yfinance quote fetch."""
    return await asyncio.to_thread(_yf_quote, ticker)


async def _fetch_index_price(symbol: str) -> Optional[dict]:
    """Async wrapper around the blocking yfinance index quote fetch."""
    return await asyncio.to_thread(_yf_index_quote, symbol)


async def _fetch_news_headlines(ticker: str, limit: int = 10) -> List[dict]:
    """Fetch recent news headlines from yfinance and score them.

    Used as a fallback when the DB news table has no articles for a symbol.
    """
    try:
        t = yf.Ticker(to_yahoo_symbol(ticker))
        raw_news = list(t.news or [])[:limit]
        results = []
        for item in raw_news:
            title = item.get("title") or ""
            sentiment = score_headline(title)
            results.append({
                "title": title,
                "publisher": item.get("publisher"),
                "published_at": (
                    datetime.fromtimestamp(item.get("providerPublishTime", 0), tz=timezone.utc).isoformat()
                    if item.get("providerPublishTime") else None
                ),
                "excerpt": item.get("summary", "")[:200] if item.get("summary") else None,
                "sentiment": sentiment["label"],
                "sentiment_score": sentiment["score"],
                "url": item.get("link"),
                "source": "yfinance",
            })
        return results
    except Exception as e:
        logger.warning("yfinance_news_fetch_error", error=str(e), ticker=ticker)
        return []


# ---------------------------------------------------------------------------
# Market status
# ---------------------------------------------------------------------------

# PSE regular session: Monday–Friday, 09:30–15:30 Pakistan Standard Time
# (UTC+05:00, no daylight saving). The comparison must happen on the PKT clock —
# comparing UTC hours against a PKT-based schedule (as this did before) reported
# the market open five hours early.
_PKT = timezone(timedelta(hours=5))
_PSE_SESSION_OPEN_MINUTES = 9 * 60 + 30   # 09:30 PKT
_PSE_SESSION_CLOSE_MINUTES = 15 * 60 + 30  # 15:30 PKT


def _market_status(now: Optional[datetime] = None) -> str:
    """Return 'OPEN', 'CLOSED', or 'WEEKEND' based on the PKT clock.

    This is the exchange's *session window*, not a live trading feed: public
    holidays are not modelled. It is reported as such so the assistant never
    presents the schedule as observed market state.

    ``now`` is injectable so the window can be pinned in tests.
    """
    now_pkt = (now or datetime.now(timezone.utc)).astimezone(_PKT)
    if now_pkt.weekday() >= 5:
        return "WEEKEND"
    minutes = now_pkt.hour * 60 + now_pkt.minute
    if _PSE_SESSION_OPEN_MINUTES <= minutes < _PSE_SESSION_CLOSE_MINUTES:
        return "OPEN"
    return "CLOSED"


# ---------------------------------------------------------------------------
# Context Builder
# ---------------------------------------------------------------------------

class ContextBuilder:
    """
    Builds normalized context objects for AI assistant requests.

    Central service that consolidates all context building logic.
    Frontend should not build context separately in every component.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_context(
        self,
        route: str,
        symbol: Optional[str] = None,
        entity_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        include_news: bool = True,
        include_announcements: bool = True,
        include_sentiment: bool = True,
        include_portfolio: bool = False,
        user_id: Optional[str] = None,
        max_news_items: int = 5,
        max_announcements: int = 3,
    ) -> Dict[str, Any]:
        """
        Build comprehensive context for AI requests.

        Args:
            route: Current route/page (e.g., "/stock/OGDC", "/market", "/portfolio")
            symbol: Stock symbol or index (e.g., "OGDC", "KSE100")
            entity_type: "stock" or "index"
            timeframe: Current timeframe selection (e.g., "1D", "1M", "1Y")
            include_news: Whether to include relevant news
            include_announcements: Whether to include PSX announcements
            include_sentiment: Whether to include sentiment analysis
            include_portfolio: Whether to include portfolio data (requires auth)
            user_id: User identifier (required if include_portfolio=True)
            max_news_items: Maximum news items to include
            max_announcements: Maximum announcements to include

        Returns:
            Normalized context dictionary
        """
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "route": route,
            "page_type": self._determine_page_type(route),
            "market_status": _market_status(),
        }

        # Entity context (stock or index)
        if symbol:
            context["symbol"] = symbol
            context["entity_type"] = entity_type or "stock"
            if timeframe:
                context["timeframe"] = timeframe

        # Market-level context
        if route.startswith("/market") or route == "/":
            context["market_context"] = await self._build_market_context()

        # Stock-specific context
        if symbol and entity_type == "stock":
            stock_context = await self._build_stock_context(
                symbol=symbol,
                include_news=include_news,
                include_announcements=include_announcements,
                include_sentiment=include_sentiment,
                max_news=max_news_items,
                max_announcements=max_announcements,
            )
            context["stock_context"] = stock_context

        # Index-specific context
        if symbol and entity_type == "index":
            index_context = await self._build_index_context(symbol=symbol)
            context["index_context"] = index_context

        # Portfolio context (only if authorized)
        if include_portfolio and user_id:
            portfolio_context = await self._build_portfolio_context(user_id=user_id)
            context["portfolio_context"] = portfolio_context
        elif include_portfolio and not user_id:
            logger.warning("portfolio_context_requested_without_auth")
            context["portfolio_context"] = {"error": "Not authorized"}
        elif include_portfolio:
            # Single-tenant app: portfolio is always authorized
            portfolio_context = await self._build_portfolio_context(user_id=None)
            context["portfolio_context"] = portfolio_context

        # News page context
        if route.startswith("/news"):
            news_context = await self._build_news_page_context(max_items=10)
            context["news_context"] = news_context

        return context

    def _determine_page_type(self, route: str) -> str:
        """Determine page type from route."""
        if route == "/" or route.startswith("/market"):
            return "market_overview"
        elif route.startswith("/stock/"):
            return "stock_detail"
        elif route.startswith("/index/"):
            return "index_detail"
        elif route.startswith("/portfolio"):
            return "portfolio"
        elif route.startswith("/watchlist"):
            return "watchlist"
        elif route.startswith("/news"):
            return "news"
        elif route.startswith("/announcements"):
            return "announcements"
        elif route.startswith("/sentiment"):
            return "sentiment"
        elif route.startswith("/forex"):
            return "forex_commodities"
        else:
            return "other"

    # ------------------------------------------------------------------
    # Market context
    # ------------------------------------------------------------------

    async def _build_market_context(self) -> Dict[str, Any]:
        """Build market-level context from real data only.

        Index quotes come from Yahoo's live endpoints. Yahoo does not reliably
        carry PSX index series, so when the quote is missing the block still
        carries the *real* market tone available: the news desk's stored
        headlines and their aggregate sentiment. Nothing is ever fabricated to
        fill an index gap.
        """
        indices = {}
        for name in ("KSE100", "KSE30"):
            try:
                price = await _fetch_index_price(name)
                if price:
                    indices[name] = price
                else:
                    indices[name] = {
                        "price": None,
                        "change": None,
                        "change_percent": None,
                        "source": "yfinance",
                        "status": "UNAVAILABLE",
                    }
            except Exception as e:
                logger.warning("index_price_fetch_error", index=name, error=str(e))
                indices[name] = {
                    "price": None,
                    "change": None,
                    "change_percent": None,
                    "status": "UNAVAILABLE",
                }

        market_context: Dict[str, Any] = {
            "status": "Live via yfinance provider layer",
            "indices": indices,
            "market_status": _market_status(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Tone from real headlines whenever an index quote is missing (or even
        # when it is present — headlines describe *why* the index moved).
        try:
            market_context["headline_tone"] = await self._get_market_headline_tone()
        except Exception as e:
            logger.warning("market_headline_tone_error", error=str(e))

        return market_context

    async def _get_market_headline_tone(self, max_items: int = 12) -> Dict[str, Any]:
        """Aggregate market tone from the news desk's stored headlines.

        Same data the news page shows — real publisher articles ingested by the
        background job — scored with the same sentiment model the app uses.
        """
        query = (
            select(NewsArticle)
            .order_by(desc(NewsArticle.published_at))
            .limit(max_items * 3)
        )
        result = await self.db.execute(query)
        articles = result.scalars().all()

        scored = [a for a in articles if a.sentiment_score is not None]
        if scored:
            scores = [a.sentiment_score for a in scored]
            labels = [a.sentiment_label for a in scored]
            avg = round(sum(scores) / len(scores), 4)
            bullish = sum(1 for l in labels if l and l.upper() in ("POSITIVE", "BULLISH"))
            bearish = sum(1 for l in labels if l and l.upper() in ("NEGATIVE", "BEARISH"))
        else:
            avg, bullish, bearish = 0.0, 0, 0

        if avg > 0.15:
            label = "bullish"
        elif avg < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        headlines = [
            {
                "title": a.title,
                "publisher": a.publisher,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "category": a.category,
                "sentiment_label": a.sentiment_label,
                "sentiment_score": a.sentiment_score,
            }
            for a in articles[:max_items]
        ]
        return {
            "headline_count": len(headlines),
            "headlines": headlines,
            "aggregate_sentiment": {
                "average_score": avg,
                "label": label,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "scored_count": len(scored),
            },
        }

    # ------------------------------------------------------------------
    # Stock context
    # ------------------------------------------------------------------

    async def _build_stock_context(
        self,
        symbol: str,
        include_news: bool,
        include_announcements: bool,
        include_sentiment: bool,
        max_news: int,
        max_announcements: int,
    ) -> Dict[str, Any]:
        """Build stock-specific context with live price + stored news/sentiment."""
        context: Dict[str, Any] = {
            "symbol": symbol,
            "market_status": _market_status(),
        }

        # Live price data — fetch concurrently
        price_task = _fetch_price(symbol)
        news_task = self._get_relevant_news(symbol=symbol, limit=max_news) if include_news else None
        ann_task = (
            self._get_relevant_announcements(symbol=symbol, limit=max_announcements)
            if include_announcements else None
        )
        sentiment_task = self._get_sentiment(symbol=symbol) if include_sentiment else None

        # Gather all results concurrently
        results = await asyncio.gather(
            price_task,
            news_task or asyncio.sleep(0, result=None),
            ann_task or asyncio.sleep(0, result=None),
            sentiment_task or asyncio.sleep(0, result=None),
        )

        price = results[0]
        if price:
            context.update(price)

        if include_news:
            context["recent_news"] = results[1] if results[1] is not None else []
        if include_announcements:
            context["recent_announcements"] = results[2] if results[2] is not None else []
        if include_sentiment:
            context["sentiment"] = results[3] if results[3] is not None else {
                "score": 0.0, "label": "NEUTRAL", "confidence": 0.0
            }

        return context

    async def _build_index_context(self, symbol: str) -> Dict[str, Any]:
        """Build index-specific context with live data."""
        context: Dict[str, Any] = {
            "symbol": symbol,
            "type": "index",
            "market_status": _market_status(),
        }

        # Fetch live price (index candidates need the ^-prefixed resolution)
        price = await _fetch_index_price(symbol)
        if price:
            context.update(price)

        # Fetch related news
        news = await self._get_relevant_news(symbol=symbol, limit=3)
        context["recent_news"] = news

        # Fetch sentiment
        sentiment = await self._get_sentiment(symbol=symbol)
        context["sentiment"] = sentiment

        return context

    # ------------------------------------------------------------------
    # Portfolio context
    # ------------------------------------------------------------------

    async def _build_portfolio_context(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Build portfolio context (ONLY if user is authorized).

        SECURITY: This must only be called after verifying user authorization.

        In the current single-tenant app there is no ``user_id`` column on
        ``PortfolioHolding`` or ``Transaction`` — every row belongs to the one
        tenant. When a future auth layer is added, the ``user_id`` filter can
        be re-enabled here without touching the rest of the builder.
        """
        try:
            # Get holdings — single-tenant: no user_id filter
            holdings_result = await self.db.execute(select(PortfolioHolding))
            holdings = holdings_result.scalars().all()

            # Get recent transactions
            txn_result = await self.db.execute(
                select(Transaction)
                .order_by(desc(Transaction.transaction_date))
                .limit(10)
            )
            transactions = txn_result.scalars().all()

            # Fetch live prices for each holding concurrently
            holding_tickers = [h.ticker for h in holdings]
            price_tasks = [_fetch_price(ticker) for ticker in holding_tickers]
            live_prices = await asyncio.gather(*price_tasks, return_exceptions=True)

            enriched_holdings = []
            total_cost = 0.0
            total_value = 0.0
            for h, live in zip(holdings, live_prices):
                cost_basis = h.shares * h.avg_cost
                total_cost += cost_basis
                price_val = None
                market_value = None
                pnl = None
                pnl_pct = None
                if isinstance(live, dict) and live:
                    price_val = live.get("price")
                    if price_val is not None:
                        market_value = round(price_val * h.shares, 4)
                        total_value += market_value
                        pnl = round(market_value - cost_basis, 4)
                        pnl_pct = round((price_val - h.avg_cost) / h.avg_cost * 100.0, 4) if h.avg_cost else None

                enriched_holdings.append({
                    "symbol": h.ticker,
                    "shares": h.shares,
                    "avg_cost": round(h.avg_cost, 4),
                    "cost_basis": round(cost_basis, 4),
                    "current_price": price_val,
                    "market_value": market_value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "note": h.note,
                })

            positions_count = len(holdings)
            total_pnl = round(total_value - total_cost, 4) if total_value else None
            total_pnl_pct = round(total_pnl / total_cost * 100.0, 4) if total_cost and total_pnl is not None else None

            return {
                "positions_count": positions_count,
                "total_cost_basis": round(total_cost, 4),
                "total_value": round(total_value, 4) if total_value else None,
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "holdings": enriched_holdings,
                "recent_transactions_count": len(transactions),
                "transactions": [
                    {
                        "symbol": t.symbol,
                        "type": t.transaction_type,
                        "quantity": t.quantity,
                        "price": round(t.price, 4),
                        "total_amount": round(t.total_amount, 4),
                        "date": t.transaction_date.isoformat() if t.transaction_date else None,
                    }
                    for t in transactions
                ],
            }
        except Exception as e:
            logger.error("portfolio_context_build_error", error=str(e))
            return {"error": "Failed to load portfolio context"}

    # ------------------------------------------------------------------
    # News page context
    # ------------------------------------------------------------------

    async def _build_news_page_context(self, max_items: int) -> Dict[str, Any]:
        """Build context for news page from stored NewsArticle records."""
        try:
            query = (
                select(NewsArticle)
                .order_by(desc(NewsArticle.published_at))
                .limit(max_items)
            )
            result = await self.db.execute(query)
            articles = result.scalars().all()

            # Build sentiment aggregate
            sentiments = [a.sentiment_score for a in articles if a.sentiment_score is not None]
            if sentiments:
                avg_score = round(sum(sentiments) / len(sentiments), 4)
                labels = [a.sentiment_label for a in articles if a.sentiment_label]
                bullish = sum(1 for l in labels if l and l.upper() in ("POSITIVE", "BULLISH"))
                bearish = sum(1 for l in labels if l and l.upper() in ("NEGATIVE", "BEARISH"))
                if avg_score > 0.15:
                    agg_label = "bullish"
                elif avg_score < -0.15:
                    agg_label = "bearish"
                else:
                    agg_label = "neutral"
            else:
                avg_score = 0.0
                agg_label = "neutral"
                bullish = 0
                bearish = 0

            return {
                "recent_headlines_count": len(articles),
                "recent_headlines": [
                    {
                        "title": a.title,
                        "publisher": a.publisher,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "category": a.category,
                        "sentiment_score": a.sentiment_score,
                        "sentiment_label": a.sentiment_label,
                        "impact_score": a.impact_score,
                    }
                    for a in articles
                ],
                "aggregate_sentiment": {
                    "average_score": avg_score,
                    "label": agg_label,
                    "bullish_count": bullish,
                    "bearish_count": bearish,
                },
            }
        except Exception as e:
            logger.error("news_context_build_error", error=str(e))
            return {"error": "Failed to load news context"}

    # ------------------------------------------------------------------
    # News for a specific symbol
    # ------------------------------------------------------------------

    async def _get_relevant_news(self, symbol: str, limit: int) -> List[Dict]:
        """Get news relevant to a specific symbol.

        Queries the DB-stored NewsArticle table, filtering on
        ``related_symbols`` in Python (SQLite has no native JSON-array
        contains; iterating in Python is cheap for a news table).
        """
        try:
            query = (
                select(NewsArticle)
                .order_by(desc(NewsArticle.published_at))
                .limit(limit * 5)  # fetch extra so Python filtering doesn't starve
            )
            result = await self.db.execute(query)
            articles = result.scalars().all()

            # Filter in Python for SQLite compatibility
            symbol_upper = symbol.upper()
            matching = [
                a for a in articles
                if symbol_upper in [s.upper() for s in (a.related_symbols or [])]
            ][:limit]

            if matching:
                return [
                    {
                        "title": a.title,
                        "publisher": a.publisher,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "excerpt": a.excerpt,
                        "sentiment": a.sentiment_label,
                        "sentiment_score": a.sentiment_score,
                        "url": a.source_url,
                        "impact_score": a.impact_score,
                    }
                    for a in matching
                ]

            # Fallback: fetch from yfinance news feed
            fallback = await _fetch_news_headlines(symbol, limit=limit)
            if fallback:
                return fallback

            return []
        except Exception as e:
            logger.error("relevant_news_fetch_error", error=str(e), symbol=symbol)
            return []

    # ------------------------------------------------------------------
    # Announcements for a specific symbol
    # ------------------------------------------------------------------

    async def _get_relevant_announcements(
        self, symbol: str, limit: int
    ) -> List[Dict]:
        """Get PSX announcements relevant to a specific symbol via the live
        announcements feed (uses the same cached HTTP mirror as the rest of
        the app, never fabricates content)."""
        try:
            # Real PSX filings only: the live ksestocks.com mirror (same cached
            # source the announcements page serves). The labelled demo dataset
            # (source="simulated") must never feed the assistant — it would
            # present invented "Demo Fertilizer Ltd" records as market facts.
            filters = AnnouncementFiltersModel(
                source="company",
                ticker=symbol,
                page_size=min(limit, 50),
            )
            feed = await get_announcements_feed(filters)

            items = [
                {
                    "title": ann.get("title", ""),
                    "date": ann.get("published", ""),
                    "type": ann.get("event", ""),
                    "sentiment": ann.get("sentiment", ""),
                    "url": ann.get("source_url", ""),
                    "company": ann.get("company", ""),
                }
                for ann in feed.get("items", [])
            ]
            if items:
                return items

            # The mirror answered but carried nothing for this ticker (or was
            # unreachable): say so honestly instead of silently substituting
            # anything else.
            context_note = feed.get("source_status") or "UNAVAILABLE"
            return [
                {
                    "title": (
                        "No PSX announcements found for this ticker "
                        f"(announcements source status: {context_note})."
                    ),
                    "date": None,
                    "type": "none",
                    "sentiment": None,
                    "url": None,
                    "company": None,
                }
            ]
        except Exception as e:
            logger.error(
                "relevant_announcements_fetch_error", error=str(e), symbol=symbol
            )
            return []

    # ------------------------------------------------------------------
    # Sentiment for a specific symbol
    # ------------------------------------------------------------------

    async def _get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Get sentiment analysis for a symbol.

        Aggregates ``sentiment_score`` from stored NewsArticle records that
        mention the symbol. Falls back to scoring recent yfinance headlines
        when no DB articles exist for the symbol.
        """
        try:
            # Try DB-stored news with sentiment
            query = select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(100)
            result = await self.db.execute(query)
            articles = result.scalars().all()

            symbol_upper = symbol.upper()
            matching = [
                a for a in articles
                if symbol_upper in [s.upper() for s in (a.related_symbols or [])]
                and a.sentiment_score is not None
            ]

            if matching:
                scores = [a.sentiment_score for a in matching]
                labels = [a.sentiment_label for a in matching]
                avg = round(sum(scores) / len(scores), 4)
                most_common_label = max(set(labels), key=labels.count) if labels else "NEUTRAL"
                confidence = round(min(abs(avg), 1.0), 4)
                return {
                    "score": avg,
                    "label": most_common_label.upper() if most_common_label else "NEUTRAL",
                    "confidence": confidence,
                    "source": "db_news_articles",
                    "article_count": len(matching),
                }

            # Fallback: score yfinance headlines
            headlines = await _fetch_news_headlines(symbol, limit=10)
            if headlines:
                scores = [h.get("sentiment_score", 0.0) for h in headlines]
                labels = [h.get("sentiment", "neutral").upper() for h in headlines]
                avg = round(sum(scores) / len(scores), 4) if scores else 0.0
                bullish = sum(1 for l in labels if l in ("BULLISH", "POSITIVE"))
                bearish = sum(1 for l in labels if l in ("BEARISH", "NEGATIVE"))
                label = "POSITIVE" if avg > 0.15 else "NEGATIVE" if avg < -0.15 else "NEUTRAL"
                confidence = round(min(abs(avg), 1.0), 4)
                return {
                    "score": avg,
                    "label": label,
                    "confidence": confidence,
                    "source": "yfinance_headlines",
                    "article_count": len(headlines),
                }

            return {"score": 0.0, "label": "NEUTRAL", "confidence": 0.0, "source": "no_data"}
        except Exception as e:
            logger.error("sentiment_fetch_error", error=str(e), symbol=symbol)
            return {"score": 0.0, "label": "NEUTRAL", "confidence": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Standalone comparison context builder
# ---------------------------------------------------------------------------

async def build_comparison_context(
    db: AsyncSession,
    symbols: List[str],
    include_news: bool = True,
    include_sentiment: bool = True,
) -> Dict[str, Any]:
    """
    Build context for stock comparison requests.

    Example: "Compare HBL and MEBL"

    Fetches live price, change %, sentiment, and news for each symbol
    concurrently, then assembles a comparison matrix.
    """
    builder = ContextBuilder(db)

    async def _fetch_one(sym: str) -> Dict[str, Any]:
        """Fetch price + context for one symbol in the comparison."""
        price = await _fetch_price(sym)
        news = await builder._get_relevant_news(symbol=sym, limit=3) if include_news else []
        sentiment = await builder._get_sentiment(symbol=sym) if include_sentiment else None
        return {
            "symbol": sym,
            "price": price,
            "recent_news": news,
            "sentiment": sentiment,
        }

    tasks = [_fetch_one(s) for s in symbols[:10]]  # cap at 10 comparables
    results = await asyncio.gather(*tasks, return_exceptions=True)

    comparison_data = {}
    for sym, res in zip(symbols[:10], results):
        if isinstance(res, Exception):
            logger.warning("comparison_fetch_error", symbol=sym, error=str(res))
            comparison_data[sym] = {"symbol": sym, "error": str(res)}
        else:
            comparison_data[sym] = res

    return {
        "comparison_type": "stock_comparison",
        "symbols": symbols[:10],
        "data": comparison_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
