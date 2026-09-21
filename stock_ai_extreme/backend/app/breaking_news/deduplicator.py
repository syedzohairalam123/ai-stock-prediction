"""
Duplicate detection / event clustering (spec §6).

The problem: the same event reaches the feed five times, once per publisher, and
a naive aggregator presents five independent stories. This module groups those
five into one event, keeps the best-attributed version as the canonical row, and
attaches the rest as corroborating coverage.

Five independent signals are combined with a union-find, so *any* strong signal
is enough to merge two articles and no single signal can be relied on alone:

===================  ==========================================================
signal               what it catches
===================  ==========================================================
exact URL            the identical link arriving twice from two feed entries
normalized title     the identical headline re-syndicated under a new URL
SimHash near-dup     the same wire story with a handful of words changed
MinHash signature    the same story reworded (Jaccard estimate ≥ threshold)
TF-IDF cosine        the same event covered *independently* by two newsrooms —
                     different wording, overlapping vocabulary and entities
===================  ==========================================================

Every merge is also time-gated: two articles about the same company three days
apart are two events, not one, so the SimHash/MinHash/TF-IDF passes only compare
articles that fall inside ``cluster_window_hours`` of each other.

The heavy lifting for the first four signals is done by the algorithms that
already exist in :mod:`news_analytics` (SimHash, MinHash + LSH bands, the
BM25/TF-IDF corpus); this module composes them rather than re-implementing them.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from ..logging_config import get_logger
from ..news_analytics import (
    MinHashIndex,
    SimHashIndex,
    cluster_articles as tfidf_cluster_articles,
    is_duplicate_title,
    normalize_title,
    source_tier,
    tokenize,
)
from .config import breaking_news_settings
from .pipeline import NormalizedArticle
from .sources import publisher_prior
from .timeutil import to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.deduplicator")


@dataclass
class ArticleCluster:
    """A group of articles judged to describe one real-world event."""

    cluster_id: str
    article_ids: list[int] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    indices: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    canonical_article_id: Optional[int] = None
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    max_impact: float = 0.0
    signals: dict[str, int] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.article_ids)

    @property
    def time_span_hours(self) -> float:
        if self.first_seen is None or self.last_seen is None:
            return 0.0
        return round((self.last_seen - self.first_seen).total_seconds() / 3600.0, 4)

    def as_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "article_ids": list(self.article_ids),
            "canonical_article_id": self.canonical_article_id,
            "publishers": list(self.publishers),
            "urls": list(self.urls),
            "symbols": list(self.symbols),
            "indices": list(self.indices),
            "terms": list(self.terms),
            "size": self.size,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "time_span_hours": self.time_span_hours,
            "max_impact": round(self.max_impact, 2),
            "signals": dict(self.signals),
        }


class _UnionFind:
    """Path-compressed union-find over integer article keys."""

    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def add(self, key: int) -> None:
        self.parent.setdefault(key, key)

    def find(self, key: int) -> int:
        self.add(key)
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != root:  # path compression
            self.parent[key], key = root, self.parent[key]
        return root

    def union(self, left: int, right: int) -> bool:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return False
        # Keep the smaller root as the representative for stable ids.
        if root_left > root_right:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        return True


class NewsDeduplicator:
    """Clusters related articles so one event is presented once."""

    def __init__(
        self,
        *,
        similarity_threshold: Optional[float] = None,
        simhash_threshold: Optional[int] = None,
        window_hours: Optional[int] = None,
        settings: Any = None,
    ):
        self.settings = settings or breaking_news_settings
        self.similarity_threshold = (
            similarity_threshold if similarity_threshold is not None else self.settings.similarity_threshold
        )
        self.simhash_threshold = (
            simhash_threshold if simhash_threshold is not None else self.settings.simhash_threshold
        )
        self.window_hours = window_hours if window_hours is not None else self.settings.cluster_window_hours
        self.max_clusters = self.settings.max_clusters

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def cluster_related_articles(
        self,
        articles: Iterable[NormalizedArticle],
        *,
        extra_articles: Optional[list[dict]] = None,
    ) -> list[ArticleCluster]:
        """Group articles into event clusters, largest/most-corroborated first.

        ``extra_articles`` lets the caller add unnormalized rows to the TF-IDF
        pass only (used for keyword context); they do not become cluster members.
        """
        items = [a for a in articles if a.title and a.url]
        if not items:
            return []

        keys = list(range(len(items)))
        by_key: dict[int, NormalizedArticle] = dict(enumerate(items))
        uf = _UnionFind()
        signals: dict[tuple[int, int], set[str]] = defaultdict(set)

        def merge(left: int, right: int, signal: str) -> None:
            if left == right:
                return
            if uf.union(left, right):
                signals[(min(left, right), max(left, right))].add(signal)

        self._merge_by_url(by_key, merge)
        self._merge_by_title(by_key, merge)
        self._merge_by_simhash(by_key, merge)
        self._merge_by_minhash(by_key, merge)
        self._merge_by_tfidf(items, merge)

        # --- materialise clusters -------------------------------------
        groups: dict[int, list[int]] = defaultdict(list)
        for key in keys:
            groups[uf.find(key)].append(key)

        clusters: list[ArticleCluster] = []
        for index, (root, members) in enumerate(sorted(groups.items())):
            member_articles = [by_key[k] for k in members]
            cluster = self._build_cluster(f"evt-{index:04d}", member_articles)
            cluster.signals = self._collect_signals(members, signals)
            clusters.append(cluster)

        clusters.sort(key=lambda c: (-c.size, -c.max_impact, c.cluster_id))
        return clusters[: self.max_clusters]

    # ------------------------------------------------------------------
    # signal passes
    # ------------------------------------------------------------------

    def _merge_by_url(self, by_key: dict[int, NormalizedArticle], merge) -> None:
        seen: dict[str, int] = {}
        for key, article in by_key.items():
            existing = seen.get(article.url)
            if existing is None:
                seen[article.url] = key
            else:
                merge(existing, key, "url")

    def _merge_by_title(self, by_key: dict[int, NormalizedArticle], merge) -> None:
        seen: dict[str, int] = {}
        for key, article in by_key.items():
            normalized = normalize_title(article.title)
            if not normalized:
                continue
            existing = seen.get(normalized)
            if existing is None:
                seen[normalized] = key
                continue
            if self._within_window(by_key[existing], article):
                merge(existing, key, "title")

        # A fuzzy headline pass for re-worded syndication (overlap coefficient).
        # Comparing every pair would be O(n^2) tokenizations, so articles are
        # bucketed by their longest headline tokens first: two rewrites of the
        # same headline almost always share at least one distinctive word, while
        # unrelated stories rarely do.
        for bucket in _fuzzy_buckets(by_key).values():
            for i, left in enumerate(bucket):
                for right in bucket[i + 1:]:
                    left_article, right_article = by_key[left], by_key[right]
                    if not self._within_window(left_article, right_article):
                        continue
                    if is_duplicate_title(left_article.title, right_article.title, threshold=0.85):
                        merge(left, right, "title_fuzzy")

    def _merge_by_simhash(self, by_key: dict[int, NormalizedArticle], merge) -> None:
        index = SimHashIndex(
            bands=max(int(self.settings.simhash_threshold) + 1, 4),
            threshold=int(self.simhash_threshold),
        )
        for key, article in sorted(by_key.items(), key=lambda kv: _published_key(kv[1])):
            fingerprint = _attr_int(article, "simhash")
            if not fingerprint:
                continue
            match = index.find_duplicate(fingerprint)
            if match is not None and self._within_window(by_key.get(match), article):
                merge(int(match), key, "simhash")
            index.add(fingerprint, key)

    def _merge_by_minhash(self, by_key: dict[int, NormalizedArticle], merge) -> None:
        index = MinHashIndex(
            rows=24,
            band_rows=4,
            # MinHash decides near-duplicates, so its threshold stays high even
            # when the TF-IDF event-clustering threshold is deliberately loose.
            threshold=0.75,
        )
        for key, article in sorted(by_key.items(), key=lambda kv: _published_key(kv[1])):
            signature = _attr_signature(article)
            if not signature:
                continue
            match = index.find_duplicate(signature)
            if match is not None and self._within_window(by_key.get(match), article):
                merge(int(match), key, "minhash")
            index.add(signature, key)

    def _merge_by_tfidf(self, items: list[NormalizedArticle], merge) -> None:
        """Same event, independently written — clustered by TF-IDF cosine."""
        payload = [
            {
                "id": index,
                "title": article.title,
                "excerpt": article.excerpt or "",
                "content": "",
                "related_symbols": article.symbols,
                "event_type": article.event_type,
                "published_at": article.published_at,
                "impact_score": article.impact_score,
            }
            for index, article in enumerate(items)
        ]
        try:
            clusters = tfidf_cluster_articles(
                payload,
                threshold=float(self.similarity_threshold),
                max_clusters=self.max_clusters,
            )
        except Exception as exc:  # TF-IDF must never break ingestion
            logger.warning("tf-idf clustering skipped: %s", exc)
            return

        for cluster in clusters:
            members = [int(i) for i in cluster.article_ids]
            if len(members) < 2:
                continue
            # Respect the time gate inside a TF-IDF cluster too: a rolling
            # "earnings season" topic must not merge Monday's story with Friday's.
            anchor = members[0]
            for member in members[1:]:
                if self._within_window(items[anchor], items[member]):
                    merge(anchor, member, "tfidf")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _within_window(self, left: Optional[NormalizedArticle], right: Optional[NormalizedArticle]) -> bool:
        if left is None or right is None:
            return False
        if left.published_at is None or right.published_at is None:
            # Without both timestamps the time gate cannot be evaluated. Be
            # conservative and allow the textual signals to decide, since those
            # already compared real headline/shingle content.
            return True
        span = abs((left.published_at - right.published_at).total_seconds()) / 3600.0
        return span <= self.window_hours

    def _build_cluster(self, cluster_id: str, members: list[NormalizedArticle]) -> ArticleCluster:
        cluster = ArticleCluster(cluster_id=cluster_id)
        for article in members:
            if article.id is not None and article.id not in cluster.article_ids:
                cluster.article_ids.append(article.id)
            if article.publisher and article.publisher not in cluster.publishers:
                cluster.publishers.append(article.publisher)
            if article.url and article.url not in cluster.urls:
                cluster.urls.append(article.url)
            for symbol in article.symbols:
                if symbol not in cluster.symbols:
                    cluster.symbols.append(symbol)
            for index in article.indices:
                if index not in cluster.indices:
                    cluster.indices.append(index)
            if article.published_at is not None:
                cluster.first_seen = (
                    article.published_at if cluster.first_seen is None
                    else min(cluster.first_seen, article.published_at)
                )
                cluster.last_seen = (
                    article.published_at if cluster.last_seen is None
                    else max(cluster.last_seen, article.published_at)
                )
            if article.impact_score is not None:
                cluster.max_impact = max(cluster.max_impact, float(article.impact_score))

        canonical = self._select_canonical(members)
        cluster.canonical_article_id = canonical.id if canonical else None
        cluster.terms = _top_terms(members)
        return cluster

    @staticmethod
    def _select_canonical(members: list[NormalizedArticle]) -> Optional[NormalizedArticle]:
        """Pick the version of the event the reader should see.

        Ranked by, in order: publisher quality (observed reliability prior, then
        the analytics tier), then data completeness (a lede and an image beat
        neither), then the earliest publication time. Deterministic and
        explainable — never "the first one that happened to be ingested".
        """
        if not members:
            return None

        def rank(article: NormalizedArticle) -> tuple:
            prior = publisher_prior(article.publisher, None, article.source)
            tier = source_tier(article.publisher, article.source)
            completeness = (1 if article.excerpt else 0) + (1 if article.image else 0)
            published = article.published_at or datetime.max
            return (round(prior, 4), round(tier, 4), completeness, -published.timestamp())

        return max(members, key=rank)

    @staticmethod
    def _collect_signals(members: list[int], signals: dict[tuple[int, int], set[str]]) -> dict[str, int]:
        member_set = set(members)
        counts: dict[str, int] = defaultdict(int)
        for (left, right), found in signals.items():
            if left in member_set and right in member_set:
                for signal in found:
                    counts[signal] += 1
        return dict(counts)


def _published_key(article: NormalizedArticle) -> float:
    return article.published_at.timestamp() if article.published_at else float("inf")


#: Longest-token bucket count. A headline token of 6+ characters is distinctive
#: enough to be a useful bucket key; short words ("bank", "oil") are not, so
#: they are excluded to keep the buckets from becoming one giant one.
_FUZZY_TOKEN_MIN_LENGTH = 6
_FUZZY_BUCKET_LIMIT = 40


def _fuzzy_buckets(by_key: dict[int, NormalizedArticle]) -> dict[str, list[int]]:
    """Bucket article keys by distinctive headline tokens for the fuzzy pass."""
    buckets: dict[str, list[int]] = defaultdict(list)
    for key, article in by_key.items():
        tokens = [t for t in tokenize(article.title) if len(t) >= _FUZZY_TOKEN_MIN_LENGTH][:3]
        if not tokens:
            tokens = [t for t in tokenize(article.title)][:1]
        for token in tokens:
            buckets[token].append(key)
    return {token: keys for token, keys in buckets.items() if 1 < len(keys) <= _FUZZY_BUCKET_LIMIT}


def _attr_int(article: NormalizedArticle, name: str) -> Optional[int]:
    """Read an optional analytics integer that the normalizer may not carry."""
    value = getattr(article, name, None)
    if value is None and isinstance(article.raw, dict):
        value = article.raw.get(name)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _attr_signature(article: NormalizedArticle) -> list[int]:
    from ..news_analytics import decode_signature

    value = getattr(article, "shingle_signature", None)
    if value is None and isinstance(article.raw, dict):
        value = article.raw.get("shingle_signature")
    return decode_signature(value)


def _top_terms(members: list[NormalizedArticle], top_n: int = 8) -> list[str]:
    """Most frequent non-stopword terms across a cluster, for the UI chips."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for article in members:
        counts.update(set(tokenize(f"{article.title} {article.excerpt or ''}")))
    return [term for term, _ in counts.most_common(top_n)]


class ClusterManager:
    """Keeps the latest cluster assignment for lookup by article id.

    The engine rebuilds clusters from the corpus on every refresh, so this is a
    thin index over the most recent run rather than separately maintained state —
    which is what makes a restart harmless.
    """

    def __init__(self, deduplicator: Optional[NewsDeduplicator] = None):
        self.deduplicator = deduplicator or NewsDeduplicator()
        self.clusters: dict[str, ArticleCluster] = {}
        self.article_to_cluster: dict[int, str] = {}
        self.cluster_of: dict[int, tuple[str, int]] = {}

    def update(self, articles: list[NormalizedArticle]) -> list[ArticleCluster]:
        clusters = self.deduplicator.cluster_related_articles(articles)
        self.clusters = {c.cluster_id: c for c in clusters}
        self.article_to_cluster = {}
        self.cluster_of = {}
        for cluster in clusters:
            for article_id in cluster.article_ids:
                self.article_to_cluster[article_id] = cluster.cluster_id
                self.cluster_of[article_id] = (cluster.cluster_id, cluster.size)
        return clusters

    def get_cluster_for_article(self, article_id: int) -> Optional[ArticleCluster]:
        cluster_id = self.article_to_cluster.get(article_id)
        return self.clusters.get(cluster_id) if cluster_id else None

    def get_related_articles(self, article_id: int) -> list[int]:
        cluster = self.get_cluster_for_article(article_id)
        if not cluster:
            return []
        return [aid for aid in cluster.article_ids if aid != article_id]


__all__ = [
    "ArticleCluster",
    "NewsDeduplicator",
    "ClusterManager",
]
