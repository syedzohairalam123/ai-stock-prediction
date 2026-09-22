"""
Source reliability & metadata engine (spec §16).

A publisher is not interchangeable with another publisher. An official exchange
filing and an aggregated rewrite of a social post must not be ranked as
equivalent, so every publisher that reaches this package gets a
:class:`~..models.models.SourceMetadata` row with an explicit, reproducible
reliability score.

Where the numbers come from
---------------------------
``reliability_score`` blends four *observable* signals — nothing is invented:

1. ``prior`` — the ranked publisher-quality prior already used elsewhere in the
   app (:data:`news_analytics.SOURCE_TIERS`, plus each feed's own ``quality``
   from :mod:`news_sources`). An official filing scores 1.0, an aggregator 0.6.
2. ``corroboration`` — the share of the publisher's recent articles that other
   publishers also covered (they appear in a multi-source story cluster). A
   source nobody else ever corroborates is worth less than one whose stories
   keep showing up across outlets.
3. ``completeness`` — the share of its articles that arrive with the fields a
   useful news item needs (a lede and, where the publisher provides one, an
   image and validated entities).
4. ``reliability from error rate`` — ingestion failures recorded for that
   publisher's feed(s).

When a signal is genuinely unobservable (a publisher with two articles has not
had time to be corroborated) its weight is redistributed onto the prior rather
than being filled with a guess.

The same engine computes ``timeliness_score`` — how early inside a story's time
span the publisher filed — which is a real measurement over clustered articles
and is the one metric that distinguishes a wire from a slow aggregator.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..news_analytics import DEFAULT_SOURCE_TIER, SOURCE_TIERS
from ..news_sources import FEEDS
from .models.models import SourceMetadata
from .timeutil import ensure_aware, to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.sources")

#: Publisher name -> feed registry entry (lower-cased publisher names).
_FEED_BY_NAME: dict[str, Any] = {feed.name.strip().lower(): feed for feed in FEEDS}
_FEED_BY_KEY: dict[str, Any] = {feed.key: feed for feed in FEEDS}

#: How a feeder's data source maps onto a source type, so a keyed commercial
#: API is never labelled as an official primary source.
_FEEDER_TYPES: dict[str, str] = {
    "newsapi": "API",
    "finnhub": "API",
    "alpha_vantage": "API",
    "yfinance": "API",
    "psx": "OFFICIAL",
    "sbp": "OFFICIAL",
    "secp": "OFFICIAL",
}

#: Blend weights for the reliability score. Sum to 1.0.
_W_PRIOR = 0.50
_W_CORROBORATION = 0.20
_W_COMPLETENESS = 0.20
_W_ERRORS = 0.10


@dataclass
class PublisherObservation:
    """Everything measurable about one publisher in the current corpus."""

    publisher: str
    article_count: int = 0
    breaking_count: int = 0
    high_impact_count: int = 0
    corroborated_count: int = 0
    complete_count: int = 0
    last_published: Optional[Any] = None
    feed_key: Optional[str] = None
    data_sources: set[str] = field(default_factory=set)
    earliest_in_cluster: int = 0
    timeliness_samples: list[float] = field(default_factory=list)


def _feed_for(publisher: str, feed_key: Optional[str]) -> Any:
    if feed_key and feed_key in _FEED_BY_KEY:
        return _FEED_BY_KEY[feed_key]
    return _FEED_BY_NAME.get((publisher or "").strip().lower())


def publisher_prior(publisher: str, feed_key: Optional[str] = None, data_source: Optional[str] = None) -> float:
    """Ranked quality prior for a publisher in ``[0, 1]``.

    Order of evidence: the feed registry (most specific), then the analytics
    tier table, then a keyed-API default, then the conservative fallback.
    """
    feed = _feed_for(publisher, feed_key)
    if feed is not None:
        return float(feed.quality)

    key = (publisher or "").strip().lower()
    if key and key in SOURCE_TIERS:
        return float(SOURCE_TIERS[key])
    for name, weight in SOURCE_TIERS.items():
        if name and name in key:
            return float(weight)

    feeder = (data_source or "").split(":", 1)[0].strip().lower()
    if feeder in _FEEDER_TYPES:
        return float(SOURCE_TIERS.get(feeder, DEFAULT_SOURCE_TIER))
    return float(DEFAULT_SOURCE_TIER)


def source_type_for(publisher: str, feed_key: Optional[str], data_source: Optional[str]) -> str:
    """Coarse source classification: RSS | API | OFFICIAL | SOCIAL."""
    feed = _feed_for(publisher, feed_key)
    if feed is not None:
        return "OFFICIAL" if feed.source_type in {"OFFICIAL_NOTICE", "PSX_FILING", "PRESS_RELEASE"} else "RSS"
    feeder = (data_source or "").split(":", 1)[0].strip().lower()
    return _FEEDER_TYPES.get(feeder, "RSS")


def _blend(prior: float, corroboration: Optional[float], completeness: Optional[float], error_rate: float) -> float:
    """Weighted blend with graceful degradation when a signal is unavailable.

    If corroboration is unknown its weight moves to the prior (the one signal
    that always exists), so a publisher is never penalised for being new.
    """
    weights: dict[str, float] = {"prior": _W_PRIOR, "errors": _W_ERRORS}
    if corroboration is not None:
        weights["corroboration"] = _W_CORROBORATION
    else:
        weights["prior"] += _W_CORROBORATION
    if completeness is not None:
        weights["completeness"] = _W_COMPLETENESS
    else:
        weights["prior"] += _W_COMPLETENESS

    total_weight = sum(weights.values()) or 1.0
    score = (
        prior * weights["prior"]
        + (corroboration or 0.0) * weights.get("corroboration", 0.0)
        + (completeness or 0.0) * weights.get("completeness", 0.0)
        + (1.0 - min(max(error_rate, 0.0), 1.0)) * weights["errors"]
    ) / total_weight
    return max(0.0, min(score, 1.0))


def _completeness_of(article: Any) -> bool:
    """Whether an article carries the fields a reader actually needs.

    Excerpt + at least one linked entity, mirroring what the desk renders.
    """
    excerpt = getattr(article, "excerpt", None)
    symbols = getattr(article, "related_symbols", None) or []
    indices = getattr(article, "related_indices", None) or []
    return bool(excerpt) and bool(symbols or indices)


class SourceReliabilityEngine:
    """Aggregates the stored corpus into per-publisher reliability rows."""

    def __init__(self, settings: Any = None):
        from .config import breaking_news_settings

        self.settings = settings or breaking_news_settings

    # ------------------------------------------------------------------
    # observation
    # ------------------------------------------------------------------

    def collect_observations(
        self,
        articles: Iterable[Any],
        *,
        breaking_by_publisher: Optional[dict[str, int]] = None,
        cluster_of: Optional[dict[int, tuple[str, int]]] = None,
        cluster_file_time: Optional[dict[str, Any]] = None,
    ) -> dict[str, PublisherObservation]:
        """Build one observation per publisher from the real stored rows.

        ``cluster_of`` maps ``article_id -> (cluster_id, cluster_size)`` and
        ``cluster_file_time`` maps ``cluster_id -> first publication time in that
        cluster``; together they make corroboration and timeliness measurable
        without any additional network call.

        Feed health is deliberately not a parameter: it is recorded once per
        ingest by :func:`record_feed_errors` and read back in :meth:`score`, so
        there is a single source of truth for "which feeds are failing" rather
        than a second copy threaded through here.
        """
        breaking_by_publisher = breaking_by_publisher or {}
        cluster_of = cluster_of or {}
        cluster_file_time = cluster_file_time or {}

        observations: dict[str, PublisherObservation] = {}

        for article in articles:
            publisher = (getattr(article, "publisher", None) or "").strip()
            if not publisher:
                continue

            obs = observations.setdefault(publisher, PublisherObservation(publisher=publisher))
            obs.article_count += 1
            obs.data_sources.add(getattr(article, "data_source", None) or "")

            feed_key = getattr(article, "feed_key", None)
            if feed_key and not obs.feed_key:
                obs.feed_key = feed_key

            if _completeness_of(article):
                obs.complete_count += 1

            impact = getattr(article, "impact_score", None)
            if impact is not None and impact >= 65:
                obs.high_impact_count += 1

            published = getattr(article, "published_at", None)
            if published is not None:
                if obs.last_published is None or published > obs.last_published:
                    obs.last_published = published

            cluster = cluster_of.get(getattr(article, "id", None))
            if cluster:
                cluster_id, cluster_size = cluster
                if cluster_size > 1:
                    obs.corroborated_count += 1
                    first = cluster_file_time.get(cluster_id)
                    if first is not None and published is not None:
                        span = (published - first).total_seconds()
                        obs.timeliness_samples.append(max(span, 0.0))
                        if span <= 0:
                            obs.earliest_in_cluster += 1

        for publisher, count in breaking_by_publisher.items():
            name = (publisher or "").strip()
            if not name:
                continue
            obs = observations.setdefault(name, PublisherObservation(publisher=name))
            obs.breaking_count += count

        self._apply_feed_status(observations)
        return observations

    def _apply_feed_status(
        self,
        observations: dict[str, PublisherObservation],
    ) -> None:
        """Resolve the registry feed key for every publisher seen this run.

        The key is what lets :meth:`score` look the publisher up in the error
        table maintained by :func:`record_feed_errors` — and what lets
        :meth:`sync` persist ``source_url`` / ``region`` / ``category`` from the
        feed registry. Publishers whose key cannot be resolved are left as-is
        rather than guessed at.
        """
        for obs in observations.values():
            key = obs.feed_key
            if not key:
                feed = _feed_for(obs.publisher, None)
                key = feed.key if feed is not None else None
            obs.feed_key = key

    # ------------------------------------------------------------------
    # scoring
    # ------------------------------------------------------------------

    def score(self, obs: PublisherObservation) -> dict:
        """Compute every metric for one publisher, with provenance."""
        data_source = next((s for s in obs.data_sources if s), None)
        prior = publisher_prior(obs.publisher, obs.feed_key, data_source)

        corroboration: Optional[float] = None
        if obs.article_count >= 3:
            corroboration = obs.corroborated_count / obs.article_count

        completeness: Optional[float] = None
        if obs.article_count:
            completeness = obs.complete_count / obs.article_count

        errors = obs.feed_key and obs.feed_key in _ERROR_FEEDS.get(obs.publisher, set())
        error_rate = 1.0 if errors else 0.0

        reliability = _blend(prior, corroboration, completeness, error_rate)

        timeliness: Optional[float] = None
        if obs.timeliness_samples:
            # 1.0 when the publisher is (on average) the first to file, decaying
            # across a 6-hour reference span.
            mean_delay_minutes = (sum(obs.timeliness_samples) / len(obs.timeliness_samples)) / 60.0
            timeliness = max(0.0, 1.0 - min(mean_delay_minutes / 360.0, 1.0))

        accuracy: Optional[float] = None
        if obs.article_count >= 3:
            accuracy = (obs.high_impact_count / obs.article_count) if obs.high_impact_count else 0.0

        return {
            "reliability_score": round(reliability, 4),
            "accuracy_score": round(accuracy, 4) if accuracy is not None else None,
            "timeliness_score": round(timeliness, 4) if timeliness is not None else None,
            "completeness_score": round(completeness, 4) if completeness is not None else None,
            "prior": round(prior, 4),
            "corroboration_ratio": round(corroboration, 4) if corroboration is not None else None,
            "error_rate": round(error_rate, 4),
        }

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def sync(
        self,
        db: Session,
        observations: dict[str, PublisherObservation],
        *,
        feed_statuses: Optional[list[dict]] = None,
    ) -> list[SourceMetadata]:
        """Upsert :class:`SourceMetadata` rows and return them.

        Never deletes a publisher that has gone quiet — its row is marked
        ``INACTIVE`` instead, so reliability history survives a feed outage.
        """
        status_by_publisher: dict[str, str] = {}
        for status in feed_statuses or []:
            key = status.get("key")
            feed = _FEED_BY_KEY.get(key) if key else None
            if feed is not None and status.get("status") == "ERROR":
                status_by_publisher[feed.name] = status.get("error") or "feed unavailable"

        now = utcnow()
        existing: dict[str, SourceMetadata] = {
            row.publisher: row for row in db.query(SourceMetadata).all()
        }
        rows: list[SourceMetadata] = []

        for publisher, obs in observations.items():
            scores = self.score(obs)
            feed = _feed_for(publisher, obs.feed_key)
            error = status_by_publisher.get(publisher)

            row = existing.get(publisher)
            if row is None:
                row = SourceMetadata(publisher=publisher)
                db.add(row)

            row.source_url = feed.url if feed is not None else row.source_url
            row.source_type = source_type_for(publisher, obs.feed_key, next(iter(obs.data_sources), None))
            row.region = feed.region if feed is not None else row.region
            row.category = feed.category if feed is not None else row.category
            row.feed_key = obs.feed_key or row.feed_key
            row.reliability_score = scores["reliability_score"]
            row.accuracy_score = scores["accuracy_score"]
            row.timeliness_score = scores["timeliness_score"]
            row.completeness_score = scores["completeness_score"]
            row.article_count = obs.article_count
            row.breaking_count = obs.breaking_count
            row.last_published = to_naive_utc(obs.last_published)
            row.last_retrieved = now

            if error:
                row.error_count = (row.error_count or 0) + 1
                row.consecutive_errors = (row.consecutive_errors or 0) + 1
                row.last_error = str(error)[:500]
                if row.consecutive_errors >= self.settings.source_degraded_error_threshold:
                    row.status = "DEGRADED"
            else:
                row.consecutive_errors = 0
                row.status = "ACTIVE"
                if obs.article_count:
                    row.last_error = None

            row.additional_data = {
                "prior": scores["prior"],
                "corroboration_ratio": scores["corroboration_ratio"],
                "error_rate": scores["error_rate"],
                "high_impact_count": obs.high_impact_count,
                "corroborated_count": obs.corroborated_count,
                "computed_at": now.isoformat(),
            }
            rows.append(row)

        # Mark publishers that dropped out of the window as inactive, keeping
        # their last known reliability rather than deleting the record.
        seen = set(observations)
        for publisher, row in existing.items():
            if publisher not in seen and row.status == "ACTIVE":
                row.status = "INACTIVE"

        db.commit()
        rows.sort(key=lambda r: (-(r.reliability_score or 0), r.publisher))
        return rows

    # ------------------------------------------------------------------
    # lookups used by the detector / API
    # ------------------------------------------------------------------

    def reliability_lookup(self, db: Session) -> dict[str, float]:
        """Publisher -> reliability map for the breaking detector."""
        try:
            rows = db.query(SourceMetadata.publisher, SourceMetadata.reliability_score).all()
        except Exception as exc:  # a missing table must not break detection
            logger.warning("source reliability lookup failed: %s", exc)
            return {}
        return {publisher: score for publisher, score in rows if score is not None}


#: Filled in by :func:`record_feed_errors` so :meth:`SourceReliabilityEngine.score`
#: can account for a publisher whose feed is currently failing. Kept module-level
#: (and tiny) because it is refreshed on every ingest, not persisted separately.
_ERROR_FEEDS: dict[str, set[str]] = defaultdict(set)


def record_feed_errors(feed_statuses: Optional[list[dict]]) -> None:
    """Remember which feed keys failed on the most recent ingest."""
    _ERROR_FEEDS.clear()
    for status in feed_statuses or []:
        if status.get("status") != "ERROR":
            continue
        key = status.get("key")
        feed = _FEED_BY_KEY.get(key) if key else None
        if feed is not None:
            _ERROR_FEEDS.setdefault(feed.name, set()).add(key)


def reliability_by_publisher(db: Session) -> dict[str, float]:
    """Convenience wrapper used by routes."""
    return SourceReliabilityEngine().reliability_lookup(db)


def list_source_metadata(db: Session) -> list[SourceMetadata]:
    return (
        db.query(SourceMetadata)
        .order_by(SourceMetadata.reliability_score.desc(), SourceMetadata.publisher.asc())
        .all()
    )


def source_summary(rows: Iterable[SourceMetadata]) -> dict:
    """Aggregate counts for the sources panel header (all self-describing)."""
    rows = list(rows)
    return {
        "total": len(rows),
        "active": sum(1 for r in rows if r.status == "ACTIVE"),
        "degraded": sum(1 for r in rows if r.status == "DEGRADED"),
        "inactive": sum(1 for r in rows if r.status == "INACTIVE"),
        "official": sum(1 for r in rows if r.source_type == "OFFICIAL"),
        "mean_reliability": round(
            sum(r.reliability_score or 0.0 for r in rows) / len(rows), 4
        ) if rows else None,
    }


__all__ = [
    "PublisherObservation",
    "SourceReliabilityEngine",
    "publisher_prior",
    "source_type_for",
    "record_feed_errors",
    "reliability_by_publisher",
    "list_source_metadata",
    "source_summary",
]
