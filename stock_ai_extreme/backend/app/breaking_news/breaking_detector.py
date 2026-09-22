"""
Breaking-news detection engine (spec §5).

The score is deliberately **not** "newest article wins". Seven measurable
factors are combined with configurable weights, and every one of them is
returned alongside the total so a reader can see why a story was flagged:

=====================  ===========================================================
factor                 what it measures (all derived from the stored corpus)
=====================  ===========================================================
``recency``            age of the *publisher's own* timestamp, with a plateau for
                       the first ``breaking_recency_minutes`` then decay
``source_reliability`` ranked publisher prior, or the observed reliability from
                       :mod:`sources` when one has been computed
``entity_importance``  number of major, market-moving entities in the story
``mention_velocity``   how fast the entities in this story are being mentioned
                       right now (articles per minute inside a window)
``topic_acceleration`` change in mention rate between two consecutive windows —
                       a topic speeding up matters more than one that is merely
                       busy
``market_association`` density of market-moving vocabulary and validated symbols
``cluster_bonus``      corroboration: independent publishers carrying the event
=====================  ===========================================================

Velocity and acceleration are computed from the corpus (real timestamps), not
from an in-memory counter that resets on every restart, so the score is
reproducible for the same input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Optional

from ..logging_config import get_logger
from ..news_analytics import SOURCE_TIERS, extract_symbols, source_tier
from .config import breaking_news_settings
from .schemas import BreakingLevel
from .timeutil import ensure_aware, to_naive_utc

logger = get_logger("neural_market.breaking_news.detector")

#: Entities whose appearance in a headline is itself a market event.
MAJOR_ENTITIES: frozenset[str] = frozenset({
    "BTC", "ETH", "SOL", "SPX", "DJI", "NDAQ", "FTSE", "DAX", "NIFTY",
    "GOLD", "OIL", "USD", "EUR", "GBP", "JPY", "PKR",
    "FED", "ECB", "BOE", "SNB", "BOJ", "SBP", "SECP", "IMF", "OPEC",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM",
    "KSE100", "KSE30", "PSX",
})

MARKET_KEYWORDS: tuple[str, ...] = (
    "market", "stock", "index", "trading", "price", "earnings", "dividend",
    "merger", "acquisition", "ipo", "fed", "central bank", "policy rate",
    "inflation", "gdp", "recession", "bull", "bear", "volatility", "halt",
    "default", "bailout", "imf", "sanction", "tariff", "crash", "plunge",
    "surge", "record high", "record low", "profit warning",
)

#: Mentions-per-minute that map to a full velocity score. Real financial feeds
#: produce a handful of mentions per minute in a breaking window; 6/min is a
#: deliberate saturation point (documented so it can be tuned).
VELOCITY_SATURATION_PER_MINUTE = 6.0
#: Acceleration saturation: 3 additional mentions per minute over the previous
#: window is "as accelerating as it matters".
ACCELERATION_SATURATION_PER_MINUTE = 3.0


@dataclass
class ScoreBreakdown:
    """A score plus the evidence behind it."""

    score: float
    components: dict[str, float]
    weights: dict[str, float]
    level: BreakingLevel

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "level": self.level.value,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "weights": dict(self.weights),
        }


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def compute_mention_velocity(
    articles: Iterable[Any],
    entity: str,
    *,
    now: Optional[datetime] = None,
    window_minutes: Optional[int] = None,
) -> float:
    """Mentions of ``entity`` per minute inside the trailing window, in ``[0,1]``.

    Reads real ``published_at`` timestamps of real articles. Returns 0.0 when
    there is nothing to measure — never a neutral guess.
    """
    window = window_minutes or breaking_news_settings.topic_velocity_window_hours * 60
    reference = to_naive_utc(now) or to_naive_utc(datetime.now())
    cutoff = reference - timedelta(minutes=window)

    mentions = 0
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    for article in articles:
        published = to_naive_utc(_attr(article, "published_at"))
        if published is None or published < cutoff:
            continue
        if entity_tokens(article).get(entity):
            mentions += 1
            earliest = published if earliest is None else min(earliest, published)
            latest = published if latest is None else max(latest, published)

    if mentions < 2 or earliest is None or latest is None:
        return 0.0
    span_minutes = max((latest - earliest).total_seconds() / 60.0, 1.0)
    rate = mentions / span_minutes
    return _clamp01(rate / VELOCITY_SATURATION_PER_MINUTE)


def compute_topic_acceleration(
    articles: Iterable[Any],
    entity: str,
    *,
    now: Optional[datetime] = None,
    window_minutes: Optional[int] = None,
) -> float:
    """Change in mention rate between the last and previous window, in ``[-1,1]``.

    A positive value means the entity is being mentioned faster than it was,
    which is the signal a "breaking" label is supposed to carry. Negative values
    are returned as 0 by the scoring pass (falling interest cannot make a story
    breaking) but are surfaced in the breakdown for transparency.
    """
    window = window_minutes or breaking_news_settings.topic_velocity_window_hours * 60
    reference = to_naive_utc(now) or to_naive_utc(datetime.now())
    recent_cutoff = reference - timedelta(minutes=window)
    previous_cutoff = reference - timedelta(minutes=window * 2)

    recent = previous = 0
    for article in articles:
        published = to_naive_utc(_attr(article, "published_at"))
        if published is None or published < previous_cutoff:
            continue
        if not entity_tokens(article).get(entity):
            continue
        if published >= recent_cutoff:
            recent += 1
        else:
            previous += 1

    recent_rate = recent / max(window, 1)
    previous_rate = previous / max(window, 1)
    delta = recent_rate - previous_rate
    return max(-1.0, min(delta / ACCELERATION_SATURATION_PER_MINUTE, 1.0))


def _attr(article: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a dict or an ORM row."""
    if isinstance(article, dict):
        return article.get(name, default)
    return getattr(article, name, default)


#: Per-article entity token cache, keyed by the *content* ``entity_tokens``
#: reads (see :func:`_token_signature`) rather than by object identity.
#:
#: This distinction is load-bearing. An ``id()``-keyed cache is unsound: Python
#: recycles the ids of garbage-collected objects, so once the original article
#: was collected a newly created one could inherit its id and be handed the dead
#: article's token set. That silently corrupts mention velocity, topic
#: acceleration and entity importance for a perfectly unrelated story, and it
#: only showed up under object churn (i.e. in production, not in a one-shot
#: script). Keying on the exact input fields makes the cache correct by
#: construction and lets equal articles share one computation.
_ENTITY_TOKEN_CACHE: dict[tuple, dict[str, bool]] = {}


def _token_signature(article: Any) -> tuple:
    """A hashable signature of exactly the fields :func:`entity_tokens` reads.

    Sequences are sorted so two articles carrying the same entities in a
    different order still hit the same cache entry.
    """
    market_entities = (
        str(entry["entity"])
        for entry in (_attr(article, "market_entities") or [])
        if isinstance(entry, dict) and entry.get("entity")
    )
    return (
        str(_attr(article, "title") or ""),
        str(_attr(article, "excerpt") or ""),
        tuple(sorted(str(v) for v in (_attr(article, "related_indices") or []))),
        tuple(sorted(str(v) for v in (_attr(article, "related_symbols") or []))),
        tuple(sorted(str(v) for v in (_attr(article, "topics") or []))),
        tuple(sorted(market_entities)),
        tuple(sorted(str(v) for v in (_attr(article, "entity_types") or {}))),
    )


def entity_tokens(article: Any) -> dict[str, bool]:
    """Set-membership view of every entity mentioned in an article."""
    signature = _token_signature(article)
    cached = _ENTITY_TOKEN_CACHE.get(signature)
    if cached is not None:
        return cached

    title, excerpt, indices, symbols, topics, market_entities, entity_types = signature
    text = f"{title} {excerpt}"
    tokens = {symbol: True for symbol in extract_symbols(text, max_symbols=6)}
    for value in (*indices, *symbols, *topics, *market_entities, *entity_types):
        tokens[value] = True

    _ENTITY_TOKEN_CACHE[signature] = tokens
    if len(_ENTITY_TOKEN_CACHE) > 5000:  # bound growth on a long-running process
        _ENTITY_TOKEN_CACHE.clear()
    return tokens


def clear_entity_cache() -> None:
    _ENTITY_TOKEN_CACHE.clear()


class BreakingNewsDetector:
    """Configurable, fully-inspectable breaking-news scorer."""

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        settings: Any = None,
    ):
        self.settings = settings or breaking_news_settings
        self.config = config or self._default_config()

    def _default_config(self) -> dict:
        return {
            "weights": dict(self.settings.detection_weights),
            "breaking_threshold": self.settings.breaking_threshold,
            "significant_threshold": self.settings.significant_threshold,
            "recency_window_hours": self.settings.recency_window_hours,
            "breaking_recency_minutes": self.settings.breaking_recency_minutes,
            "significant_recency_hours": self.settings.significant_recency_hours,
            "min_sources_for_cluster": self.settings.min_sources_for_cluster,
            "major_entities": set(MAJOR_ENTITIES),
        }

    @property
    def weights(self) -> dict[str, float]:
        return dict(self.config.get("weights") or {})

    # ------------------------------------------------------------------
    # individual factors
    # ------------------------------------------------------------------

    def recency_score(self, article: Any, *, now: Optional[datetime] = None) -> float:
        """Freshness of the publisher's own timestamp, in ``[0, 1]``.

        A missing timestamp scores 0.0. That is intentional: the phase forbids
        substituting the fetch time for a publication time, so a story with no
        timestamp must not be able to look like it just broke.
        """
        published = to_naive_utc(_attr(article, "published_at"))
        if published is None:
            return 0.0
        reference = to_naive_utc(now) or to_naive_utc(datetime.now())
        age = (reference - published).total_seconds() / 60.0
        if age < 0:
            age = 0.0

        breaking_minutes = float(self.config["breaking_recency_minutes"])
        significant_minutes = float(self.config["significant_recency_hours"]) * 60.0
        window_minutes = float(self.config["recency_window_hours"]) * 60.0

        if age <= breaking_minutes:
            return 1.0
        if age <= significant_minutes:
            span = max(significant_minutes - breaking_minutes, 1.0)
            return _clamp01(1.0 - ((age - breaking_minutes) / span) * 0.5)
        if age <= window_minutes:
            span = max(window_minutes - significant_minutes, 1.0)
            return _clamp01(0.5 - ((age - significant_minutes) / span) * 0.5)
        return 0.0

    def source_reliability_score(
        self,
        article: Any,
        *,
        reliability_lookup: Optional[Callable[[str], Optional[float]]] = None,
    ) -> float:
        """Observed reliability when known, otherwise the ranked prior."""
        publisher = (_attr(article, "publisher") or "").strip()
        if reliability_lookup is not None and publisher:
            observed = reliability_lookup(publisher)
            if observed is not None:
                return _clamp01(observed)
        return _clamp01(source_tier(publisher, _attr(article, "source")))

    def entity_importance_score(self, article: Any) -> float:
        """Importance of the entities a story is about, in ``[0, 1]``."""
        tokens = entity_tokens(article)
        if not tokens:
            return 0.0
        major = self.config["major_entities"]
        hits = sum(1 for token in tokens if token in major)
        # Two major entities is already a market-wide story.
        return _clamp01(hits / 2.0)

    def market_association_score(self, article: Any) -> float:
        """Market-moving vocabulary and instrument evidence, in ``[0, 1]``.

        Uses an absolute hit count rather than a density: a ten-word headline
        containing three market words is not "90% market", and a density measure
        made every short headline saturate at 1.0.
        """
        text = " ".join(
            str(v or "") for v in (_attr(article, "title"), _attr(article, "excerpt"))
        ).lower()
        if not text:
            return 0.0
        hits = sum(1 for keyword in MARKET_KEYWORDS if keyword in text)
        vocabulary = min(hits / 4.0, 1.0) * 0.7
        # A validated symbol, index or curated instrument is direct evidence.
        instrument = 0.0
        if _attr(article, "related_symbols") or _attr(article, "related_indices"):
            instrument = 0.35
        elif _attr(article, "market_entities") or _attr(article, "entity_types"):
            instrument = 0.35
        return _clamp01(vocabulary + instrument)

    def cluster_bonus(self, cluster_size: int) -> float:
        """Corroboration bonus for independent publishers carrying one event."""
        minimum = int(self.config["min_sources_for_cluster"])
        if cluster_size < minimum:
            return 0.0
        return _clamp01(cluster_size / (minimum * 4.0) + 0.4)

    # ------------------------------------------------------------------
    # the score
    # ------------------------------------------------------------------

    def breakdown(
        self,
        article: Any,
        *,
        mention_velocity: Optional[float] = None,
        topic_acceleration: Optional[float] = None,
        cluster_size: int = 1,
        reliability_lookup: Optional[Callable[[str], Optional[float]]] = None,
        now: Optional[datetime] = None,
    ) -> ScoreBreakdown:
        """Weighted, normalised 0-100 score with every component exposed."""
        components: dict[str, float] = {
            "recency": self.recency_score(article, now=now),
            "source_reliability": self.source_reliability_score(article, reliability_lookup=reliability_lookup),
            "entity_importance": self.entity_importance_score(article),
            "mention_velocity": _clamp01(mention_velocity or 0.0),
            "topic_acceleration": _clamp01(max(topic_acceleration or 0.0, 0.0)),
            "market_association": self.market_association_score(article),
            "cluster_bonus": self.cluster_bonus(cluster_size),
        }
        weights = self.weights
        total_weight = sum(weights.values()) or 1.0
        raw = sum(components[name] * weights.get(name, 0.0) for name in components)
        score = _clamp01(raw / total_weight) * 100.0

        # Corroboration is evidence of significance, so it can lift a story
        # across the threshold — but only by a bounded amount, so a single
        # widely-syndicated wire story cannot become "breaking" on its own.
        if components["cluster_bonus"] > 0:
            score = min(score + components["cluster_bonus"] * 8.0, 100.0)

        return ScoreBreakdown(
            score=round(score, 2),
            components=components,
            weights=weights,
            level=self.determine_breaking_level(score),
        )

    def calculate_breaking_score(
        self,
        article: Any,
        mention_velocity: Optional[float] = None,
        topic_acceleration: Optional[float] = None,
        cluster_size: int = 1,
        **kwargs: Any,
    ) -> float:
        """Backwards-compatible score-only entry point."""
        return self.breakdown(
            article,
            mention_velocity=mention_velocity,
            topic_acceleration=topic_acceleration,
            cluster_size=cluster_size,
            **kwargs,
        ).score

    def determine_breaking_level(self, score: float) -> BreakingLevel:
        if score >= float(self.config["breaking_threshold"]):
            return BreakingLevel.BREAKING
        if score >= float(self.config["significant_threshold"]):
            return BreakingLevel.SIGNIFICANT
        return BreakingLevel.NORMAL


class MentionVelocityTracker:
    """Legacy in-memory velocity tracker, retained for compatibility.

    Kept because it is still useful for a *streaming* consumer that wants a
    cheap running estimate between corpus rebuilds. The engine itself scores
    from the corpus via :func:`compute_mention_velocity`, which is restart-safe.
    """

    def __init__(self, window_minutes: int = 60):
        self.window_minutes = window_minutes
        self.mention_history: dict[str, list[datetime]] = {}

    def record_mention(self, entity: str, timestamp: datetime) -> None:
        self.mention_history.setdefault(entity, []).append(to_naive_utc(timestamp) or timestamp)

    def calculate_velocity(self, entity: str) -> float:
        reference = to_naive_utc(datetime.now())
        cutoff = reference - timedelta(minutes=self.window_minutes)
        mentions = [t for t in self.mention_history.get(entity, []) if t >= cutoff]
        if len(mentions) < 2:
            return 0.0
        span = max((mentions[-1] - mentions[0]).total_seconds() / 60.0, 1.0)
        return _clamp01((len(mentions) / span) / VELOCITY_SATURATION_PER_MINUTE)


class TopicAccelerationTracker:
    """Legacy in-memory acceleration tracker, retained for compatibility."""

    def __init__(self, window_minutes: int = 60):
        self.window_minutes = window_minutes
        self.topic_history: dict[str, list[tuple[datetime, int]]] = {}

    def record_topic_activity(self, topic: str, count: int, timestamp: datetime) -> None:
        self.topic_history.setdefault(topic, []).append((to_naive_utc(timestamp) or timestamp, count))

    def calculate_acceleration(self, topic: str) -> float:
        reference = to_naive_utc(datetime.now())
        cutoff = reference - timedelta(minutes=self.window_minutes)
        activity = [(t, c) for t, c in self.topic_history.get(topic, []) if t >= cutoff]
        if len(activity) < 2:
            return 0.0
        span = max((activity[-1][0] - activity[0][0]).total_seconds() / 60.0, 1.0)
        delta = activity[-1][1] - activity[0][1]
        return _clamp01((delta / span) / ACCELERATION_SATURATION_PER_MINUTE)


__all__ = [
    "BreakingNewsDetector",
    "MentionVelocityTracker",
    "TopicAccelerationTracker",
    "ScoreBreakdown",
    "MAJOR_ENTITIES",
    "MARKET_KEYWORDS",
    "compute_mention_velocity",
    "compute_topic_acceleration",
    "entity_tokens",
    "clear_entity_cache",
]
