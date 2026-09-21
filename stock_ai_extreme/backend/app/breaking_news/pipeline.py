"""
News ingestion pipeline (spec §2).

    external sources -> fetch -> validation -> normalization -> deduplication
        -> entity extraction -> market association -> impact analysis -> feed

This module owns the first half of that chain:

* :class:`NewsProvider` — one named adapter over a real source. Concrete
  providers wrap the *existing* Phase 8 stack (:mod:`news_sources` /
  :mod:`news_service`) rather than re-implementing HTTP, so there is exactly one
  code path that talks to a publisher and exactly one place where provenance is
  recorded.
* :class:`NewsAggregator` — runs every provider with per-provider isolation: a
  single failing feed marks that provider ``ok=False`` with its error and
  contributes no articles, while the rest of the pipeline continues (spec §19).
* :class:`NewsNormalizer` — maps a raw provider item or a stored ORM row onto the
  one canonical article shape (spec §3) and records which required fields were
  genuinely absent.
* :class:`NewsRanker` — turns normalized articles into ranked breaking events
  using :class:`~.breaking_detector.BreakingNewsDetector`.

Hard rules enforced in code, not documentation:

* An item without a title or without a URL is **rejected** — a link is the
  identity of an article, and a headline is what the reader reads.
* A missing publication timestamp is preserved as ``None``. It is never replaced
  with the fetch time, and it can never be scored as "just now".
* Nothing is invented to fill a gap; the gap is reported.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import NewsArticle
from ..news_analytics import extract_entities, extract_indices, extract_symbols, extract_topics
from ..news_service import data_mode_for, get_news_service
from ..symbols import PSX_SYMBOLS
from .breaking_detector import (
    BreakingNewsDetector,
    ScoreBreakdown,
    compute_mention_velocity,
    compute_topic_acceleration,
)
from .config import breaking_news_settings
from .timeutil import age_minutes, parse_datetime, to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.pipeline")

#: Fields a usable article is expected to carry. Anything missing is reported in
#: ``NormalizedArticle.missing`` so the UI can be explicit instead of blank.
REQUIRED_FIELDS = ("title", "publisher", "published_at", "url", "image", "excerpt")


@dataclass
class NormalizedArticle:
    """The canonical Phase 17 article shape."""

    title: str
    publisher: str
    url: str
    source: str
    id: Optional[int] = None
    published_at: Optional[datetime] = None
    image: Optional[str] = None
    excerpt: Optional[str] = None
    category: Optional[str] = None
    entities: list[dict] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    indices: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    #: Curated global market instruments named in the text (equities, indices,
    #: commodities, FX, crypto) — see :mod:`entities`. Separate from ``symbols``,
    #: which stays the PSX-validated list the UI links on.
    market_entities: list[dict] = field(default_factory=list)
    #: ``{entity: type}`` covering symbols, indices and market entities.
    entity_types: dict[str, str] = field(default_factory=dict)
    data_mode: str = "UNKNOWN"
    event_type: Optional[str] = None
    impact_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    missing: list[str] = field(default_factory=list)
    #: The enriched raw payload, retained so the ingest step can persist the
    #: *original* dict through the existing Phase 8 store (no field invention).
    raw: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "publisher": self.publisher,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "url": self.url,
            "image": self.image,
            "excerpt": self.excerpt,
            "category": self.category,
            "entities": self.entities,
            "symbols": self.symbols,
            "indices": self.indices,
            "topics": self.topics,
            "market_entities": self.market_entities,
            "entity_types": self.entity_types,
            "source": self.source,
            "data_mode": self.data_mode,
            "event_type": self.event_type,
            "impact_score": self.impact_score,
            "sentiment_score": self.sentiment_score,
            "missing": self.missing,
            "age_minutes": age_minutes(self.published_at),
        }


@dataclass
class RankedArticle:
    """A normalized article plus its breaking assessment."""

    article: NormalizedArticle
    breakdown: ScoreBreakdown
    cluster_id: Optional[str] = None
    cluster_size: int = 1

    @property
    def score(self) -> float:
        return self.breakdown.score

    @property
    def level(self) -> str:
        return self.breakdown.level.value

    def as_dict(self) -> dict:
        return {
            **self.article.as_dict(),
            "breaking_score": self.breakdown.score,
            "breaking_level": self.breakdown.level.value,
            "score_components": self.breakdown.components,
            "score_weights": self.breakdown.weights,
            "cluster_id": self.cluster_id,
            "cluster_size": self.cluster_size,
        }


@dataclass
class ProviderReport:
    name: str
    ok: bool
    fetched: int = 0
    normalized: int = 0
    rejected: int = 0
    #: Items dropped because another provider (or an earlier item in this batch)
    #: already returned the same URL in this run.
    duplicates: int = 0
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    missing_fields: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "fetched": self.fetched,
            "normalized": self.normalized,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "duration_ms": round(self.duration_ms, 2) if self.duration_ms is not None else None,
            "error": self.error,
            "missing_fields": self.missing_fields,
        }


@dataclass
class AggregationResult:
    articles: list[NormalizedArticle] = field(default_factory=list)
    reports: list[ProviderReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    feed_statuses: list[dict] = field(default_factory=list)

    @property
    def raw_articles(self) -> list[dict]:
        """Enriched payloads ready for the Phase 8 store (live providers only)."""
        return [a.raw for a in self.articles if a.raw]


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------

def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class NewsNormalizer:
    """Maps any source's item onto :class:`NormalizedArticle`."""

    def normalize(self, item: Any, *, publisher_fallback: str = "Unknown publisher") -> Optional[NormalizedArticle]:
        """Return the normalized article, or ``None`` when it is unusable.

        Unusable means: no title, or no URL. Everything else — a missing
        publisher, timestamp, image or lede — is preserved as a recorded gap.
        """
        title = (_get(item, "title") or "").strip()
        url = (_get(item, "source_url") or _get(item, "url") or "").strip()
        if not title or not url:
            return None

        publisher = (_get(item, "publisher") or "").strip() or publisher_fallback
        published = parse_datetime(_get(item, "published_at"))
        image = _get(item, "image_url") or _get(item, "image")
        excerpt = _get(item, "excerpt")
        category = _get(item, "category")
        source = (_get(item, "data_source") or _get(item, "source") or "unknown").strip()

        symbols = [s for s in (_get(item, "related_symbols") or []) if s in PSX_SYMBOLS]
        indices = list(_get(item, "related_indices") or [])
        topics = list(_get(item, "topics") or [])

        # A payload that reached us without the Phase 8 enrichment columns (a raw
        # provider item, or a row stored before the analytics layer existed) is
        # re-derived from its own text with the same deterministic rules. This is
        # idempotent: enrichment already extracted from exactly this text.
        analysis_text = f"{title}. {excerpt or ''}"
        if not symbols:
            symbols = extract_symbols(analysis_text)
        if not indices:
            indices = extract_indices(analysis_text)

        # Entities come from the stored analytics column when present, and are
        # otherwise re-derived from the text with the same deterministic rules.
        raw_entities = _get(item, "entities")
        if raw_entities:
            entities = [
                {"type": e.get("type"), "value": e.get("value"), "label": e.get("label")}
                for e in raw_entities
                if isinstance(e, dict) and e.get("value")
            ]
        else:
            entities = [e.as_dict() for e in extract_entities(f"{title}. {excerpt or ''}")]
            if not topics:
                topics = extract_topics(f"{title}. {excerpt or ''}")

        missing = [name for name in REQUIRED_FIELDS if not _get(item, _FIELD_SOURCE[name])]

        # Global market entities: only computed for the normalized shape (stored
        # ORM rows do not carry them), so a rebuild is self-sufficient.
        from .entities import entity_types_for, extract_market_entities

        market_entities = extract_market_entities(f"{title}. {excerpt or ''}")
        entity_types = entity_types_for(market_entities)
        for symbol in symbols:
            entity_types.setdefault(symbol, "STOCK")
        for index in indices:
            entity_types.setdefault(index, "INDEX")

        return NormalizedArticle(
            id=_get(item, "id"),
            title=title,
            publisher=publisher,
            published_at=published,
            url=url,
            image=image or None,
            excerpt=excerpt or None,
            category=category,
            entities=entities,
            symbols=symbols,
            indices=indices,
            topics=topics,
            market_entities=[e.as_dict() for e in market_entities],
            entity_types=entity_types,
            source=source,
            data_mode=data_mode_for(published) if published else "UNKNOWN",
            event_type=_get(item, "event_type"),
            impact_score=_get(item, "impact_score"),
            sentiment_score=_get(item, "sentiment_score"),
            missing=missing,
            raw=item if isinstance(item, dict) else None,
        )


#: Maps a normalized field to the raw column(s) it comes from, so "missing" is
#: measured against the real payload rather than the normalized value.
_FIELD_SOURCE = {
    "title": "title",
    "publisher": "publisher",
    "published_at": "published_at",
    "url": "source_url",
    "image": "image_url",
    "excerpt": "excerpt",
}


normalizer = NewsNormalizer()


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

class NewsProvider:
    """One real news source, fetched in isolation."""

    name: str = "provider"

    async def fetch(self) -> list[Any]:
        raise NotImplementedError

    def feed_statuses(self) -> list[dict]:
        return []


class StoredCorpusProvider(NewsProvider):
    """Reads articles already ingested into the Phase 8 corpus.

    This is the provider that guarantees the breaking feed can be rebuilt from
    real, already-attributed rows without touching the network.
    """

    name = "stored-corpus"

    def __init__(self, db: Session, *, hours: int = 24, limit: Optional[int] = None):
        self.db = db
        self.hours = hours
        self.limit = limit or breaking_news_settings.ingest_scan_limit

    async def fetch(self) -> list[Any]:
        cutoff = utcnow() - timedelta(hours=self.hours)
        rows = (
            self.db.query(NewsArticle)
            .filter(NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc(), NewsArticle.id.desc())
            .limit(self.limit)
            .all()
        )
        return rows


class RSSFeedProvider(NewsProvider):
    """Keyless publisher feeds (the Phase 8 RSS layer), enriched for storage."""

    name = "rss-feeds"

    def __init__(self, db: Session, *, region: Optional[str] = None):
        self.db = db
        self.region = region
        self._statuses: list[dict] = []

    async def fetch(self) -> list[Any]:
        service = get_news_service()
        raw, statuses = await service.fetch_rss_feeds(self.region)
        self._statuses = [s.as_dict() if hasattr(s, "as_dict") else dict(s) for s in statuses]
        if not raw:
            return []
        corpus = service.corpus_for(
            self.db,
            extra_texts=[f"{a.get('title', '')} {a.get('excerpt') or ''}" for a in raw],
        )
        return service.enrich_articles(raw, corpus)

    def feed_statuses(self) -> list[dict]:
        return list(self._statuses)


class SymbolNewsProvider(NewsProvider):
    """Company-scoped headlines from the configured ticker watchlist."""

    name = "symbol-news"

    def __init__(self, db: Session, *, symbols: Optional[list[str]] = None):
        self.db = db
        self.symbols = symbols

    async def fetch(self) -> list[Any]:
        service = get_news_service()
        raw = await service.fetch_watchlist_news(self.symbols)
        if not raw:
            return []
        corpus = service.corpus_for(
            self.db,
            extra_texts=[f"{a.get('title', '')} {a.get('excerpt') or ''}" for a in raw],
        )
        return service.enrich_articles(raw, corpus)


class KeyedAPIProvider(NewsProvider):
    """Optional commercial APIs (NewsAPI / Finnhub / Alpha Vantage).

    With no key configured the provider reports ``ok=True, fetched=0`` — "not
    configured" is a normal state, not a failure worth alarming about.
    """

    def __init__(self, db: Session, *, kind: str, query: str = "finance"):
        self.db = db
        self.kind = kind
        self.query = query
        self.name = f"api-{kind}"

    async def fetch(self) -> list[Any]:
        service = get_news_service()
        if self.kind == "newsapi":
            raw = await service.fetch_newsapi(query=self.query)
        elif self.kind == "finnhub":
            raw = await service.fetch_finnhub_news()
        elif self.kind == "alpha_vantage":
            raw = await service.fetch_alpha_vantage_news(topics="finance")
        else:
            return []
        if not raw:
            return []
        corpus = service.corpus_for(
            self.db,
            extra_texts=[f"{a.get('title', '')} {a.get('excerpt') or ''}" for a in raw],
        )
        return service.enrich_articles(raw, corpus)


class NewsAggregator:
    """Runs providers concurrently, isolating every failure."""

    def __init__(self, providers: Iterable[NewsProvider]):
        self.providers = list(providers)

    async def collect(self, *, normalizer: Optional[NewsNormalizer] = None) -> AggregationResult:
        normalizer = normalizer or NewsNormalizer()
        result = AggregationResult()

        async def run(provider: NewsProvider) -> tuple[NewsProvider, Any, float, Optional[str]]:
            started = time.perf_counter()
            try:
                items = await provider.fetch()
                return provider, items, (time.perf_counter() - started) * 1000.0, None
            except Exception as exc:  # one provider must never break the batch
                logger.warning("news provider %s failed: %s", provider.name, exc)
                return provider, [], (time.perf_counter() - started) * 1000.0, f"{type(exc).__name__}: {exc}"

        outcomes = await asyncio.gather(*(run(p) for p in self.providers))

        #: URLs already accepted in this run. Two providers routinely return the
        #: same article (a publisher feed and a symbol-scoped search hit the same
        #: story), and storing both would hit the corpus' unique URL constraint.
        seen_urls: set[str] = set()

        for provider, items, duration_ms, error in outcomes:
            report = ProviderReport(name=provider.name, ok=error is None, duration_ms=duration_ms)
            if error:
                report.error = error
                result.errors.append(f"{provider.name}: {error}")
                result.reports.append(report)
                result.feed_statuses.extend(provider.feed_statuses())
                continue

            report.fetched = len(items)
            for item in items:
                article = normalizer.normalize(item)
                if article is None:
                    report.rejected += 1
                    continue
                if article.url in seen_urls:
                    report.duplicates += 1
                    continue
                seen_urls.add(article.url)
                report.normalized += 1
                for name in article.missing:
                    report.missing_fields[name] = report.missing_fields.get(name, 0) + 1
                result.articles.append(article)

            result.reports.append(report)
            result.feed_statuses.extend(provider.feed_statuses())
            logger.info(
                "provider %s: %d fetched, %d normalized, %d rejected",
                provider.name, report.fetched, report.normalized, report.rejected,
            )

        return result


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

class NewsRanker:
    """Scores normalized articles and orders them by breaking significance."""

    def __init__(self, detector: Optional[BreakingNewsDetector] = None, *, settings: Any = None):
        self.settings = settings or breaking_news_settings
        self.detector = detector or BreakingNewsDetector(settings=self.settings)

    def rank(
        self,
        articles: list[NormalizedArticle],
        *,
        cluster_of: Optional[dict[int, tuple[str, int]]] = None,
        reliability_lookup: Optional[Callable[[str], Optional[float]]] = None,
        velocity_window_minutes: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> list[RankedArticle]:
        """Return every article with its score, highest score first.

        The velocity/acceleration factors are computed once per distinct entity
        and memoised, so a story mentioning AAPL does not trigger a corpus scan
        for every article that mentions it.
        """
        cluster_of = cluster_of or {}
        reference = to_naive_utc(now) or utcnow()
        velocity_cache: dict[str, float] = {}
        acceleration_cache: dict[str, float] = {}

        ranked: list[RankedArticle] = []
        for article in articles:
            primary = self._primary_entity(article)
            velocity = 0.0
            acceleration = 0.0
            if primary:
                if primary not in velocity_cache:
                    velocity_cache[primary] = compute_mention_velocity(
                        articles, primary, now=reference, window_minutes=velocity_window_minutes
                    )
                    acceleration_cache[primary] = compute_topic_acceleration(
                        articles, primary, now=reference, window_minutes=velocity_window_minutes
                    )
                velocity = velocity_cache[primary]
                acceleration = acceleration_cache[primary]

            cluster_id, cluster_size = cluster_of.get(article.id or -1, (None, 1))

            breakdown = self.detector.breakdown(
                article,
                mention_velocity=velocity,
                topic_acceleration=acceleration,
                cluster_size=cluster_size,
                reliability_lookup=reliability_lookup,
                now=reference,
            )
            ranked.append(
                RankedArticle(
                    article=article,
                    breakdown=breakdown,
                    cluster_id=cluster_id,
                    cluster_size=cluster_size,
                )
            )

        ranked.sort(
            key=lambda r: (
                -r.score,
                -(r.article.published_at.timestamp() if r.article.published_at else 0.0),
                r.article.title,
            )
        )
        return ranked

    @staticmethod
    def _primary_entity(article: NormalizedArticle) -> Optional[str]:
        """The single entity whose velocity best represents this story."""
        if article.symbols:
            return article.symbols[0]
        if article.indices:
            return article.indices[0]
        if article.topics:
            return article.topics[0]
        return None


__all__ = [
    "NormalizedArticle",
    "RankedArticle",
    "ProviderReport",
    "AggregationResult",
    "NewsNormalizer",
    "NewsProvider",
    "StoredCorpusProvider",
    "RSSFeedProvider",
    "SymbolNewsProvider",
    "KeyedAPIProvider",
    "NewsAggregator",
    "NewsRanker",
    "REQUIRED_FIELDS",
]
