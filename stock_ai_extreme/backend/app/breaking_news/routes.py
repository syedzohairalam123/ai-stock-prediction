"""
REST + streaming API for Phase 17.

Endpoint map (all under ``/api/breaking-news``):

======================  =======================================================
``GET  /health``        subsystem health: corpus size, last build, stream,
                        providers, AI availability
``POST /refresh``       fetch real news, store it, rebuild the feed, optionally
                        run market-impact analysis
``GET  /feed``          the breaking feed for a window (the main endpoint)
``GET  /breaking``      only BREAKING-level events from the last few hours
``GET  /digest``        polling fallback: compact snapshot + content ``etag``
``GET  /clusters``      the deduplicated event clusters the feed is built from
``GET  /topics``        hot topics, ranked by the transparent trend score
``GET  /topics/{id}``   topic detail: timeline, articles, impacts, sources
``GET  /topics/{id}/timeline`` / ``/topics/{id}/articles``
``POST /impact``        observed movement for one event/entity across windows
``GET  /impact/study``  observed-movement event study over stored rows
``GET  /impact/entity/{entity}``
``GET  /impact/{news_id}/windows``  every window that has enough real data
``POST /probability``   observed Phase 14 probability movement
``GET  /probability/{market_id}``
``GET  /sources``       publisher reliability, health and registry
``GET  /stream``        Server-Sent Events
``WS   /ws``            WebSocket
``GET  /{news_id}``     one event, including its corroborating coverage
``POST /{news_id}/summary``  grounded, clearly-labelled AI summary
======================  =======================================================

Static paths are declared before ``/{news_id}`` on purpose: FastAPI resolves
routes in declaration order, so a parameterised route declared first would
swallow ``/topics`` and friends.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..logging_config import get_logger
from ..models import NewsArticle
from ..news_service import data_mode_for, get_news_service
from .config import breaking_news_settings
from .engine import engine
from .impact_stats import build_impact_study
from .models.models import (
    BreakingNews,
    MarketImpactEvent,
    NewsTopic,
    ProbabilityMovement,
    TopicTimeline,
)
from .schemas import (
    BreakingFeedMeta,
    BreakingFeedResponse,
    BreakingLevel,
    BreakingNewsSchema,
    ClusterSchema,
    ImpactStudyResponse,
    IngestReportSchema,
    ImpactWindowAnalysis,
    MarketImpactEventSchema,
    MarketImpactRequest,
    NewsTopicSchema,
    ProbabilityMovementRequest,
    ProbabilityMovementSchema,
    SourceMetadataSchema,
    SourcesResponse,
    TopicArticleSchema,
    TopicDetailResponse,
    TopicTimelineSchema,
    TopicsResponse,
)
from .sources import list_source_metadata, source_summary
from .stream import stream_manager
from .timeutil import ensure_aware, iso, to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.routes")

router = APIRouter(prefix="/api/breaking-news", tags=["breaking-news"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# serialization helpers
# ---------------------------------------------------------------------------

def _time_ago(published_at: Optional[datetime]) -> Optional[str]:
    """Display label derived from the publisher's own timestamp.

    Deliberately computed here (not stored): it must be relative to *now* every
    time the feed is read, and it must never be derived from the fetch time.
    """
    published = ensure_aware(published_at)
    if published is None:
        return None
    seconds = (utcnow().replace(tzinfo=published.tzinfo) - published).total_seconds()
    if seconds < 0:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def serialize_breaking(row: BreakingNews) -> BreakingNewsSchema:
    return BreakingNewsSchema(
        id=row.id,
        article_id=row.article_id,
        article_url=row.article_url,
        title=row.title,
        publisher=row.publisher,
        published_at=ensure_aware(row.published_at),
        url=row.url,
        image=row.image,
        excerpt=row.excerpt,
        category=row.category,
        source=row.source,
        data_mode=row.data_mode or "UNKNOWN",
        breaking_score=row.breaking_score,
        breaking_level=row.breaking_level,
        entity_importance=row.entity_importance,
        mention_velocity=row.mention_velocity,
        topic_acceleration=row.topic_acceleration,
        source_reliability=row.source_reliability,
        score_components=row.score_components or None,
        score_weights=row.score_weights or None,
        cluster_id=row.cluster_id,
        cluster_size=row.cluster_size or 1,
        related_articles=[aid for aid in (row.related_articles or []) if isinstance(aid, int)],
        affected_entities=row.affected_entities or [],
        affected_indices=row.affected_indices or [],
        topics=row.topics or [],
        market_associations=row.market_associations or {},
        impact_detected=bool(row.impact_detected),
        impact_data=row.impact_data,
        ai_summary=row.ai_summary,
        ai_summary_model=row.ai_summary_model,
        ai_summary_generated_at=ensure_aware(row.ai_summary_generated_at),
        ai_summary_is_ai_generated=bool(row.ai_summary),
        time_ago=_time_ago(row.published_at),
        created_at=ensure_aware(row.created_at),
        updated_at=ensure_aware(row.updated_at),
    )


def _feed_meta(bundle, rows: list[BreakingNews]) -> BreakingFeedMeta:
    levels = [row.breaking_level for row in rows]
    return BreakingFeedMeta(
        hours=bundle.hours,
        min_score=bundle.min_score,
        generated_at=ensure_aware(bundle.generated_at) or utcnow(),
        total_events=len(rows),
        breaking_count=levels.count("BREAKING"),
        significant_count=levels.count("SIGNIFICANT"),
        articles_analyzed=bundle.articles_analyzed,
        clusters_found=bundle.clusters_found,
        sources_consulted=bundle.sources_consulted,
        providers=bundle.provider_reports,
    )


# ---------------------------------------------------------------------------
# health / operations
# ---------------------------------------------------------------------------

@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Honest subsystem status — counts are read from the real tables."""
    corpus_window = utcnow() - timedelta(hours=int(breaking_news_settings.recency_window_hours))
    try:
        corpus = (
            db.query(NewsArticle)
            .filter(NewsArticle.published_at >= corpus_window)
            .count()
        )
        events = db.query(BreakingNews).count()
        topics = db.query(NewsTopic).count()
        impacts = db.query(MarketImpactEvent).count()
        movements = db.query(ProbabilityMovement).count()
        db_status = "ok"
    except Exception as exc:
        corpus = events = topics = impacts = movements = 0
        db_status = f"error: {exc}"

    return {
        "status": "ok",
        "phase": 17,
        "database": db_status,
        "corpus_articles_24h": corpus,
        "breaking_events": events,
        "topics": topics,
        "market_impact_events": impacts,
        "probability_movements": movements,
        "last_build_at": iso(engine.last_build_at),
        "last_build_stats": engine.last_build_stats,
        "last_ingest_report": engine.last_ingest_report,
        "stream": stream_manager.stats(),
        "providers_configured": engine.manager is not None,
        "ai_summarization": {
            "enabled": bool(breaking_news_settings.enable_ai_summarization),
            "available": engine.summarizer.available,
            "min_score": breaking_news_settings.ai_summary_min_score,
        },
        "observation_windows": list(breaking_news_settings.observation_windows),
        "settings": {
            "breaking_threshold": breaking_news_settings.breaking_threshold,
            "significant_threshold": breaking_news_settings.significant_threshold,
            "detection_weights": breaking_news_settings.detection_weights,
            "topic_trend_weights": breaking_news_settings.topic_trend_weights,
        },
        "generated_at": utcnow().isoformat(),
    }


@router.post("/refresh", response_model=IngestReportSchema)
async def refresh(
    live: bool = Query(default=True, description="Fetch live publisher feeds before rebuilding."),
    region: Optional[str] = Query(default=None),
    analyze_impacts: bool = Query(default=False, description="Also run market-impact analysis for top events."),
    db: Session = Depends(get_db),
):
    """Ingest real news and rebuild the breaking feed.

    Everything is isolated: with one provider down the response still reports the
    per-provider outcome and the events built from whatever did arrive.
    """
    try:
        report = await engine.ingest(db, region=region, live=live, analyze_impacts=analyze_impacts)
    except Exception as exc:
        logger.exception("breaking-news refresh failed")
        raise HTTPException(status_code=502, detail=f"Breaking-news refresh failed: {exc}") from exc

    await stream_manager.push_events([{"id": row.id} for row in engine.feed_query(db, hours=24)][:5])
    return report


# ---------------------------------------------------------------------------
# feed
# ---------------------------------------------------------------------------

@router.get("/feed", response_model=BreakingFeedResponse)
async def feed(
    hours: int = Query(default=24, ge=1, le=168),
    min_score: float = Query(default=0, ge=0, le=100),
    level: Optional[BreakingLevel] = None,
    category: Optional[str] = None,
    entity: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    rebuild: bool = Query(default=False, description="Force a rebuild before reading."),
    db: Session = Depends(get_db),
):
    """The breaking feed for the last ``hours``.

    Ordering is by breaking score, not by "most recently ingested", and every
    row's ``time_ago`` comes from the publisher's timestamp.
    """
    try:
        bundle = await engine.ensure_fresh(db, hours=hours, force=rebuild)
        bundle.min_score = min_score
        rows = engine.feed_query(
            db,
            hours=hours,
            min_score=min_score,
            level=level.value if level else None,
            category=category,
            entity=entity,
            limit=limit,
        )
        return BreakingFeedResponse(
            items=[serialize_breaking(row) for row in rows],
            meta=_feed_meta(bundle, rows),
        )
    except Exception as exc:
        logger.exception("breaking-news feed failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/breaking", response_model=BreakingFeedResponse)
async def breaking_only(
    hours: int = Query(default=6, ge=1, le=24),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Only the highest-severity events (BREAKING level)."""
    bundle = await engine.ensure_fresh(db, hours=max(hours, 24))
    rows = engine.feed_query(db, hours=hours, level="BREAKING", limit=limit)
    bundle.hours = hours
    return BreakingFeedResponse(items=[serialize_breaking(r) for r in rows], meta=_feed_meta(bundle, rows))


@router.get("/digest")
async def digest(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=15, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Polling fallback: compact snapshot with a content ``etag``.

    A client polls this and re-renders only when the etag changes — which is the
    same contract the streaming transports use, so behaviour is consistent
    whichever transport is available.
    """
    return await build_snapshot(db, hours=hours, limit=limit)


@router.get("/clusters", response_model=list[ClusterSchema])
async def clusters(
    hours: int = Query(default=24, ge=1, le=168),
    min_size: int = Query(default=1, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """The deduplicated event groups the feed is built from.

    Exposed so a reader can see *why* five headlines became one story.
    """
    await engine.ensure_fresh(db, hours=hours)
    rows = engine.feed_query(db, hours=hours, limit=breaking_news_settings.feed_max_items)

    grouped: dict[str, list[BreakingNews]] = {}
    for row in rows:
        grouped.setdefault(row.cluster_id or row.id, []).append(row)

    out: list[ClusterSchema] = []
    for cluster_id, members in grouped.items():
        if len(members) < min_size:
            continue
        best = max(members, key=lambda r: r.breaking_score or 0)
        first = min((r.published_at for r in members if r.published_at), default=None)
        last = max((r.published_at for r in members if r.published_at), default=None)
        span = ((last - first).total_seconds() / 3600.0) if first and last else 0.0
        article_ids = sorted({
            aid for r in members for aid in ([r.article_id] + list(r.related_articles or []))
            if isinstance(aid, int)
        })
        associations = best.market_associations or {}
        out.append(ClusterSchema(
            cluster_id=cluster_id,
            canonical_article_id=best.article_id,
            title=best.title,
            publisher=best.publisher,
            cluster_size=best.cluster_size or len(members),
            publishers=list(dict.fromkeys(r.publisher for r in members)),
            article_ids=article_ids,
            first_seen=ensure_aware(first),
            last_seen=ensure_aware(last),
            time_span_hours=round(span, 4),
            symbols=best.affected_entities or [],
            terms=list(associations.get("terms") or []),
        ))

    out.sort(key=lambda c: (-c.cluster_size, -(c.last_seen.timestamp() if c.last_seen else 0)))
    return out


# ---------------------------------------------------------------------------
# topics
# ---------------------------------------------------------------------------

@router.get("/topics", response_model=TopicsResponse)
async def topics(
    limit: int = Query(default=20, ge=1, le=100),
    min_trend_score: float = Query(default=0, ge=0, le=100),
    category: Optional[str] = None,
    topic_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Hot topics ranked by the transparent trend score.

    Every topic carries ``trend_components`` and ``trend_weights``, so the
    ranking can be reproduced by hand. No monetary volume is ever shown: no
    source in this app supplies one.
    """
    await engine.ensure_fresh(db, hours=24)
    query = db.query(NewsTopic).filter(NewsTopic.trend_score >= min_trend_score)
    if category:
        query = query.filter(NewsTopic.category == category)
    if topic_type:
        query = query.filter(NewsTopic.topic_type == topic_type.upper())
    rows = (
        query.order_by(NewsTopic.trend_score.desc(), NewsTopic.last_seen.desc())
        .limit(limit)
        .all()
    )
    return TopicsResponse(
        topics=[NewsTopicSchema.model_validate(row) for row in rows],
        meta={
            "count": len(rows),
            "min_trend_score": min_trend_score,
            "trend_weights": breaking_news_settings.topic_trend_weights,
            "generated_at": utcnow().isoformat(),
            "note": (
                "Trend scores are computed from real mention counts, source counts, "
                "recency and market-linked coverage. No invented volume figures."
            ),
        },
    )


@router.get("/topics/{topic_id}/timeline", response_model=list[TopicTimelineSchema])
def topic_timeline(
    topic_id: str,
    hours: int = Query(default=168, ge=1, le=720),
    db: Session = Depends(get_db),
):
    topic = _require_topic(db, topic_id)
    cutoff = utcnow() - timedelta(hours=hours)
    rows = (
        db.query(TopicTimeline)
        .filter(TopicTimeline.topic_id == topic.id, TopicTimeline.timestamp >= cutoff)
        .order_by(TopicTimeline.timestamp.asc())
        .all()
    )
    return [TopicTimelineSchema.model_validate(row) for row in rows]


@router.get("/topics/{topic_id}/articles", response_model=list[TopicArticleSchema])
def topic_articles(
    topic_id: str,
    hours: int = Query(default=72, ge=1, le=720),
    limit: int = Query(default=40, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Real articles behind a topic, matched on the topic's own evidence."""
    topic = _require_topic(db, topic_id)
    return [_topic_article_schema(article) for article in _topic_article_rows(db, topic, hours, limit)]


@router.get("/topics/{topic_id}", response_model=TopicDetailResponse)
def topic_detail(
    topic_id: str,
    hours: int = Query(default=72, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """Everything the topic page needs in one call."""
    topic = _require_topic(db, topic_id)
    cutoff = utcnow() - timedelta(hours=hours)

    timeline = (
        db.query(TopicTimeline)
        .filter(TopicTimeline.topic_id == topic.id, TopicTimeline.timestamp >= cutoff)
        .order_by(TopicTimeline.timestamp.asc())
        .limit(500)
        .all()
    )
    articles = _topic_article_rows(db, topic, hours, 40)
    impacts = (
        db.query(MarketImpactEvent)
        .filter(MarketImpactEvent.news_published_at >= cutoff)
        .filter(MarketImpactEvent.entity.in_(topic.related_stocks or ["__none__"]))
        .order_by(MarketImpactEvent.news_published_at.desc())
        .limit(20)
        .all()
    )

    return TopicDetailResponse(
        topic=NewsTopicSchema.model_validate(topic),
        timeline=[TopicTimelineSchema.model_validate(row) for row in timeline],
        articles=[_topic_article_schema(article) for article in articles],
        impact_events=[MarketImpactEventSchema.model_validate(row) for row in impacts],
        sources=sorted({(a.publisher or "Unknown publisher") for a in articles}),
        generated_at=utcnow(),
    )


def _require_topic(db: Session, topic_id: str) -> NewsTopic:
    topic = (
        db.query(NewsTopic)
        .filter((NewsTopic.id == topic_id) | (NewsTopic.normalized_name == topic_id))
        .first()
    )
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    return topic


def _topic_article_rows(db: Session, topic: NewsTopic, hours: int, limit: int) -> list[NewsArticle]:
    """Articles that genuinely carry the topic, not merely a keyword overlap.

    The topic's own stored evidence decides: its sample article ids first, then a
    match on its related symbols / indices / keywords. This keeps a topic page
    from pulling in unrelated coverage.
    """
    cutoff = utcnow() - timedelta(hours=hours)
    rows: list[NewsArticle] = []
    seen: set[int] = set()

    sample_ids = [aid for aid in (topic.sample_article_ids or []) if isinstance(aid, int)]
    if sample_ids:
        for article in (
            db.query(NewsArticle)
            .filter(NewsArticle.id.in_(sample_ids), NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .all()
        ):
            rows.append(article)
            seen.add(article.id)

    needle = topic.topic_name.replace("_", " ").strip()
    if needle and len(rows) < limit:
        candidates = (
            db.query(NewsArticle)
            .filter(NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .limit(400)
            .all()
        )
        lowered = needle.lower()
        for article in candidates:
            if article.id in seen or len(rows) >= limit:
                continue
            haystack = f"{article.title or ''} {article.excerpt or ''}".lower()
            symbols = {s.upper() for s in (article.related_symbols or [])}
            if lowered in haystack or needle.upper() in symbols:
                rows.append(article)
                seen.add(article.id)

    rows.sort(key=lambda a: (a.published_at is None, -(a.published_at.timestamp() if a.published_at else 0)))
    return rows[:limit]


def _topic_article_schema(article: NewsArticle) -> TopicArticleSchema:
    published = ensure_aware(article.published_at)
    return TopicArticleSchema(
        id=article.id,
        title=article.title,
        publisher=article.publisher,
        published_at=published,
        url=article.source_url,
        excerpt=article.excerpt,
        impact_score=article.impact_score,
        event_type=article.event_type,
        symbols=list(article.related_symbols or []),
        data_mode=data_mode_for(published) if published else "UNKNOWN",
    )


# ---------------------------------------------------------------------------
# market impact
# ---------------------------------------------------------------------------

@router.post("/impact", response_model=ImpactWindowAnalysis)
async def analyze_impact(request: MarketImpactRequest, db: Session = Depends(get_db)):
    """Observed movement for one event/entity, window by window.

    A window is returned only when real timestamped bars exist on both sides of
    publication; the rest are listed in ``unavailable_windows`` with the reason
    recorded on the row's ``notes``.
    """
    row = _resolve_event(db, article_id=request.article_id, url=request.url, required=False)
    # An explicit timestamp is a first-class anchor: it lets a caller measure an
    # ad-hoc entity/window pair with no stored event behind it.
    published = to_naive_utc(request.published_at)
    entity = request.entity
    entity_type = request.entity_type

    if row is not None:
        published = row.published_at
        if not entity:
            targets = engine._impact_targets(row)
            if not targets:
                raise HTTPException(
                    status_code=422,
                    detail="This event has no validated market entity to analyse. Pass ?entity= explicitly.",
                )
            entity, entity_type = targets[0]
    elif request.article_id or request.url:
        article = _find_article(db, article_id=request.article_id, url=request.url)
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found.")
        published = article.published_at
        if not entity:
            entity = next(iter(article.related_symbols or []), None)
            if not entity:
                raise HTTPException(
                    status_code=422,
                    detail="This article has no validated market entity; pass ?entity= explicitly.",
                )

    if published is None:
        raise HTTPException(
            status_code=422,
            detail="Provide article_id, url or published_at so the observation window has a real anchor.",
        )
    if not entity:
        raise HTTPException(status_code=422, detail="Provide an entity (ticker, index or asset name).")

    fetcher = engine.history_fetcher
    if fetcher is None:
        raise HTTPException(status_code=503, detail="Market data provider is not configured for this process.")

    analysis = await engine.impact_analyzer.analyze_all_windows(
        published_at=published,
        entity=entity,
        entity_type=entity_type,
        fetcher=fetcher,
        windows=[request.observation_window] if request.observation_window else None,
    )
    windows = [MarketImpactEventSchema(**result) for result in analysis["windows"]]
    return ImpactWindowAnalysis(
        entity=analysis["entity"],
        entity_type=analysis["entity_type"],
        news_published_at=ensure_aware(analysis["news_published_at"]),
        windows=windows,
        unavailable_windows=analysis["unavailable_windows"],
    )


@router.get("/impact/study", response_model=ImpactStudyResponse)
def impact_study(
    hours: int = Query(default=168, ge=1, le=720),
    window: Optional[str] = Query(default=None, pattern="^(5m|15m|30m|1h|4h|24h)$"),
    entity_type: Optional[str] = Query(
        default=None,
        pattern="^(STOCK|INDEX|COMMODITY|FOREX|CRYPTO|FORECAST)$",
    ),
    min_sample: Optional[int] = Query(default=None, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Observed-movement event study over the stored impact rows.

    Pure aggregation of rows the desk has already measured — no provider calls,
    no network, and no value that is not a statistic over real stored movements.
    Groups whose measured sample is below ``min_sample`` come back with
    ``sufficient_sample: false`` so the caller can say "not enough observations"
    instead of showing a confident average built from two data points.
    """
    cutoff = utcnow() - timedelta(hours=hours)
    query = db.query(MarketImpactEvent).filter(MarketImpactEvent.news_published_at >= cutoff)
    if window:
        query = query.filter(MarketImpactEvent.observation_window == window)
    if entity_type:
        query = query.filter(MarketImpactEvent.entity_type == entity_type.upper())

    try:
        rows = query.limit(int(breaking_news_settings.impact_study_max_rows)).all()
    except Exception as exc:
        logger.exception("impact study query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ImpactStudyResponse(
        **build_impact_study(
            rows,
            hours=hours,
            min_sample=min_sample,
            window=window,
            entity_type=entity_type.upper() if entity_type else None,
        )
    )


@router.get("/impact/entity/{entity}", response_model=list[MarketImpactEventSchema])
def entity_impact_history(
    entity: str,
    hours: int = Query(default=168, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Every observed impact event recorded for one entity."""
    cutoff = utcnow() - timedelta(hours=hours)
    rows = (
        db.query(MarketImpactEvent)
        .filter(MarketImpactEvent.entity == entity.strip().upper(), MarketImpactEvent.news_published_at >= cutoff)
        .order_by(MarketImpactEvent.news_published_at.desc())
        .limit(limit)
        .all()
    )
    return [MarketImpactEventSchema.model_validate(row) for row in rows]


@router.get("/impact/{news_id}/windows", response_model=ImpactWindowAnalysis)
async def event_impact_windows(
    news_id: str,
    entity: Optional[str] = None,
    entity_type: str = Query(default="AUTO"),
    window: Optional[str] = Query(default=None, pattern="^(5m|15m|30m|1h|4h|24h)$"),
    db: Session = Depends(get_db),
):
    """Every observation window that holds enough real data for this event."""
    row = _require_event(db, news_id)
    fetcher = engine.history_fetcher
    if fetcher is None:
        raise HTTPException(status_code=503, detail="Market data provider is not configured for this process.")

    target = entity
    kind = entity_type
    if not target:
        targets = engine._impact_targets(row)
        if not targets:
            raise HTTPException(status_code=422, detail="This event has no validated market entity; pass ?entity=.")
        target, kind = targets[0]

    analysis = await engine.impact_analyzer.analyze_all_windows(
        published_at=row.published_at,
        entity=target,
        entity_type=kind,
        fetcher=fetcher,
        windows=[window] if window else None,
    )
    return ImpactWindowAnalysis(
        entity=analysis["entity"],
        entity_type=analysis["entity_type"],
        news_published_at=ensure_aware(analysis["news_published_at"]),
        windows=[MarketImpactEventSchema(**result) for result in analysis["windows"]],
        unavailable_windows=analysis["unavailable_windows"],
    )


# ---------------------------------------------------------------------------
# probability movement (Phase 14)
# ---------------------------------------------------------------------------

@router.post("/probability", response_model=list[ProbabilityMovementSchema])
async def probability_movement(request: ProbabilityMovementRequest, db: Session = Depends(get_db)):
    """Observed probability movement for a Phase 14 market around an event."""
    if not breaking_news_settings.probability_movement_enabled:
        raise HTTPException(status_code=503, detail="Probability movement analysis is disabled.")

    if request.market_id:
        from ..forecast_markets import fetch_market_by_id
        from .market_impact import ProbabilityMovementAnalyzer

        # The observation window is anchored on a real publication time, so the
        # anchor is validated before any provider call: a request that can never
        # be answered must not cost a network round-trip (or leak a 500 from a
        # provider outage in place of an honest 422).
        published = None
        if request.article_id:
            article = _find_article(db, article_id=request.article_id)
            published = article.published_at if article else None
        if published is None:
            raise HTTPException(status_code=422, detail="Provide article_id so the movement window is anchored.")

        market = await fetch_market_by_id(request.market_id, 15.0)
        if market is None:
            raise HTTPException(status_code=404, detail="Forecast market not found.")

        analyzer = ProbabilityMovementAnalyzer(breaking_news_settings)
        analysis = await analyzer.analyze_market(
            market=market,
            published_at=published,
            observation_window=request.observation_window,
        )
        if analysis is None:
            return []
        return [ProbabilityMovementSchema(
            id="adhoc",
            market_id=analysis["market_id"],
            market_name=analysis.get("market_name"),
            market_url=analysis.get("market_url"),
            news_published_at=ensure_aware(analysis["news_published_at"]),
            observation_window=analysis["observation_window"],
            probability_before=analysis.get("probability_before"),
            probability_after=analysis.get("probability_after"),
            probability_change=analysis.get("probability_change"),
            movement_direction=analysis.get("movement_direction"),
            impact_magnitude=analysis.get("impact_magnitude"),
            source_name=analysis.get("source_name"),
            source_url=analysis.get("source_url"),
            series=analysis.get("series") or [],
        )]

    row = _resolve_event(db, article_id=request.article_id, url=None, required=True)
    written = await engine.analyze_probability(db, row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [ProbabilityMovementSchema.model_validate(m) for m in written]


@router.get("/probability/{market_id}", response_model=list[ProbabilityMovementSchema])
def market_probability_history(
    market_id: str,
    hours: int = Query(default=168, ge=1, le=720),
    db: Session = Depends(get_db),
):
    cutoff = utcnow() - timedelta(hours=hours)
    rows = (
        db.query(ProbabilityMovement)
        .filter(ProbabilityMovement.market_id == market_id, ProbabilityMovement.news_published_at >= cutoff)
        .order_by(ProbabilityMovement.news_published_at.desc())
        .limit(100)
        .all()
    )
    return [ProbabilityMovementSchema.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

@router.get("/sources", response_model=SourcesResponse)
def sources(db: Session = Depends(get_db)):
    """Publisher reliability + real feed health from the last ingest."""
    rows = list_source_metadata(db)
    feed_health = get_news_service().source_status()
    return SourcesResponse(
        sources=[SourceMetadataSchema.model_validate(row) for row in rows],
        summary=source_summary(rows),
        feed_health=feed_health,
        generated_at=utcnow(),
    )


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------

async def _sse_generator(client_id: str):
    """Yield SSE frames for one client until it disconnects."""
    client = stream_manager.register(client_id, "sse")
    try:
        initial = await build_snapshot()
        yield f"event: snapshot\ndata: {json.dumps(initial, default=str)}\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(client.queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                stream_manager.touch(client_id)
                yield ": keep-alive\n\n"
                continue
            stream_manager.touch(client_id)
            event = payload.get("type", "message")
            yield f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"
    except asyncio.CancelledError:  # client went away
        raise
    finally:
        stream_manager.unregister(client_id)


@router.get("/stream")
async def sse_stream():
    """Server-Sent Events stream of breaking-news digests."""
    if not breaking_news_settings.enable_sse:
        raise HTTPException(status_code=503, detail="SSE streaming is disabled.")
    await stream_manager.start()
    client_id = f"sse-{utcnow().timestamp()}-{id(object())}"
    return StreamingResponse(
        _sse_generator(client_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket stream: snapshots, heartbeats, and client ping/pong."""
    await websocket.accept()
    await stream_manager.start()
    client_id = f"ws-{utcnow().timestamp()}-{id(websocket)}"
    client = stream_manager.register(client_id, "websocket")

    try:
        snapshot = await build_snapshot()
        await websocket.send_json({
            "type": "snapshot",
            "generated_at": snapshot.get("generated_at"),
            "data": snapshot,
        })

        while True:
            try:
                payload = await asyncio.wait_for(client.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                stream_manager.touch(client_id)
                await websocket.send_json({"type": "heartbeat", "generated_at": utcnow().isoformat()})
                continue

            await websocket.send_json(payload)
            stream_manager.touch(client_id)
            # Opportunistically read a client ping without ever blocking the loop.
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=0.01)
                if isinstance(message, dict) and message.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "generated_at": utcnow().isoformat()})
            except (asyncio.TimeoutError, ValueError):
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - transport level
        logger.debug("websocket error for %s: %s", client_id, exc)
    finally:
        stream_manager.unregister(client_id)


# ---------------------------------------------------------------------------
# snapshot (shared by WebSocket, SSE and the polling digest)
# ---------------------------------------------------------------------------

async def build_snapshot(db: Optional[Session] = None, *, hours: int = 24, limit: int = 15) -> dict:
    """Compact, side-effect-free digest of the current breaking desk."""
    own_session = db is None
    session = db or SessionLocal()
    try:
        bundle = await engine.ensure_fresh(session, hours=hours)
        rows = engine.feed_query(session, hours=hours, limit=limit)
        topic_rows = (
            session.query(NewsTopic)
            .order_by(NewsTopic.trend_score.desc(), NewsTopic.last_seen.desc())
            .limit(10)
            .all()
        )
        snapshot = {
            "generated_at": utcnow().isoformat(),
            "hours": hours,
            "events": [
                {
                    "id": row.id,
                    "title": row.title,
                    "publisher": row.publisher,
                    "published_at": iso(row.published_at),
                    "time_ago": _time_ago(row.published_at),
                    "url": row.url,
                    "image": row.image,
                    "breaking_score": row.breaking_score,
                    "breaking_level": row.breaking_level,
                    "cluster_size": row.cluster_size,
                    "affected_entities": row.affected_entities or [],
                    "data_mode": row.data_mode,
                    "ai_summary": bool(row.ai_summary),
                }
                for row in rows
            ],
            "topics": [
                {
                    "id": row.id,
                    "topic_name": row.topic_name,
                    "trend_score": row.trend_score,
                    "trend_direction": row.trend_direction,
                    "mention_count": row.mention_count,
                    "source_count": row.source_count,
                    "related_stocks": row.related_stocks or [],
                }
                for row in topic_rows
            ],
            "counts": {
                "events": len(rows),
                "breaking": sum(1 for r in rows if r.breaking_level == "BREAKING"),
                "significant": sum(1 for r in rows if r.breaking_level == "SIGNIFICANT"),
            },
            "meta": {
                "articles_analyzed": bundle.articles_analyzed,
                "clusters_found": bundle.clusters_found,
                "articles_analyzed_corpus": bundle.articles_analyzed,
            },
        }
        return snapshot
    finally:
        if own_session:
            session.close()


# ---------------------------------------------------------------------------
# event detail (declared last so it cannot swallow the static routes above)
# ---------------------------------------------------------------------------

@router.get("/{news_id}", response_model=BreakingNewsSchema)
def event_detail(news_id: str, db: Session = Depends(get_db)):
    row = _require_event(db, news_id)
    payload = serialize_breaking(row)
    payload.market_associations = {
        **(row.market_associations or {}),
        "corroborating_coverage": engine.related_articles(db, row),
    }
    return payload


@router.post("/{news_id}/summary")
async def event_summary(news_id: str, force: bool = Query(default=False), db: Session = Depends(get_db)):
    """Grounded, clearly-labelled AI summary for one event."""
    row = _require_event(db, news_id)
    if row.ai_summary and not force:
        return {
            "status": "CACHED",
            "summary": row.ai_summary,
            "model": row.ai_summary_model,
            "generated_at": iso(row.ai_summary_generated_at),
            "is_ai_generated": True,
            "label": "AI-generated summary — verify against the source article.",
        }
    return await engine.summarize(db, row)


# ---------------------------------------------------------------------------
# small resolvers
# ---------------------------------------------------------------------------

def _require_event(db: Session, news_id: str) -> BreakingNews:
    row = db.query(BreakingNews).filter(BreakingNews.id == news_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Breaking news event not found.")
    return row


def _find_article(db: Session, *, article_id: Optional[int] = None, url: Optional[str] = None) -> Optional[NewsArticle]:
    if article_id is not None:
        article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
        if article is not None:
            return article
    if url:
        return db.query(NewsArticle).filter(NewsArticle.source_url == url).first()
    return None


def _resolve_event(
    db: Session,
    *,
    article_id: Optional[int],
    url: Optional[str],
    required: bool,
) -> Optional[BreakingNews]:
    query = db.query(BreakingNews)
    if article_id is not None:
        row = query.filter(BreakingNews.article_id == article_id).first()
        if row is not None:
            return row
    if url:
        row = query.filter(BreakingNews.url == url).first()
        if row is not None:
            return row
    if required:
        raise HTTPException(status_code=404, detail="No breaking-news event is linked to that article.")
    return None


__all__ = ["router", "build_snapshot", "serialize_breaking", "get_db"]
