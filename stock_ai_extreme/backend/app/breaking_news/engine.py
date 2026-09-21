"""
Breaking-news orchestration engine (spec §2 pipeline, §4, §6–§14).

One object owns the whole chain so a caller cannot accidentally run half of it:

    ingest   -> real providers fetch and store through the Phase 8 stack
    build    -> normalize -> cluster -> score -> persist breaking events
             -> aggregate topics + hourly timeline
             -> associate market entities
    analyse  -> observed market movement + forecast probability movement
             -> optional grounded AI summary

Persistence is idempotent: a rebuild updates rows in place keyed by the
underlying article, so repeatedly refreshing the feed does not multiply events,
and restarting the server loses nothing (all state that matters is in the
database, not in a counter).

Everything the engine writes is traceable to a stored article, a real market bar
or a real forecast point. When a step cannot produce an honest value it records
the reason in the ingest report instead of writing a placeholder.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from ..logging_config import get_logger
from ..models import NewsArticle
from ..news_analytics import TfIdfCorpus
from .breaking_detector import BreakingNewsDetector, clear_entity_cache
from .config import breaking_news_settings
from .deduplicator import ArticleCluster, ClusterManager, NewsDeduplicator
from .market_impact import (
    MarketImpactAnalyzer,
    ProbabilityMovementAnalyzer,
    ProviderHistoryFetcher,
)
from .models.models import (
    BreakingNews,
    MarketImpactEvent,
    NewsTopic,
    ProbabilityMovement,
    TopicTimeline,
)
from .pipeline import (
    KeyedAPIProvider,
    NewsAggregator,
    NewsNormalizer,
    NewsRanker,
    NormalizedArticle,
    RSSFeedProvider,
    RankedArticle,
    StoredCorpusProvider,
    SymbolNewsProvider,
)
from .sources import SourceReliabilityEngine, record_feed_errors
from .summarizer import AISummarizer
from .timeutil import to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.engine")


@dataclass
class FeedBundle:
    """The persisted breaking feed plus the metadata that explains it."""

    items: list[BreakingNews] = field(default_factory=list)
    hours: int = 24
    min_score: float = 0.0
    articles_analyzed: int = 0
    clusters_found: int = 0
    sources_consulted: int = 0
    provider_reports: list[dict] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utcnow)
    warnings: list[str] = field(default_factory=list)


class BreakingNewsEngine:
    """Ingests, scores and persists the Phase 17 intelligence."""

    def __init__(
        self,
        *,
        manager: Any = None,
        settings: Any = None,
    ):
        self.settings = settings or breaking_news_settings
        self.manager = manager

        self.detector = BreakingNewsDetector(settings=self.settings)
        self.ranker = NewsRanker(self.detector, settings=self.settings)
        self.deduplicator = NewsDeduplicator(settings=self.settings)
        self.cluster_manager = ClusterManager(self.deduplicator)
        self.normalizer = NewsNormalizer()

        from .topic_engine import TopicAggregator, TopicExtractor, TopicTrendService

        self.topic_extractor = TopicExtractor(settings=self.settings)
        self.topic_aggregator = TopicAggregator(settings=self.settings, extractor=self.topic_extractor)
        self.topic_trends = TopicTrendService(settings=self.settings)

        self.source_engine = SourceReliabilityEngine(settings=self.settings)
        self.impact_analyzer = MarketImpactAnalyzer(settings=self.settings)
        self.probability_analyzer = ProbabilityMovementAnalyzer(settings=self.settings)
        self.summarizer = AISummarizer(settings=self.settings)

        self._fetcher: Optional[ProviderHistoryFetcher] = None
        self._build_lock = asyncio.Lock()
        self.last_ingest_report: Optional[dict] = None
        self.last_build_at: Optional[datetime] = None
        self.last_build_stats: dict = {}

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------

    def configure(self, manager: Any) -> None:
        """Attach the Phase 2 provider manager (called once from main.py)."""
        self.manager = manager
        self._fetcher = None

    @property
    def history_fetcher(self) -> Optional[ProviderHistoryFetcher]:
        if self.manager is None:
            return None
        if self._fetcher is None:
            self._fetcher = ProviderHistoryFetcher(self.manager)
        return self._fetcher

    # ==================================================================
    # INGEST
    # ==================================================================

    async def ingest(
        self,
        db: Session,
        *,
        region: Optional[str] = None,
        live: bool = True,
        symbols: Optional[list[str]] = None,
        analyze_impacts: bool = False,
    ) -> dict:
        """Fetch real news, store it, then rebuild the feed.

        Each live provider is isolated, so one unreachable publisher reduces
        coverage without breaking the run (spec §19).
        """
        started_at = utcnow()
        started = time.perf_counter()
        warnings: list[str] = []
        errors: list[str] = []
        stored = 0
        reports: list[dict] = []
        feed_statuses: list[dict] = []

        if live:
            providers = [
                RSSFeedProvider(db, region=region or self.settings.ingest_region),
                SymbolNewsProvider(db, symbols=symbols),
                KeyedAPIProvider(db, kind="newsapi"),
                KeyedAPIProvider(db, kind="finnhub"),
                KeyedAPIProvider(db, kind="alpha_vantage"),
            ]
            aggregation = await NewsAggregator(providers).collect(normalizer=self.normalizer)
            reports = [r.as_dict() for r in aggregation.reports]
            errors.extend(aggregation.errors)
            feed_statuses = aggregation.feed_statuses

            raw = aggregation.raw_articles
            if raw:
                from ..news_service import get_news_service

                try:
                    store_report = get_news_service().store_articles(db, raw)
                    stored = int(store_report.get("stored", 0))
                except Exception as exc:
                    # A concurrent writer (the maintenance loop ingests on the
                    # same SQLite file) can collide on the unique article URL.
                    # Roll back so this session is usable again and carry on with
                    # whatever is already in the corpus — never leave the request
                    # holding a poisoned transaction.
                    try:
                        db.rollback()
                    except Exception:  # pragma: no cover - defensive
                        pass
                    errors.append(f"store failed: {str(exc)[:300]}")
                    logger.warning("breaking-news store failed: %s", exc)
            elif aggregation.articles:
                # Everything the providers returned was already in the corpus.
                warnings.append("No new articles to store; the corpus is already up to date.")

            accepted = sum(r["normalized"] for r in reports)
            duplicates = sum(r.get("duplicates", 0) for r in reports)
            if duplicates:
                warnings.append(
                    f"{duplicates} item(s) were returned by more than one provider and were counted once."
                )
            if accepted == 0 and reports:
                warnings.append(
                    "No usable articles were returned by the live providers in this run."
                )
        else:
            warnings.append("Live fetch disabled — built from the stored corpus only.")

        record_feed_errors(feed_statuses)

        bundle = await self.rebuild(
            db,
            hours=max(int(self.settings.recency_window_hours), 24),
            feed_statuses=[s.as_dict() if hasattr(s, "as_dict") else dict(s) for s in feed_statuses],
        )

        impact_events = 0
        probability_movements = 0
        if analyze_impacts and self.settings.market_impact_enabled:
            impact_events, probability_movements = await self.analyze_top_events(db, bundle)

        report = {
            "started_at": started_at.isoformat(),
            "finished_at": utcnow().isoformat(),
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "stored_articles": stored,
            "corpus_articles": bundle.articles_analyzed,
            "breaking_events": len(bundle.items),
            "topics_updated": int(self.last_build_stats.get("topics", 0)),
            "impact_events": impact_events,
            "probability_movements": probability_movements,
            "providers": reports,
            "errors": errors,
            "warnings": warnings,
        }
        self.last_ingest_report = report
        logger.info(
            "breaking-news ingest: stored=%d, corpus=%d, events=%d, impacts=%d, probabilities=%d",
            stored, bundle.articles_analyzed, len(bundle.items), impact_events, probability_movements,
        )
        return report

    # ==================================================================
    # REBUILD (analysis over the stored corpus)
    # ==================================================================

    async def rebuild(
        self,
        db: Session,
        *,
        hours: int = 24,
        feed_statuses: Optional[list[dict]] = None,
    ) -> FeedBundle:
        """Normalize -> cluster -> score -> persist. Network-free."""
        async with self._build_lock:
            return await self._rebuild(db, hours=hours, feed_statuses=feed_statuses or [])

    async def _rebuild(
        self,
        db: Session,
        *,
        hours: int,
        feed_statuses: list[dict],
    ) -> FeedBundle:
        clear_entity_cache()
        started = time.perf_counter()

        # --- 1. corpus -> normalized articles ---------------------------
        provider = StoredCorpusProvider(db, hours=hours)
        raw_articles = await provider.fetch()
        articles: list[NormalizedArticle] = []
        missing_counts: dict[str, int] = {}
        rejected = 0
        for row in raw_articles:
            article = self.normalizer.normalize(row)
            if article is None:
                rejected += 1
                continue
            for name in article.missing:
                missing_counts[name] = missing_counts.get(name, 0) + 1
            articles.append(article)

        bundle = FeedBundle(
            hours=hours,
            articles_analyzed=len(articles),
            generated_at=utcnow(),
        )
        if rejected:
            bundle.warnings.append(f"{rejected} stored row(s) were unusable (no title or no link).")
        if not articles:
            bundle.warnings.append(
                "No articles in the corpus window. POST /api/breaking-news/refresh to ingest live feeds."
            )
            self.last_build_at = utcnow()
            return bundle

        # --- 2. cluster (dedup) ----------------------------------------
        clusters = self.deduplicator.cluster_related_articles(articles)
        self.cluster_manager.update(articles)
        cluster_of = self.cluster_manager.cluster_of
        cluster_first = {
            c.cluster_id: c.first_seen for c in clusters if c.first_seen is not None
        }
        bundle.clusters_found = len(clusters)

        # --- 3. source reliability (observed, then persisted) ----------
        breaking_by_publisher = self._breaking_counts_by_publisher(db)
        observations = self.source_engine.collect_observations(
            raw_articles,
            breaking_by_publisher=breaking_by_publisher,
            cluster_of=cluster_of,
            cluster_file_time=cluster_first,
            feed_statuses=feed_statuses,
        )
        reliability_map = {
            publisher: self.source_engine.score(obs)["reliability_score"]
            for publisher, obs in observations.items()
        }
        bundle.sources_consulted = len(observations)
        try:
            self.source_engine.sync(db, observations, feed_statuses=feed_statuses)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("source metadata sync failed: %s", exc)
            bundle.warnings.append(f"Source metadata could not be persisted: {exc}")

        # --- 4. score ------------------------------------------------
        ranked = self.ranker.rank(
            articles,
            cluster_of=cluster_of,
            reliability_lookup=reliability_map.get,
        )

        # --- 5. persist breaking events (one row per cluster) ---------
        persisted, persisted_count, pruned = self._persist_breaking(db, clusters, ranked, hours)
        bundle.items = persisted

        # --- 6. topics ------------------------------------------------
        corpus = self._corpus(db, articles)
        topics_count = self._persist_topics(db, ranked, corpus)

        # --- 7. market entity association ----------------------------
        self._attach_market_associations(db, persisted)

        try:
            db.commit()
        except Exception as exc:  # pragma: no cover - defensive
            db.rollback()
            logger.warning("breaking-news commit failed: %s", exc)
            bundle.warnings.append(f"Could not persist breaking feed: {exc}")

        self.last_build_at = utcnow()
        self.last_build_stats = {
            "articles": len(articles),
            "clusters": len(clusters),
            "events": engine_len(persisted),
            "topics": topics_count,
            "sources_consulted": bundle.sources_consulted,
            "pruned": pruned,
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "missing_fields": missing_counts,
        }
        bundle.provider_reports = [{
            "name": "stored-corpus",
            "ok": True,
            "fetched": len(raw_articles),
            "normalized": len(articles),
            "rejected": rejected,
            "missing_fields": missing_counts,
        }]
        logger.info("breaking-news rebuild: %s", self.last_build_stats)
        return bundle

    async def ensure_fresh(
        self,
        db: Session,
        *,
        hours: int = 24,
        force: bool = False,
        max_age_seconds: Optional[int] = None,
    ) -> FeedBundle:
        """Return the persisted feed for a window, rebuilding when needed.

        The background maintenance loop keeps this warm; this method is what makes
        the API correct when background jobs are disabled or the process just
        started, so a user never sees an empty breaking desk simply because a
        scheduled task has not run yet.
        """
        existing = self.feed_query(db, hours=hours)
        age_limit = max_age_seconds if max_age_seconds is not None else int(
            self.settings.breaking_news_cache_ttl_seconds
        )
        stale = (
            self.last_build_at is None
            or (utcnow() - self.last_build_at).total_seconds() > age_limit
        )
        if not force and existing and not stale:
            return FeedBundle(
                items=existing,
                hours=hours,
                generated_at=self.last_build_at or utcnow(),
                articles_analyzed=int(self.last_build_stats.get("articles", len(existing))),
                clusters_found=int(self.last_build_stats.get("clusters", 0)),
                sources_consulted=int(self.last_build_stats.get("sources_consulted", 0)),
                provider_reports=[],
            )
        return await self.rebuild(db, hours=hours)

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _breaking_counts_by_publisher(db: Session) -> dict[str, int]:
        """Real breaking counts from the previous run, for source scoring."""
        cutoff = utcnow() - timedelta(days=7)
        try:
            rows = (
                db.query(BreakingNews.publisher)
                .filter(BreakingNews.published_at >= cutoff)
                .all()
            )
        except Exception:
            return {}
        counts: dict[str, int] = {}
        for (publisher,) in rows:
            if publisher:
                counts[publisher] = counts.get(publisher, 0) + 1
        return counts

    def _persist_breaking(
        self,
        db: Session,
        clusters: list[ArticleCluster],
        ranked: list[RankedArticle],
        hours: int,
    ) -> tuple[list[BreakingNews], int, int]:
        """Upsert one row per event cluster; return the rows for the window."""
        ranked_by_id = {r.article.id: r for r in ranked if r.article.id is not None}
        article_by_id = {r.article.id: r.article for r in ranked if r.article.id is not None}

        existing = {
            row.article_id: row
            for row in db.query(BreakingNews).filter(BreakingNews.article_id.isnot(None)).all()
        }

        written: list[BreakingNews] = []
        for cluster in clusters:
            members = [ranked_by_id[aid] for aid in cluster.article_ids if aid in ranked_by_id]
            if not members:
                continue

            # The reader sees the best-attributed version of the event with the
            # event's own (highest) significance score.
            canonical = self._canonical_member(cluster, members, article_by_id)
            best = max(members, key=lambda r: r.score)

            row = existing.get(canonical.article.id)
            if row is None:
                row = BreakingNews(article_id=canonical.article.id)
                db.add(row)

            self._apply_breaking_row(row, canonical, best, cluster)
            written.append(row)

        db.flush()

        # Prune rows that can no longer be shown by any feed window.
        cutoff = utcnow() - timedelta(hours=int(self.settings.retention_hours))
        pruned = 0
        try:
            pruned = (
                db.query(BreakingNews)
                .filter(BreakingNews.published_at < cutoff)
                .delete(synchronize_session=False)
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("breaking prune skipped: %s", exc)

        cutoff_window = utcnow() - timedelta(hours=hours)
        rows = (
            db.query(BreakingNews)
            .filter(BreakingNews.published_at >= cutoff_window)
            .order_by(BreakingNews.breaking_score.desc(), BreakingNews.published_at.desc())
            .limit(int(self.settings.feed_max_items))
            .all()
        )
        return rows, len(written), int(pruned or 0)

    @staticmethod
    def _canonical_member(
        cluster: ArticleCluster,
        members: list[RankedArticle],
        article_by_id: dict[int, NormalizedArticle],
    ) -> RankedArticle:
        if cluster.canonical_article_id is not None:
            row = next((m for m in members if m.article.id == cluster.canonical_article_id), None)
            if row is not None:
                return row
        return max(members, key=lambda r: (r.breakdown.components.get("source_reliability", 0), r.score))

    def _apply_breaking_row(
        self,
        row: BreakingNews,
        canonical: RankedArticle,
        best: RankedArticle,
        cluster: ArticleCluster,
    ) -> None:
        article = canonical.article
        breakdown = best.breakdown

        row.article_url = article.url
        row.title = article.title
        row.publisher = article.publisher
        row.published_at = to_naive_utc(article.published_at) or utcnow()
        row.url = article.url
        row.image = article.image
        row.excerpt = article.excerpt
        row.category = article.category
        row.source = article.source
        row.data_mode = article.data_mode

        row.breaking_score = breakdown.score
        row.breaking_level = breakdown.level.value
        row.entity_importance = breakdown.components.get("entity_importance")
        row.mention_velocity = breakdown.components.get("mention_velocity")
        row.topic_acceleration = breakdown.components.get("topic_acceleration")
        row.source_reliability = breakdown.components.get("source_reliability")
        row.score_components = breakdown.components
        row.score_weights = breakdown.weights

        row.cluster_id = cluster.cluster_id
        row.cluster_size = cluster.size
        row.related_articles = [aid for aid in cluster.article_ids if aid != article.id]

        # PSX-validated symbols + curated global instruments, in one list, with a
        # type per entity so impact analysis knows what it is looking at.
        global_entities = [e["entity"] for e in (canonical.article.market_entities or []) if e.get("entity")]
        row.affected_entities = list(dict.fromkeys([
            *canonical.article.symbols,
            *cluster.symbols,
            *global_entities,
        ]))
        row.affected_indices = list(dict.fromkeys([*canonical.article.indices, *cluster.indices]))
        row.topics = list(canonical.article.topics)
        entity_types = {
            **(canonical.article.entity_types or {}),
            **{e: "STOCK" for e in cluster.symbols},
            **{i: "INDEX" for i in cluster.indices},
        }
        row.market_associations = {
            "symbols": row.affected_entities,
            "indices": row.affected_indices,
            "entity_types": entity_types,
            "publishers": cluster.publishers,
            "corroboration": cluster.size,
            "signals": cluster.signals,
            # The terms that hold the cluster together — surfaced by /clusters so
            # a reader can see *why* these articles were grouped.
            "terms": list(cluster.terms),
        }

    def _persist_topics(self, db: Session, ranked: list[RankedArticle], corpus: TfIdfCorpus) -> int:
        """Aggregate + upsert topics and append their hourly timeline buckets."""
        article_payload = [
            {
                "id": r.article.id,
                "title": r.article.title,
                "excerpt": r.article.excerpt,
                "publisher": r.article.publisher,
                "published_at": r.article.published_at,
                "related_symbols": r.article.symbols,
                "related_indices": r.article.indices,
                "market_entities": r.article.market_entities,
                "impact_score": r.article.impact_score,
                "sentiment_score": r.article.sentiment_score,
            }
            for r in ranked
        ]
        stats = self.topic_aggregator.aggregate(article_payload, corpus=corpus)
        if not stats:
            return 0

        now = utcnow()
        existing = {
            row.normalized_name: row for row in db.query(NewsTopic).all()
        }

        written = 0
        for key, topic in stats.items():
            trend = self.topic_trends.calculate_trend_score(topic, now=now)
            direction = self.topic_trends.determine_trend_direction(topic)

            row = existing.get(key)
            if row is None:
                row = NewsTopic(normalized_name=key, topic_name=topic.topic_name)
                db.add(row)

            row.topic_name = topic.topic_name
            row.topic_type = topic.topic_type
            row.category = topic.category
            row.mention_count = topic.mention_count
            row.article_count = topic.article_count
            row.article_velocity = self.topic_trends.article_velocity(topic)
            row.source_count = topic.source_count
            row.recency_score = trend["components"].get("recency")
            row.related_activity = trend["components"].get("related_activity")
            row.trend_score = trend["score"]
            row.trend_direction = direction.value
            row.trend_velocity = self.topic_trends.trend_velocity(topic)
            row.trend_components = trend["components"]
            row.trend_weights = trend["weights"]
            row.related_entities = sorted(topic.entities)[:25]
            row.related_stocks = sorted(topic.stocks)[:25]
            row.related_indices = sorted(topic.indices)[:10]
            row.sample_article_ids = topic.article_ids[:25]
            row.first_seen = to_naive_utc(topic.first_seen)
            row.last_seen = to_naive_utc(topic.last_seen) or now
            written += 1

        db.flush()

        # Hourly timeline for the topics that are actually trending.
        top_topics = sorted(stats.values(), key=lambda t: -t.mention_count)[: 25]
        rows_by_name = {
            row.normalized_name: row for row in db.query(NewsTopic).all()
        }
        for topic in top_topics:
            row = rows_by_name.get(topic.normalized_name)
            if row is None:
                continue
            self._upsert_timeline(db, row, topic, now)

        self._prune_topics(db, stats, rows_by_name)
        return written

    @staticmethod
    def _prune_topics(db: Session, stats: dict, rows_by_name: dict[str, NewsTopic]) -> int:
        """Remove topics the current build no longer produces.

        Without this the topic table only ever grows: a keyword that was briefly
        hot during one ingest stays on the sidebar forever. Guarded on a
        non-empty result so an empty corpus window (nothing ingested yet) can
        never wipe the desk.
        """
        if not stats:
            return 0

        current = set(stats)
        stale = [row for name, row in rows_by_name.items() if name not in current]
        if not stale:
            return 0

        stale_ids = [row.id for row in stale]
        try:
            db.query(TopicTimeline).filter(TopicTimeline.topic_id.in_(stale_ids)).delete(
                synchronize_session=False
            )
            db.query(NewsTopic).filter(NewsTopic.id.in_(stale_ids)).delete(synchronize_session=False)
            logger.info("pruned %d stale topic(s)", len(stale_ids))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("topic prune skipped: %s", exc)
            return 0
        return len(stale_ids)

    def _upsert_timeline(self, db: Session, topic_row: NewsTopic, topic, now: datetime) -> None:
        """Write one bucket per hour the topic was mentioned in (idempotent)."""
        for hour_key, mentions in topic.hourly_mentions.items():
            bucket = _parse_hour(hour_key)
            if bucket is None:
                continue
            existing = (
                db.query(TopicTimeline)
                .filter(TopicTimeline.topic_id == topic_row.id, TopicTimeline.timestamp == bucket)
                .first()
            )
            if existing is None:
                existing = TopicTimeline(topic_id=topic_row.id, timestamp=bucket)
                db.add(existing)
            existing.mention_count = mentions
            existing.article_count = topic.article_count
            existing.source_count = topic.source_count
            existing.trend_score = topic_row.trend_score
            existing.related_activity = topic_row.related_activity

    def _attach_market_associations(self, db: Session, rows: list[BreakingNews]) -> None:
        """Record which known market instruments each event plausibly touches.

        This deliberately only *lists* the instruments (a mapping), it does not
        measure a movement — that is :meth:`analyze_top_events`' job, and it needs
        network access that a plain rebuild must not depend on.
        """
        for row in rows:
            associations = dict(row.market_associations or {})
            candidates = []
            for entity in (row.affected_entities or [])[:8]:
                candidates.append({"entity": entity, "entity_type": "STOCK"})
            for index in (row.affected_indices or [])[:4]:
                candidates.append({"entity": index, "entity_type": "INDEX"})
            associations["candidates"] = candidates
            row.market_associations = associations

    @staticmethod
    def _corpus(db: Session, articles: list[NormalizedArticle]) -> TfIdfCorpus:
        documents = [f"{a.title} {a.excerpt or ''}" for a in articles]
        try:
            rows = db.query(NewsArticle.title, NewsArticle.excerpt).limit(2000).all()
            documents.extend(f"{t or ''} {e or ''}" for t, e in rows)
        except Exception as exc:  # a corpus failure must not stop the build
            logger.debug("corpus query failed, using window only: %s", exc)
        return TfIdfCorpus(documents)

    # ==================================================================
    # MARKET IMPACT + PROBABILITY (network)
    # ==================================================================

    async def analyze_top_events(self, db: Session, bundle: FeedBundle) -> tuple[int, int]:
        """Run impact + probability analysis for the highest-scoring events."""
        if self.history_fetcher is None:
            bundle.warnings.append("Market impact skipped: no provider manager configured.")
            return 0, 0

        limit = int(self.settings.top_events_for_impact)
        if limit <= 0:
            return 0, 0

        events = [row for row in bundle.items if row.breaking_level != "NORMAL"][:limit]
        if not events:
            events = bundle.items[:limit]

        impact_total = 0
        probability_total = 0
        for row in events:
            try:
                impacts = await self.analyze_impact(db, row)
                impact_total += len(impacts)
            except Exception as exc:
                logger.warning("impact analysis failed for %s: %s", row.id, exc)
                bundle.warnings.append(f"Impact analysis failed for one event: {exc}")
            try:
                probability_total += len(await self.analyze_probability(db, row))
            except Exception as exc:
                logger.warning("probability analysis failed for %s: %s", row.id, exc)

        try:
            db.commit()
        except Exception as exc:  # pragma: no cover - defensive
            db.rollback()
            logger.warning("impact commit failed: %s", exc)
        return impact_total, probability_total

    async def analyze_impact(
        self,
        db: Session,
        row: BreakingNews,
        *,
        entity: Optional[str] = None,
        entity_type: str = "AUTO",
        window: Optional[str] = None,
    ) -> list[MarketImpactEvent]:
        """Observed movement for one event, across the configured windows."""
        fetcher = self.history_fetcher
        if fetcher is None or not row.published_at:
            return []

        published = to_naive_utc(row.published_at)
        targets = [(entity, entity_type)] if entity else self._impact_targets(row)
        window = window or None
        written: list[MarketImpactEvent] = []

        for target, kind in targets[: int(self.settings.max_entities_per_event)]:
            analysis = await self.impact_analyzer.analyze_all_windows(
                published_at=published,
                entity=target,
                entity_type=kind,
                fetcher=fetcher,
                windows=[window] if window else None,
            )
            for result in analysis["windows"]:
                if not result.get("window_available"):
                    continue
                event = self._upsert_impact(db, row, result)
                if event is not None:
                    written.append(event)

        if written:
            row.impact_detected = True
            row.impact_data = self._impact_summary(written)
        return written

    def _impact_targets(self, row: BreakingNews) -> list[tuple[str, str]]:
        """Entities worth measuring for this event, most important first.

        Only *priceable* entities are returned: a policy actor (FED, IMF, SBP)
        matters for ranking but has no price series, so asking a market provider
        for it would produce a guaranteed unavailability.
        """
        from .entities import NON_PRICEABLE_ENTITIES

        types = (row.market_associations or {}).get("entity_types") or {}
        targets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for entity in (row.affected_entities or []):
            name = str(entity).strip().upper()
            if not name or name in NON_PRICEABLE_ENTITIES or name in seen:
                continue
            seen.add(name)
            targets.append((name, types.get(name, "AUTO")))
        for index in (row.affected_indices or []):
            name = str(index).strip().upper()
            if name and name not in seen:
                seen.add(name)
                targets.append((name, "INDEX"))
        return targets

    @staticmethod
    def _upsert_impact(db: Session, row: BreakingNews, result: dict) -> Optional[MarketImpactEvent]:
        existing = (
            db.query(MarketImpactEvent)
            .filter(
                MarketImpactEvent.breaking_news_id == row.id,
                MarketImpactEvent.entity == result["entity"],
                MarketImpactEvent.observation_window == result["observation_window"],
            )
            .first()
        )
        event = existing or MarketImpactEvent(
            breaking_news_id=row.id,
            entity=result["entity"],
            observation_window=result["observation_window"],
        )
        if existing is None:
            db.add(event)

        event.article_id = row.article_id
        event.entity_type = result["entity_type"]
        event.provider_symbol = result.get("provider_symbol")
        event.data_source = result.get("data_source")
        event.news_published_at = result["news_published_at"]
        event.observation_started_at = result.get("observation_started_at")
        event.observation_ended_at = result.get("observation_ended_at")
        event.bars_before = result.get("bars_before", 0)
        event.bars_after = result.get("bars_after", 0)
        event.window_available = bool(result.get("window_available"))
        event.market_data_before = result.get("market_data_before")
        event.market_data_after = result.get("market_data_after")
        event.series = result.get("series") or []
        event.price_change = result.get("price_change")
        event.price_change_percent = result.get("price_change_percent")
        event.volume_change = result.get("volume_change")
        event.volume_change_percent = result.get("volume_change_percent")
        event.max_favorable_excursion_percent = result.get("max_favorable_excursion_percent")
        event.max_adverse_excursion_percent = result.get("max_adverse_excursion_percent")
        event.realized_volatility_percent = result.get("realized_volatility_percent")
        event.impact_magnitude = result.get("impact_magnitude") or "NONE"
        event.correlation_score = result.get("correlation_score")
        event.confidence = result.get("confidence")
        event.source_reliability = row.source_reliability
        event.notes = result.get("notes")
        return event

    @staticmethod
    def _impact_summary(events: list[MarketImpactEvent]) -> dict:
        """Compact per-entity summary stored on the breaking row itself."""
        summary: dict[str, Any] = {}
        for event in events:
            summary.setdefault(event.entity, {})[event.observation_window] = {
                "price_change_percent": event.price_change_percent,
                "impact_magnitude": event.impact_magnitude,
                "window_available": event.window_available,
                "bars_before": event.bars_before,
                "bars_after": event.bars_after,
                "data_source": event.data_source,
            }
        return summary

    async def analyze_probability(self, db: Session, row: BreakingNews) -> list[ProbabilityMovement]:
        """Observed Phase 14 forecast probability movement for one event."""
        if not self.settings.probability_movement_enabled or not row.published_at:
            return []

        from ..forecast_markets import fetch_markets

        try:
            markets = await fetch_markets(
                self.settings.probability_max_markets * 8, 15.0
            )
        except Exception as exc:
            logger.debug("forecast markets unavailable: %s", exc)
            return []
        if not markets:
            return []

        text = f"{row.title} {row.excerpt or ''} {' '.join(row.affected_entities or [])}"
        analyses = await self.probability_analyzer.find_and_analyze(
            article_text=text,
            published_at=to_naive_utc(row.published_at),
            markets=markets,
            observation_window=self.settings.default_observation_window,
        )

        written: list[ProbabilityMovement] = []
        for analysis in analyses:
            existing = (
                db.query(ProbabilityMovement)
                .filter(
                    ProbabilityMovement.breaking_news_id == row.id,
                    ProbabilityMovement.market_id == analysis["market_id"],
                )
                .first()
            )
            movement = existing or ProbabilityMovement(
                breaking_news_id=row.id,
                market_id=analysis["market_id"],
            )
            if existing is None:
                db.add(movement)

            movement.article_id = row.article_id
            movement.market_name = analysis.get("market_name")
            movement.market_url = analysis.get("market_url")
            movement.news_published_at = analysis["news_published_at"]
            movement.observation_window = analysis["observation_window"]
            movement.probability_before = analysis.get("probability_before")
            movement.probability_after = analysis.get("probability_after")
            movement.probability_change = analysis.get("probability_change")
            movement.movement_direction = analysis.get("movement_direction")
            movement.impact_magnitude = analysis.get("impact_magnitude")
            movement.source_name = analysis.get("source_name")
            movement.source_url = analysis.get("source_url")
            movement.series = analysis.get("series") or []
            movement.source_reliability = row.source_reliability
            written.append(movement)
        return written

    # ==================================================================
    # AI SUMMARY
    # ==================================================================

    async def summarize(self, db: Session, row: BreakingNews) -> dict:
        """Grounded AI summary for one event, persisted on the row."""
        result = await self.summarizer.summarize(
            title=row.title,
            excerpt=row.excerpt,
            publisher=row.publisher,
            published_at=row.published_at.isoformat() if row.published_at else None,
            breaking_score=row.breaking_score,
            affected_entities=row.affected_entities or [],
        )
        payload = result.as_dict()
        if result.status == "OK" and result.summary:
            row.ai_summary = result.summary
            row.ai_summary_model = result.model
            row.ai_summary_generated_at = to_naive_utc(result.generated_at) or utcnow()
            row.ai_summary_error = None
            db.commit()
        elif result.status in {"UNAVAILABLE", "DISABLED"}:
            row.ai_summary_error = result.error
            db.commit()
        return payload

    # ==================================================================
    # read helpers
    # ==================================================================

    def feed_query(
        self,
        db: Session,
        *,
        hours: int = 24,
        min_score: float = 0.0,
        level: Optional[str] = None,
        category: Optional[str] = None,
        entity: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[BreakingNews]:
        cutoff = utcnow() - timedelta(hours=hours)
        query = db.query(BreakingNews).filter(
            BreakingNews.published_at >= cutoff,
            BreakingNews.breaking_score >= min_score,
        )
        if level:
            query = query.filter(BreakingNews.breaking_level == level)
        if category:
            query = query.filter(BreakingNews.category == category)
        rows = (
            query.order_by(BreakingNews.breaking_score.desc(), BreakingNews.published_at.desc())
            .limit(limit or int(self.settings.feed_max_items))
            .all()
        )
        if entity:
            needle = entity.strip().upper()
            rows = [
                row for row in rows
                if needle in {e.upper() for e in (row.affected_entities or [])}
                or needle in {i.upper() for i in (row.affected_indices or [])}
            ]
        return rows

    def related_articles(self, db: Session, row: BreakingNews) -> list[dict]:
        """Corroborating coverage for an event, as compact rows."""
        ids = [aid for aid in (row.related_articles or []) if isinstance(aid, int)]
        if not ids:
            return []
        rows = db.query(NewsArticle).filter(NewsArticle.id.in_(ids)).all()
        by_id = {article.id: article for article in rows}
        return [
            {
                "id": article.id,
                "title": article.title,
                "publisher": article.publisher,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "url": article.source_url,
                "image": article.image_url,
                "data_mode": article.data_mode,
            }
            for article in (by_id[aid] for aid in ids if aid in by_id)
        ]


def engine_len(rows: Iterable[Any]) -> int:
    try:
        return len(list(rows))
    except TypeError:
        return 0


def _unique(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in out:
            out.append(text)
    return out


def _parse_hour(hour_key: str) -> Optional[datetime]:
    try:
        return datetime.strptime(hour_key, "%Y-%m-%dT%H:00")
    except (TypeError, ValueError):
        return None


#: Process-wide engine instance. `configure_breaking_news()` in ``__init__``
#: wires the provider manager into it once main.py has built one.
engine = BreakingNewsEngine()


__all__ = ["BreakingNewsEngine", "FeedBundle", "engine"]
