"""
Topic engine (spec §12, §13).

``TopicExtractor``  pulls candidate topics out of real article text with three
                    complementary methods: TF-IDF keywords over the live corpus,
                    the curated finance topic lexicon, and validated entities
                    (PSX symbols / index labels) found in the text.
``TopicAggregator`` counts what actually happened — mentions, distinct articles,
                    distinct publishers, entity and index associations, hourly
                    buckets — per topic.
``TopicTrendService`` ranks those counts with a transparent, weighted metric.

    TrendScore = weighted(mentionVelocity, sourceCount, recency, relatedActivity)

Every weight comes from :class:`~.config.BreakingNewsSettings` and every
component is returned with the total, so the ranking is inspectable in the API
response rather than existing only inside a UI component.

Extraction is deterministic: identical input text and corpus produce identical
topics. There is no embedding model to download and no random tie-break.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from ..logging_config import get_logger
from ..news_analytics import (
    TfIdfCorpus,
    extract_indices,
    extract_symbols,
    extract_topics as lexicon_topics,
    normalize_title,
)
from .config import breaking_news_settings
from .schemas import TrendDirection
from .timeutil import to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.topic_engine")

#: Saturation constants for the trend components, documented so the numbers can
#: be tuned deliberately rather than guessed at.
MENTION_SATURATION = 12.0      # mentions/hour that count as "as hot as it gets"
SOURCE_SATURATION = 6.0        # distinct publishers covering a topic
VELOCITY_SATURATION = 3.0      # additional mentions/hour vs the previous window

#: Words that appear in almost every market headline and therefore identify no
#: topic at all. Without this list the TF-IDF keyword pass promotes "stock" and
#: "growth" to the top of the hot-topics sidebar, which is noise dressed up as a
#: trend. Curated and reviewable — not a statistical cutoff, because a small
#: corpus cannot estimate one reliably.
KEYWORD_BLOCKLIST: frozenset[str] = frozenset({
    "stock", "stocks", "market", "markets", "share", "shares", "shareholder",
    "price", "prices", "pricing", "trading", "trade", "trades", "trader",
    "investor", "investors", "investing", "investment", "growth", "buy",
    "sell", "hold", "key", "focus", "top", "best", "worst", "new", "news",
    "report", "reports", "result", "results", "company", "companies",
    "business", "profit", "profits", "revenue", "value", "gain", "gains",
    "loss", "losses", "index", "indexes", "indices", "fund", "funds",
    "money", "economy", "economic", "financial", "finance", "analyst",
    "analysts", "wall", "street", "week", "month", "year", "today", "time",
    "rise", "rises", "fall", "falls", "high", "higher", "low", "lower",
    "amid", "could", "would", "should", "amid", "says", "said", "update",
})

#: Minimum length for a free-text keyword to be considered a topic at all.
MIN_KEYWORD_LENGTH = 5


@dataclass
class TopicCandidate:
    name: str
    normalized: str
    topic_type: str  # LEXICON | SYMBOL | INDEX | KEYWORD
    weight: float = 1.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "normalized": self.normalized,
            "topic_type": self.topic_type,
            "weight": round(self.weight, 4),
        }


@dataclass
class TopicStats:
    """Everything measurable about one topic in the current window."""

    topic_name: str
    normalized_name: str
    topic_type: str = "LEXICON"
    category: Optional[str] = None
    mention_count: int = 0
    article_ids: list[int] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    entities: set[str] = field(default_factory=set)
    stocks: set[str] = field(default_factory=set)
    indices: set[str] = field(default_factory=set)
    sentiments: list[float] = field(default_factory=list)
    market_linked: int = 0
    high_impact: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    hourly_mentions: dict[str, int] = field(default_factory=dict)
    recent_mentions: int = 0
    previous_mentions: int = 0

    @property
    def article_count(self) -> int:
        return len(self.article_ids)

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def avg_sentiment(self) -> Optional[float]:
        return round(sum(self.sentiments) / len(self.sentiments), 4) if self.sentiments else None


class TopicExtractor:
    """Extracts topic candidates from real article text."""

    def __init__(self, settings: Any = None):
        self.settings = settings or breaking_news_settings

    def extract_topics(self, article: Any, corpus: Optional[TfIdfCorpus] = None) -> list[TopicCandidate]:
        """Candidates for one article, de-duplicated and ordered by weight.

        ``corpus`` (built from the live corpus) makes the keyword candidates
        TF-IDF weighted; without it the extractor falls back to the lexicon and
        entity passes, which need no corpus at all.
        """
        title = _get(article, "title") or ""
        excerpt = _get(article, "excerpt") or ""
        text = f"{title}. {excerpt}"

        candidates: dict[str, TopicCandidate] = {}
        #: Names already claimed by a higher-confidence pass, lower-cased, so the
        #: keyword pass cannot create a second topic for the same thing ("PPL"
        #: and "ppl" were previously two separate entries in the sidebar).
        claimed: set[str] = set()

        # 1. curated finance lexicon — highest confidence, human-maintained.
        for topic in lexicon_topics(text, max_topics=6):
            candidates[topic] = TopicCandidate(topic.replace("-", " ").title(), topic, "LEXICON", 1.0)
            claimed.add(topic.replace("-", " ").lower())

        # 2. validated entities — a symbol only appears if it exists in the real
        #    PSX universe, so a topic is never a typo'd ticker.
        for symbol in extract_symbols(text, max_symbols=6):
            key = f"symbol:{symbol.lower()}"
            candidates[key] = TopicCandidate(symbol, key, "SYMBOL", 0.9)
            claimed.add(symbol.lower())

        for index in extract_indices(text):
            key = f"index:{index.lower()}"
            candidates[key] = TopicCandidate(index, key, "INDEX", 0.9)
            claimed.add(index.lower())

        # 2b. curated global instruments (NVDA, BTC, GOLD, SPX …).
        from .entities import extract_market_entities

        for entry in extract_market_entities(f"{title}. {excerpt or ''}", max_entities=6):
            if entry.entity_type in {"INDEX", "STOCK"} and entry.entity.lower() in claimed:
                continue
            key = f"market:{entry.entity.lower()}"
            candidates.setdefault(key, TopicCandidate(entry.entity, key, entry.entity_type, 0.9))
            claimed.add(entry.entity.lower())
            # Also claim the alias the text actually used ("nvidia" -> NVDA) so
            # the keyword pass does not create a second topic for the same thing.
            if entry.matched:
                claimed.add(entry.matched.lower())

        # 3. TF-IDF keywords — what distinguishes *this* article from the corpus.
        for keyword, weight in self._keywords(text, corpus):
            lowered = keyword.lower()
            if lowered in KEYWORD_BLOCKLIST or lowered in claimed:
                continue
            if len(lowered) < MIN_KEYWORD_LENGTH:
                continue
            key = f"keyword:{lowered}"
            candidates.setdefault(key, TopicCandidate(lowered, key, "KEYWORD", weight))

        ordered = sorted(candidates.values(), key=lambda c: (-c.weight, c.normalized))
        limit = self.settings.max_topics
        return ordered[:limit]

    def _keywords(self, text: str, corpus: Optional[TfIdfCorpus]) -> list[tuple[str, float]]:
        top_k = int(self.settings.topic_keywords_per_article)
        if corpus is not None:
            vector = corpus.vector(text)
            if not vector:
                return []
            ranked = sorted(vector.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
            peak = ranked[0][1] or 1.0
            return [(term, round(min(value / peak, 1.0) * 0.7, 4)) for term, value in ranked]

        from ..news_analytics import default_keywords

        terms = default_keywords(text, top_k=top_k)
        if not terms:
            return []
        counts = Counter(terms)
        peak = max(counts.values()) or 1
        return [(term, round(counts[term] / peak * 0.5, 4)) for term in terms]

    @staticmethod
    def normalize_topic_name(topic: str) -> str:
        return normalize_title(topic).replace(" ", "_") or "unknown"


class TopicAggregator:
    """Aggregates per-topic observations from a window of real articles."""

    def __init__(self, settings: Any = None, extractor: Optional[TopicExtractor] = None):
        self.settings = settings or breaking_news_settings
        self.extractor = extractor or TopicExtractor(settings=self.settings)

    def aggregate(
        self,
        articles: Iterable[Any],
        *,
        corpus: Optional[TfIdfCorpus] = None,
        now: Optional[datetime] = None,
    ) -> dict[str, TopicStats]:
        """Build the per-topic observation table for the supplied articles."""
        reference = to_naive_utc(now) or utcnow()
        velocity_minutes = int(self.settings.topic_velocity_window_hours) * 60
        recent_cutoff = reference - timedelta(minutes=velocity_minutes)
        previous_cutoff = reference - timedelta(minutes=velocity_minutes * 2)

        stats: dict[str, TopicStats] = {}

        for article in articles:
            published = to_naive_utc(_get(article, "published_at"))
            publisher = (_get(article, "publisher") or "").strip()
            article_id = _get(article, "id")
            impact = _get(article, "impact_score")
            sentiment = _get(article, "sentiment_score")

            symbols = [s for s in (_get(article, "related_symbols") or [])]
            indices = [i for i in (_get(article, "related_indices") or [])]
            global_entities = [
                str(entry.get("entity"))
                for entry in (_get(article, "market_entities") or [])
                if isinstance(entry, dict) and entry.get("entity")
            ]
            market_linked = bool(symbols or indices or global_entities)
            high_impact = impact is not None and float(impact) >= 65.0

            for candidate in self.extractor.extract_topics(article, corpus):
                entry = stats.get(candidate.normalized)
                if entry is None:
                    entry = TopicStats(
                        topic_name=candidate.name,
                        normalized_name=candidate.normalized,
                        topic_type=candidate.topic_type,
                    )
                    stats[candidate.normalized] = entry

                entry.mention_count += 1
                if article_id is not None and article_id not in entry.article_ids:
                    entry.article_ids.append(article_id)
                if publisher:
                    entry.sources.add(publisher)
                if market_linked:
                    entry.market_linked += 1
                if high_impact:
                    entry.high_impact += 1
                if sentiment is not None:
                    entry.sentiments.append(float(sentiment))

                # `entities` is the broad association list (PSX + global);
                # `stocks`/`indices` stay PSX-validated so the UI only ever links
                # somewhere the terminal can actually price.
                entry.entities.update(symbols)
                entry.entities.update(global_entities)
                entry.stocks.update(symbols)
                entry.indices.update(indices)

                if published is not None:
                    if entry.first_seen is None or published < entry.first_seen:
                        entry.first_seen = published
                    if entry.last_seen is None or published > entry.last_seen:
                        entry.last_seen = published
                    hour_key = published.strftime("%Y-%m-%dT%H:00")
                    entry.hourly_mentions[hour_key] = entry.hourly_mentions.get(hour_key, 0) + 1
                    if published >= recent_cutoff:
                        entry.recent_mentions += 1
                    elif published >= previous_cutoff:
                        entry.previous_mentions += 1

                if entry.category is None:
                    entry.category = self._category(candidate)

        # A topic with a single mention is noise, not a trend; free-text keywords
        # need more corroboration than a curated theme or a validated ticker.
        minimum = max(int(self.settings.min_topic_mentions), 1)
        keyword_minimum = max(int(getattr(self.settings, "min_keyword_mentions", minimum)), minimum)
        return {
            key: value
            for key, value in stats.items()
            if value.mention_count >= (keyword_minimum if value.topic_type == "KEYWORD" else minimum)
        }

    @staticmethod
    def _category(candidate: TopicCandidate) -> str:
        return {
            "LEXICON": "MARKET THEME",
            "SYMBOL": "EQUITY",
            "STOCK": "GLOBAL EQUITY",
            "INDEX": "INDEX",
            "COMMODITY": "COMMODITY",
            "FOREX": "FOREX",
            "CRYPTO": "CRYPTO",
            "KEYWORD": "KEYWORD",
        }.get(candidate.topic_type, "KEYWORD")


class TopicTrendService:
    """Ranks topics with a transparent weighted metric."""

    def __init__(self, settings: Any = None):
        self.settings = settings or breaking_news_settings
        self.weights = dict(self.settings.topic_trend_weights)

    def calculate_trend_score(self, stats: TopicStats, *, now: Optional[datetime] = None) -> dict:
        """Return the total plus every component and the weights used."""
        components = {
            "mention_velocity": self._mention_velocity(stats),
            "source_count": self._source_count(stats),
            "recency": self._recency(stats, now=now),
            "related_activity": self._related_activity(stats),
        }
        weights = self.weights
        total_weight = sum(weights.values()) or 1.0
        raw = sum(components[name] * weights.get(name, 0.0) for name in components)
        score = max(0.0, min(raw / total_weight, 1.0)) * 100.0
        return {
            "score": round(score, 2),
            "components": {k: round(v, 4) for k, v in components.items()},
            "weights": dict(weights),
        }

    # -- components ------------------------------------------------------

    def _mention_velocity(self, stats: TopicStats) -> float:
        """Mentions per hour inside the trailing velocity window."""
        window_hours = max(int(self.settings.topic_velocity_window_hours), 1)
        rate = stats.recent_mentions / window_hours
        return min(rate / MENTION_SATURATION, 1.0)

    def _source_count(self, stats: TopicStats) -> float:
        return min(stats.source_count / SOURCE_SATURATION, 1.0)

    def _recency(self, stats: TopicStats, *, now: Optional[datetime] = None) -> float:
        if stats.last_seen is None:
            return 0.0
        reference = to_naive_utc(now) or utcnow()
        age_hours = max((reference - stats.last_seen).total_seconds() / 3600.0, 0.0)
        window = max(int(self.settings.topic_trend_window_hours), 1)
        # Exponential decay inside the trend window; nothing outside it.
        return max(0.0, math.pow(0.5, age_hours / max(window / 2.0, 1.0))) if age_hours <= window else 0.0

    def _related_activity(self, stats: TopicStats) -> float:
        """How much *market* activity the topic's coverage actually carries.

        Two measurable shares: coverage that names a validated market entity,
        and coverage the analytics layer already scored as high-impact. Nothing
        here is a monetary volume claim — the spec forbids inventing those, and
        no source supplies them.
        """
        if not stats.mention_count:
            return 0.0
        linked = stats.market_linked / stats.mention_count
        impact = stats.high_impact / stats.mention_count
        return min(linked * 0.6 + impact * 0.4, 1.0)

    # -- direction / velocity -------------------------------------------

    def determine_trend_direction(self, stats: TopicStats) -> TrendDirection:
        """RISING / FALLING / STABLE from real consecutive-window mention counts."""
        previous, recent = stats.previous_mentions, stats.recent_mentions
        if recent > previous:
            return TrendDirection.RISING
        if recent < previous:
            return TrendDirection.FALLING
        if stats.hourly_mentions and len(stats.hourly_mentions) > 1:
            ordered = [stats.hourly_mentions[k] for k in sorted(stats.hourly_mentions)]
            if ordered[-1] > ordered[0]:
                return TrendDirection.RISING
            if ordered[-1] < ordered[0]:
                return TrendDirection.FALLING
        return TrendDirection.STABLE

    def trend_velocity(self, stats: TopicStats) -> float:
        """Change in mentions per hour between the last and previous window."""
        window_hours = max(int(self.settings.topic_velocity_window_hours), 1)
        delta = (stats.recent_mentions - stats.previous_mentions) / window_hours
        return round(delta, 4)

    def acceleration_score(self, stats: TopicStats) -> float:
        """Normalised acceleration in ``[0, 1]``, used by the breaking detector."""
        window_hours = max(int(self.settings.topic_velocity_window_hours), 1)
        delta = (stats.recent_mentions - stats.previous_mentions) / window_hours
        return max(0.0, min(delta / VELOCITY_SATURATION, 1.0))

    def article_velocity(self, stats: TopicStats) -> float:
        """Distinct articles per hour across the topic's lifetime so far."""
        if stats.first_seen is None or stats.last_seen is None:
            return float(stats.article_count)
        span_hours = max((stats.last_seen - stats.first_seen).total_seconds() / 3600.0, 1.0)
        return round(stats.article_count / span_hours, 4)


def _get(article: Any, name: str, default: Any = None) -> Any:
    if isinstance(article, dict):
        return article.get(name, default)
    return getattr(article, name, default)


__all__ = [
    "TopicCandidate",
    "TopicStats",
    "TopicExtractor",
    "TopicAggregator",
    "TopicTrendService",
]
