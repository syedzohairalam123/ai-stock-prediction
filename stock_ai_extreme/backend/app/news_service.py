"""
Phase 8 — Professional News & Financial Intelligence Desk.

Aggregates financial news from real sources, enriches each article with real
computed analytics, and stores it for filtering/search/ticker-linking:

- **RSS/Atom** (`news_sources`): real publisher feeds, **no API key needed** —
  Dawn Business, The Express Tribune Business, Google News scoped queries for
  PSX/SBP/SECP/the Pakistan economy, plus BBC/CNBC/WSJ/Yahoo/Investing.com.
  This is the source that makes the desk non-empty on a fresh install.
- **NewsAPI.org**: global business news (optional key, 100 req/day free).
- **Finnhub**: real-time market + company news (optional key).
- **Alpha Vantage**: market news with its own sentiment field (optional key).
- **yfinance**: company news feed for one ticker (no key).

Design rules enforced in this module:

* **Nothing is fabricated.** A source that fails contributes zero articles and
  records *why*; an article is never created to fill a gap. Timestamps are the
  publisher's own — never the fetch time, unless a feed genuinely omits one
  (in which case the article is still stored, with the ingest time and the
  feed's own status recorded).
* **No blocking calls on the event loop.** Every HTTP request in this module is
  synchronous ``httpx`` executed inside ``asyncio.to_thread``, so a slow
  publisher degrades one coroutine instead of stalling the API.
* **De-duplication is real de-duplication.** URL matching alone misses the same
  wire story republished under different links by five outlets, so ingestion
  also checks a normalized-headline key and a 64-bit SimHash index
  (``news_analytics``).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from . import news_analytics as analytics
from . import news_sources
from .config import settings
from .logging_config import get_logger
from .models import NewsArticle
from .news import score_text  # Reuse the existing finance sentiment lexicon

logger = get_logger("neural_market.news_service")

#: Kept for backwards compatibility with anything importing it; the
#: authoritative universe now lives in `symbols.PSX_SYMBOLS` and is applied by
#: `news_analytics.extract_symbols`.
PSX_TICKERS = frozenset({
    "OGDC", "PPL", "POL", "LUCK", "MLCF", "FFC", "ENGRO", "HUBC", "KAPCO",
    "HBL", "UBL", "MCB", "BAFL", "MEBL", "ABL", "NBP", "BAHL", "AKBL",
    "SYS", "TRG", "AGTL", "AVON", "NETSOL", "HASCOL", "PSO", "APL",
    "SNGP", "SSGC", "KEL", "PGLC", "ICI", "LOTCHEM", "EPCL", "SHEL",
})

CATEGORIES = [
    "PSX", "Stocks", "Economy", "Banking", "Corporate",
    "Forex", "Commodities", "Global Markets", "Business", "Regulation",
]

#: Freshness windows for a news item, in hours. Deliberately much tighter than
#: a market quote: yesterday's price is still a price, but yesterday's headline
#: is history, and the UI says so.
LIVE_WINDOW_HOURS = 6
RECENT_WINDOW_HOURS = 72

#: Tickers that are also ordinary English words. For these, a case-insensitive
#: whole-word match is not evidence of relevance ("no luck at all" is not a
#: Lucky Cement story), so only an exact-capitalised ticker or the company name
#: counts.
_ENGLISH_WORD_LIKE_TICKERS = frozenset({"LUCK", "BOP", "POL", "SHEL", "ICI", "ASL", "MTL", "MARI", "FFC", "NML"})


def analytics_aliases(ticker: str) -> tuple[str, ...]:
    """Company names that map to `ticker` in the analytics alias table."""
    return tuple(
        name for name, symbol in analytics.COMPANY_ALIASES.items() if symbol == ticker
    )


def _slugify(text: str) -> str:
    """Convert title to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:600]


def _extract_tickers(text: str) -> list[str]:
    """PSX tickers present in `text`, validated against the real universe."""
    return analytics.extract_symbols(text)


#: Category rules, evaluated in order — first match wins. Kept explicit (rather
#: than a model) so a mis-categorised headline is a one-line bug to fix.
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("PSX", ("psx", "karachi stock", "pakistan stock exchange", "kse-100", "kse100", "bourse")),
    ("Banking", ("bank", "banking", "hbl", "ubl", "mcb", "nbp", "meezan", "deposits", "advances", "npl")),
    ("Forex", ("forex", "currency", "exchange rate", "dollar", "rupee", "interbank", "pkr")),
    ("Commodities", ("commodity", "commodities", "crude", "gold", "silver", "copper", "brent", "wti")),
    ("Regulation", ("regulation", "secp", "sbp", "regulatory", "compliance", "sro")),
    ("Economy", ("economy", "economic", "gdp", "inflation", "cpi", "fiscal", "imf", "budget", "remittances", "current account")),
    ("Corporate", ("corporate", "company", "firm", "results", "earnings", "dividend", "merger")),
    ("Global Markets", ("wall street", "s&p 500", "nasdaq", "federal reserve", "global markets", "asian stocks", "european stocks")),
]


def _categorize_article(title: str, content: str, publisher: str = "") -> str:
    """Best-matching category for an article, `Business` when nothing fits."""
    text = f"{title} {content} {publisher}".lower()
    for category, keywords in _CATEGORY_RULES:
        if any(word in text for word in keywords):
            return category
    return "Business"


def _normalize_date(date_str: str | None) -> datetime | None:
    """Parse the date formats the news APIs actually emit."""
    if not date_str:
        return None
    try:
        if 'T' in date_str:
            parsed = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        if date_str.isdigit():
            return datetime.fromtimestamp(int(date_str), tz=timezone.utc)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d %b %Y"):
            try:
                return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    except Exception as exc:
        logger.warning("failed to parse feed date %r: %s", date_str, exc)
    return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def data_mode_for(published_at: datetime | None, *, now: datetime | None = None) -> str:
    """Freshness label for an article based on the publisher's own timestamp.

    Returns one of ``LIVE`` (<= 6h), ``RECENT`` (<= 72h), ``STALE`` (older) or
    ``UNKNOWN`` (no usable timestamp). This is the news equivalent of the
    quote-freshness states the rest of the terminal already uses, and it exists
    so the UI never presents last week's story as breaking news.
    """
    now = now or datetime.now(timezone.utc)
    published = _as_utc(published_at)
    if published is None:
        return "UNKNOWN"
    age_hours = (now - published).total_seconds() / 3600.0
    if age_hours <= LIVE_WINDOW_HOURS:
        return "LIVE"
    if age_hours <= RECENT_WINDOW_HOURS:
        return "RECENT"
    return "STALE"


class NewsService:
    """Aggregates news from real sources, stores it, and analyses it."""

    def __init__(self) -> None:
        self.session = httpx.Client(
            timeout=settings.newsapi_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": news_sources.DEFAULT_USER_AGENT},
        )
        self._cache: dict[str, tuple[object, datetime]] = {}
        self._cache_ttl = timedelta(minutes=5)
        #: Last per-feed result, so /api/news/sources can report real health
        #: instead of guessing. Populated by every RSS ingest.
        self.feed_statuses: list[dict] = []
        self.last_ingest_at: datetime | None = None

    def __del__(self):  # pragma: no cover - interpreter shutdown best effort
        try:
            self.session.close()
        except Exception:
            pass

    def close(self) -> None:
        self.session.close()

    # ------------------------------------------------------------------
    # tiny TTL cache (same shape as the provider layer's)
    # ------------------------------------------------------------------

    def _cache_key(self, prefix: str, **kwargs) -> str:
        params = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{prefix}_{params}"

    def _get_cached(self, key: str):
        if key in self._cache:
            result, timestamp = self._cache[key]
            if datetime.now(timezone.utc) - timestamp < self._cache_ttl:
                return result
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value) -> None:
        self._cache[key] = (value, datetime.now(timezone.utc))

    def purge_cache(self) -> int:
        """Drop expired entries — called from the background maintenance loop so
        a long-running server does not accumulate them."""
        now = datetime.now(timezone.utc)
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self._cache_ttl]
        for key in expired:
            self._cache.pop(key, None)
        return len(expired)

    async def _get(self, url: str, params: dict | None = None, headers: dict | None = None):
        """Blocking httpx GET executed off the event loop."""
        return await asyncio.to_thread(self.session.get, url, params=params, headers=headers)

    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------

    async def fetch_rss_feeds(self, region: str | None = None, *, regional_timeout: float = 12.0):
        """Fetch every enabled keyless publisher feed.

        Returns ``(articles, statuses)``. Concurrency is bounded with a
        semaphore: fetching 15 feeds serially is slow, fetching 15 at once is
        rude to the publishers. One failing feed is isolated and reported.
        """
        feeds = news_sources.enabled_feeds(region)
        if not feeds:
            return [], news_sources.disabled_feed_statuses()

        semaphore = asyncio.Semaphore(max(1, int(settings.news_fetch_concurrency)))

        async def one(feed):
            async with semaphore:
                articles, status = await asyncio.to_thread(
                    news_sources.fetch_feed, feed, timeout=regional_timeout
                )
                return articles, status

        results = await asyncio.gather(*(one(f) for f in feeds), return_exceptions=True)

        articles: list[dict] = []
        statuses: list[news_sources.FeedStatus] = list(news_sources.disabled_feed_statuses())
        for feed, result in zip(feeds, results):
            if isinstance(result, BaseException):
                statuses.append(news_sources.FeedStatus(
                    feed.key, feed.name, feed.region, feed.url, "ERROR",
                    error=f"{type(result).__name__}: {result}",
                ))
                logger.warning("rss feed %s failed: %s", feed.key, result)
                continue
            feed_articles, status = result
            statuses.append(status)
            articles.extend(feed_articles)

        # A single bad article must not poison the batch.
        articles = [a for a in articles if a.get("title") and a.get("source_url")]
        self.feed_statuses = [s.as_dict() for s in statuses]
        ok = sum(1 for s in statuses if s.status == "OK")
        logger.info("rss ingest: %d article(s) from %d/%d feeds", len(articles), ok, len(statuses))
        return articles, statuses

    async def fetch_newsapi(self, query: str = "finance", category: str = "business",
                            page_size: int = 20) -> list[dict]:
        """Fetch from NewsAPI.org (100 req/day free). Empty without a key."""
        if not settings.newsapi_key:
            logger.debug("NewsAPI key not configured, skipping")
            return []

        cache_key = self._cache_key("newsapi", q=query, cat=category, ps=page_size)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            response = await self._get(f"{settings.newsapi_url}/everything", params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": min(page_size, 100),
                "apiKey": settings.newsapi_key,
            })
            response.raise_for_status()
            data = response.json()

            articles = []
            for item in data.get("articles", []):
                title = item.get("title")
                if not title or title == "[Removed]":
                    continue
                content = item.get("description") or item.get("content") or ""
                articles.append({
                    "title": title,
                    "slug": _slugify(title),
                    "publisher": (item.get("source") or {}).get("name"),
                    "author": item.get("author"),
                    "published_at": _normalize_date(item.get("publishedAt")),
                    "image_url": item.get("urlToImage"),
                    "excerpt": (item.get("description") or "")[:1000] or None,
                    "content": content[:10000] or None,
                    "category": _categorize_article(title, content),
                    "tags": [],
                    "related_symbols": _extract_tickers(f"{title} {content}"),
                    "related_indices": [],
                    "source_url": item.get("url", ""),
                    "source_type": "ARTICLE",
                    "priority": "NORMAL",
                    "data_source": "newsapi",
                })

            articles = [a for a in articles if a["source_url"]]
            self._set_cached(cache_key, articles)
            logger.info("fetched %d article(s) from NewsAPI", len(articles))
            return articles
        except Exception as exc:
            logger.error("NewsAPI fetch failed: %s", exc)
            return []

    async def fetch_finnhub_news(self, symbol: str = "", category: str = "general") -> list[dict]:
        """Fetch from Finnhub (market news, or company news for one symbol)."""
        if not settings.finnhub_api_key:
            logger.debug("Finnhub key not configured, skipping")
            return []

        cache_key = self._cache_key("finnhub", sym=symbol, cat=category)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            if symbol:
                url = "https://finnhub.io/api/v1/company-news"
                params = {
                    "symbol": symbol,
                    "from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "to": datetime.now().strftime("%Y-%m-%d"),
                    "token": settings.finnhub_api_key,
                }
            else:
                url = "https://finnhub.io/api/v1/news"
                params = {"category": category, "token": settings.finnhub_api_key}

            response = await self._get(url, params=params)
            response.raise_for_status()
            data = response.json()

            articles = []
            for item in data if isinstance(data, list) else []:
                title = item.get("headline", "")
                if not title:
                    continue
                summary = item.get("summary", "") or ""
                published = (
                    datetime.fromtimestamp(item["datetime"], tz=timezone.utc)
                    if item.get("datetime") else None
                )
                articles.append({
                    "title": title,
                    "slug": _slugify(title),
                    "publisher": item.get("source") or "Finnhub",
                    "author": None,
                    "published_at": published,
                    "image_url": item.get("image"),
                    "excerpt": summary[:1000] or None,
                    "content": summary[:10000] or None,
                    "category": _categorize_article(title, summary),
                    "tags": [],
                    "related_symbols": [symbol] if symbol else _extract_tickers(f"{title} {summary}"),
                    "related_indices": [],
                    "source_url": item.get("url", ""),
                    "source_type": "ARTICLE",
                    "priority": "NORMAL",
                    "data_source": "finnhub",
                })

            articles = [a for a in articles if a["source_url"]]
            self._set_cached(cache_key, articles)
            logger.info("fetched %d article(s) from Finnhub", len(articles))
            return articles
        except Exception as exc:
            logger.error("Finnhub news fetch failed: %s", exc)
            return []

    async def fetch_alpha_vantage_news(self, topics: str = "technology", limit: int = 50) -> list[dict]:
        """Fetch from Alpha Vantage NEWS_SENTIMENT (25 req/day free)."""
        if not settings.alpha_vantage_key:
            logger.debug("Alpha Vantage key not configured, skipping")
            return []

        cache_key = self._cache_key("alphavantage", topics=topics, limit=limit)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            response = await self._get(f"{settings.alpha_vantage_url}/query", params={
                "function": "NEWS_SENTIMENT",
                "topics": topics,
                "limit": min(limit, 1000),
                "apikey": settings.alpha_vantage_key,
            })
            response.raise_for_status()
            data = response.json()

            articles = []
            for item in data.get("feed", []):
                title = item.get("title", "")
                if not title:
                    continue
                summary = item.get("summary", "") or ""
                tickers = [
                    t.get("ticker", "").upper() for t in item.get("ticker_sentiment", [])
                ]
                authors = item.get("authors") or []
                articles.append({
                    "title": title,
                    "slug": _slugify(title),
                    "publisher": item.get("source") or "Alpha Vantage",
                    "author": authors[0] if authors else None,
                    "published_at": _normalize_date(item.get("time_published")),
                    "image_url": item.get("banner_image"),
                    "excerpt": summary[:1000] or None,
                    "content": summary[:10000] or None,
                    "category": _categorize_article(title, summary),
                    "tags": (item.get("topics") or [])[:10],
                    "related_symbols": _extract_tickers(f"{title} {' '.join(tickers)} {summary}"),
                    "related_indices": [],
                    "source_url": item.get("url", ""),
                    "source_type": "ARTICLE",
                    "priority": "NORMAL",
                    "data_source": "alpha_vantage",
                })

            articles = [a for a in articles if a["source_url"]]
            self._set_cached(cache_key, articles)
            logger.info("fetched %d article(s) from Alpha Vantage", len(articles))
            return articles
        except Exception as exc:
            logger.error("Alpha Vantage news fetch failed: %s", exc)
            return []

    async def fetch_yfinance_news(self, ticker: str) -> list[dict]:
        """Company news for one ticker via yfinance (no key)."""
        cache_key = self._cache_key("yfinance", ticker=ticker)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        def _fetch() -> list[dict]:
            import yfinance as yf

            raw = yf.Ticker(ticker).news or []
            items: list[dict] = []
            for item in raw:
                # yfinance switched to a nested `content` envelope; support both.
                content = item.get("content") if isinstance(item.get("content"), dict) else item
                title = content.get("title") or item.get("title")
                if not title:
                    continue
                link = (
                    content.get("canonicalUrl", {}).get("url")
                    if isinstance(content.get("canonicalUrl"), dict)
                    else content.get("link") or item.get("link")
                ) or item.get("link")
                if not link:
                    continue
                publisher = None
                provider = content.get("provider")
                if isinstance(provider, dict):
                    publisher = provider.get("displayName")
                publisher = publisher or content.get("publisher") or item.get("publisher") or "Yahoo Finance"

                published = None
                if item.get("providerPublishTime"):
                    published = datetime.fromtimestamp(int(item["providerPublishTime"]), tz=timezone.utc)
                elif content.get("pubDate"):
                    published = _normalize_date(content["pubDate"])

                image = None
                thumbnail = content.get("thumbnail") or item.get("thumbnail")
                if isinstance(thumbnail, dict):
                    resolutions = thumbnail.get("resolutions") or []
                    if resolutions:
                        image = resolutions[-1].get("url")

                summary = content.get("summary") or content.get("description")
                items.append({
                    "title": title,
                    "slug": _slugify(title),
                    "publisher": publisher,
                    "author": None,
                    "published_at": published,
                    "image_url": image,
                    "excerpt": (summary or "")[:1000] or None,
                    "content": (summary or "")[:10000] or None,
                    "category": _categorize_article(title, summary or "", publisher),
                    "tags": [content.get("contentType", "")] if content.get("contentType") else [],
                    "related_symbols": [ticker.upper()],
                    "related_indices": [],
                    "source_url": link,
                    "source_type": "ARTICLE",
                    "priority": "NORMAL",
                    "data_source": "yfinance",
                })
            return items

        try:
            articles = await asyncio.to_thread(_fetch)
            self._set_cached(cache_key, articles)
            logger.info("fetched %d article(s) from yfinance for %s", len(articles), ticker)
            return articles
        except Exception as exc:
            logger.error("yfinance news fetch failed for %s: %s", ticker, exc)
            return []

    async def fetch_symbol_news(self, symbol: str) -> list[dict]:
        """Live symbol-scoped news from the keyless Google News feed.

        This is what makes `/api/news/by-symbol/{symbol}` useful for the long
        tail: a general PSX feed will never have a paragraph about every one of
        the 60-odd tickers the terminal knows, so when the stored corpus has
        nothing for a ticker the route asks the publisher feed directly for
        that name instead of returning an empty list.
        """
        ticker = (symbol or "").strip().upper()
        if not ticker:
            return []

        cache_key = self._cache_key("symbol_rss", symbol=ticker)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        feed = news_sources.NewsFeed(
            key=f"symbol_{ticker.lower()}",
            name="Google News",
            url=news_sources.symbol_search_url(ticker),
            region="PK",
            category="Stocks",
            quality=0.72,
            description_is_links=True,
        )
        articles, status = await asyncio.to_thread(news_sources.fetch_feed, feed, timeout=12.0)
        if status.status != "OK":
            logger.info("symbol news fetch for %s: %s (%s)", ticker, status.status, status.error)

        # A quoted search is not a guarantee: Google News matches "LUCK" against
        # the ordinary English word, so an unfiltered result set contains jokes
        # about luck. Keep only items that genuinely name the ticker (as a whole
        # capitalised word) or one of the company's known names.
        relevant = [a for a in articles if self._mentions_symbol(a, ticker)]
        if relevant:
            articles = relevant

        # Attribute every item to the ticker it was queried for, and make sure
        # the symbol itself survives validation (the query may return a story
        # that spells the company name rather than the ticker).
        for article in articles:
            symbols = article.get("related_symbols") or []
            if ticker not in symbols:
                article["related_symbols"] = [ticker, *symbols]

        self._set_cached(cache_key, articles)
        return articles

    @staticmethod
    def _mentions_symbol(article: dict, ticker: str) -> bool:
        """True when the article text really names the ticker or its company."""
        haystack = " ".join(filter(None, (
            article.get("title"), article.get("excerpt"), article.get("content"),
        )))
        if not haystack:
            return False
        if re.search(rf"\b{re.escape(ticker)}\b", haystack):
            return True
        if re.search(rf"\b{re.escape(ticker)}\b", haystack, re.IGNORECASE):
            # Bare lowercase/titlecase mention of an unmistakable ticker
            # (e.g. "Meezan Bank" for MEBL) is fine only when no confusion with
            # an ordinary English word is possible.
            if ticker.upper() not in _ENGLISH_WORD_LIKE_TICKERS:
                return True
        lowered = haystack.lower()
        for name in news_sources.SYMBOL_SEARCH_NAMES.get(ticker, ()) + analytics_aliases(ticker):
            if name.lower() in lowered:
                return True
        return False

    # ------------------------------------------------------------------
    # enrichment + storage
    # ------------------------------------------------------------------

    def corpus_for(self, db: Session, extra_texts: list[str] | None = None) -> analytics.TfIdfCorpus:
        """TF-IDF corpus built from what is actually in the database, so keyword
        extraction reflects the live corpus rather than a frozen word list."""
        try:
            rows = db.query(NewsArticle.title, NewsArticle.excerpt).limit(2000).all()
        except Exception as exc:  # a query failure must not block ingestion
            logger.warning("could not build tf-idf corpus: %s", exc)
            rows = []
        documents = [f"{t or ''} {e or ''}" for t, e in rows]
        documents.extend(extra_texts or [])
        return analytics.TfIdfCorpus(documents)

    def enrich_articles(self, articles: list[dict], corpus: analytics.TfIdfCorpus | None = None) -> list[dict]:
        """Attach sentiment + analytics + freshness to every article."""
        now = datetime.now(timezone.utc)
        enriched: list[dict] = []
        for article in articles:
            sentiment = score_text(article.get("title") or "")
            article = {**article, "sentiment_score": sentiment["score"], "sentiment_label": sentiment["label"]}
            article = analytics.enrich(article, corpus=corpus, now=now)
            article["data_mode"] = data_mode_for(_as_utc(article.get("published_at")), now=now)
            article["published_at"] = _as_utc(article.get("published_at")) or now
            article["slug"] = article.get("slug") or _slugify(article["title"])
            data_source = article.get("data_source") or ""
            article["feed_key"] = data_source.split(":", 1)[1] if data_source.startswith("rss:") else None
            enriched.append(article)
        return enriched

    def _existing_indexes(self, db: Session) -> tuple[set[str], set[str], analytics.MinHashIndex]:
        """URL set, normalized-title set and a populated MinHash index for the
        rows already stored. Bounded to the newest `news_dedupe_scan_limit`
        articles — an item old enough to fall outside that window is already
        history and is not a duplicate risk."""
        limit = max(int(settings.news_dedupe_scan_limit), 100)
        urls: set[str] = set()
        titles: set[str] = set()
        index = analytics.MinHashIndex(
            rows=int(settings.news_minhash_rows),
            band_rows=int(settings.news_minhash_band_rows),
            threshold=float(settings.news_dedupe_jaccard_threshold),
        )
        try:
            rows = (
                db.query(NewsArticle.id, NewsArticle.source_url, NewsArticle.title,
                         NewsArticle.shingle_signature)
                .order_by(NewsArticle.id.desc())
                .limit(limit)
                .all()
            )
        except Exception as exc:
            logger.warning("could not load dedupe index: %s", exc)
            return urls, titles, index

        for row_id, url, title, signature in rows:
            if url:
                urls.add(url)
            if title:
                titles.add(analytics.normalize_title(title))
            decoded = analytics.decode_signature(signature)
            if decoded:
                index.add(decoded, row_id)
        return urls, titles, index

    def store_articles(self, db: Session, articles: list[dict], *, dedupe: bool = True) -> dict:
        """Persist enriched articles, skipping anything already covered.

        Returns a report (stored / skipped / reasons) rather than a bare count,
        because "why did my feed only gain 12 of 400 items" is a legitimate
        question with a precise answer: 388 were the same stories again.
        """
        report = {"received": len(articles), "stored": 0, "duplicate_url": 0,
                  "duplicate_title": 0, "near_duplicate": 0, "failed": 0}

        urls, titles, index = self._existing_indexes(db) if dedupe else (set(), set(), analytics.MinHashIndex())

        for article in articles:
            try:
                url = article.get("source_url")
                if not url:
                    report["failed"] += 1
                    continue
                if dedupe and url in urls:
                    report["duplicate_url"] += 1
                    continue
                normalized_title = analytics.normalize_title(article.get("title") or "")
                if dedupe and normalized_title and normalized_title in titles:
                    report["duplicate_title"] += 1
                    continue
                signature = analytics.decode_signature(article.get("shingle_signature"))
                if dedupe and signature and index.find_duplicate(signature) is not None:
                    report["near_duplicate"] += 1
                    continue

                payload = {k: v for k, v in article.items() if hasattr(NewsArticle, k) and k != "id"}
                if payload.get("simhash"):
                    payload["simhash"] = analytics.to_signed64(int(payload["simhash"]))
                # `impact_components` is a diagnostics aid for the API, not a
                # stored column — drop it rather than silently ignore it.
                payload.pop("impact_components", None)
                db.add(NewsArticle(**payload))
                urls.add(url)
                if normalized_title:
                    titles.add(normalized_title)
                if signature:
                    index.add(signature, url)
                report["stored"] += 1
            except Exception as exc:
                logger.warning("failed to store article %r: %s", article.get("title"), exc)
                report["failed"] += 1
                db.rollback()
                # Rebuild our in-memory indexes from the DB after a rollback —
                # the aborted transaction may have undone earlier inserts.
                urls, titles, index = self._existing_indexes(db) if dedupe else (set(), set(), analytics.MinHashIndex())

        if report["stored"]:
            db.commit()
        logger.info("news store: %s", report)
        return report

    async def aggregate_and_store(
        self,
        db: Session,
        sources: list[str] | None = None,
        query: str = "Pakistan stock market",
        symbol: str = "",
        region: str | None = None,
    ) -> int:
        """Fetch from the requested sources, enrich, de-duplicate and store.

        Returns the number of newly stored articles (the contract the existing
        `/api/news/refresh` route relies on).
        """
        sources = sources or ["rss", "symbols", "newsapi", "finnhub", "alpha_vantage", "yfinance"]
        collected: list[dict] = []

        if "rss" in sources:
            rss_articles, _ = await self.fetch_rss_feeds(region)
            collected.extend(rss_articles)

        if "newsapi" in sources:
            collected.extend(await self.fetch_newsapi(query=query))

        if "finnhub" in sources:
            collected.extend(await self.fetch_finnhub_news(symbol=symbol))

        if "alpha_vantage" in sources:
            collected.extend(await self.fetch_alpha_vantage_news(topics="finance"))

        if "symbols" in sources:
            collected.extend(await self.fetch_watchlist_news())

        if "yfinance" in sources and symbol:
            collected.extend(await self.fetch_yfinance_news(symbol))

        if not collected:
            self.last_ingest_at = datetime.now(timezone.utc)
            return 0

        corpus = self.corpus_for(db, extra_texts=[f"{a.get('title','')} {a.get('excerpt') or ''}" for a in collected])
        enriched = self.enrich_articles(collected, corpus)
        report = self.store_articles(db, enriched)
        self.last_ingest_at = datetime.now(timezone.utc)
        return int(report["stored"])

    async def fetch_watchlist_news(self, symbols: list[str] | None = None) -> list[dict]:
        """Company-scoped news for the configured watchlist of tickers.

        Bounded by ``NEWS_SYMBOL_MAX`` and fetched concurrently behind the same
        politeness semaphore as the main feeds. A ticker with no coverage simply
        contributes nothing — there is no placeholder article for a quiet
        company.
        """
        if symbols is None:
            raw = (settings.news_symbol_watchlist or "").split(",")
            symbols = [s.strip().upper() for s in raw if s.strip()]
        symbols = symbols[: max(int(settings.news_symbol_max), 0)]
        if not symbols:
            return []

        semaphore = asyncio.Semaphore(max(1, int(settings.news_fetch_concurrency)))

        async def one(ticker: str):
            async with semaphore:
                try:
                    return await self.fetch_symbol_news(ticker)
                except Exception as exc:  # already handled inside, belt and braces
                    logger.warning("watchlist news failed for %s: %s", ticker, exc)
                    return []

        results = await asyncio.gather(*(one(t) for t in symbols), return_exceptions=True)
        articles: list[dict] = []
        for result in results:
            if isinstance(result, list):
                articles.extend(result)
        logger.info("watchlist news: %d article(s) across %d ticker(s)", len(articles), len(symbols))
        return articles

    async def fetch_image(self, url: str) -> tuple[str, bytes]:
        """Re-serve one allow-listed publisher image.

        Used only as a *retry* by the frontend, after a direct browser load has
        failed — several publisher CDNs block cross-origin `<img>` requests but
        serve the identical bytes to a server. Raises ``ValueError`` for a host
        outside the allowlist (no request is made) and ``RuntimeError`` for an
        upstream failure, so the caller can turn each into an honest HTTP status
        instead of a half-rendered image.
        """
        if not news_sources.is_allowed_image_host(url):
            raise ValueError("image host is not on the allowlist")

        cache_key = f"image:{url}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        response = await asyncio.to_thread(
            self.session.get,
            url,
            headers={"User-Agent": news_sources.DEFAULT_USER_AGENT, "Accept": "image/*, */*"},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"upstream returned HTTP {response.status_code}")
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            raise RuntimeError(f"upstream content-type is not an image ({content_type or 'none'})")
        body = response.content
        if len(body) > news_sources.MAX_IMAGE_BYTES:
            raise RuntimeError("image exceeds the size limit")
        if not body:
            raise RuntimeError("upstream returned an empty body")

        result = (content_type, body)
        self._set_cached(cache_key, result)
        return result

    def source_status(self) -> list[dict]:
        """Per-feed health from the most recent ingest (real HTTP results)."""
        if self.feed_statuses:
            return self.feed_statuses
        return [s.as_dict() for s in news_sources.disabled_feed_statuses()] + [
            {"key": f.key, "name": f.name, "region": f.region, "url": f.url,
             "status": "NOT_FETCHED", "http_status": None, "items": 0,
             "error": None, "fetched_at": None}
            for f in news_sources.enabled_feeds()
        ]


# Singleton instance
_news_service: Optional[NewsService] = None


def get_news_service() -> NewsService:
    """Get or create news service singleton."""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service


def reset_news_service() -> None:
    """Drop the singleton (used by tests that want a clean cache)."""
    global _news_service
    if _news_service is not None:
        _news_service.close()
        _news_service = None


__all__ = [
    "CATEGORIES", "PSX_TICKERS", "NewsService", "data_mode_for",
    "get_news_service", "reset_news_service",
    "_categorize_article", "_extract_tickers", "_normalize_date", "_slugify",
]
