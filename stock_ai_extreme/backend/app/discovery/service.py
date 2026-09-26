"""
Discovery service (spec §1–§17) — orchestration for the Phase 19 engine.

Responsibilities, in order:

1. **Collect** the entity universe once per cache window
   (:func:`app.discovery.collectors.collect`) so filters/modes never fan out
   to providers on every keystroke (spec §15: server-side caching).
2. **Enrich** with real interest counts (recorded views/searches + watchlist),
   real 24h headline mentions, and observation-based velocity.
3. **Score** through :class:`app.discovery.trend_engine.TrendEngine`, keeping
   every component visible.
4. **Rank + filter** per feed mode (trending / new / popular / recent).
5. **Sample** observations back into storage so sparklines accumulate real
   history (spec §12), throttled per entity.

Honesty rules enforced here:

    * missing signals stay missing (reported, never zero-filled);
    * a failed source shows up in ``sources`` with its reason;
    * personalization uses only explicit actions (watchlist, this client's own
      views, this client's selected categories) — nothing is inferred from
      content, and the boost is disclosed in the response.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..logging_config import get_logger
from ..providers.cache import TTLCache
from . import store
from .analytics import analyze as analyze_history
from .collectors import collect
from .config import discovery_settings
from .entities import ENTITY_TYPES, FEED_MODES
from .taxonomy import normalize_category, normalize_tag, taxonomy_from
from .trend_engine import TrendEngine, engine as trend_engine

logger = get_logger("neural_market.discovery.service")

_cache = TTLCache(default_ttl_seconds=discovery_settings.universe_cache_ttl_seconds)
_manager: Any = None

#: Honest, human-readable notes attached to every feed response.
FEED_NOTES = [
    "Every activity number is a measurement from a named source — nothing is "
    "estimated, and a metric the source does not publish shows as N/A.",
    "Trend scores aggregate only the signals available for each entity; the "
    "components, the weights used and the missing signals are returned with "
    "every item.",
    "Interest counts (views, searches, watchlist additions) are events this "
    "app actually recorded — a fresh install honestly shows zero.",
]


class DiscoveryNotConfigured(RuntimeError):
    """Raised when the provider manager has not been injected yet."""


def configure(manager: Any) -> None:
    """Bind the app's Phase 2 provider manager (called once from main.py)."""
    global _manager
    _manager = manager


def is_configured() -> bool:
    return _manager is not None


# ---------------------------------------------------------------------------
# 1–2. universe + enrichment
# ---------------------------------------------------------------------------
async def get_universe(*, force: bool = False) -> Dict[str, Any]:
    """Collected, enriched and scored entities (cached for a short window)."""
    if _manager is None:
        raise DiscoveryNotConfigured("discovery provider manager is not configured")

    if not force:
        cached = await _cache.get("universe")
        if cached is not None:
            return cached

    entities, reports = await collect(_manager)
    ids = [entity.id for entity in entities]

    interest = store.interest_counts(ids)
    watchlist = store.watchlist_entity_ids()
    viewed = set(store.recently_viewed(discovery_settings.max_recently_viewed))
    mentions = store.news_mentions_24h()
    velocity_points = store.velocity_points(ids, discovery_settings.velocity_lookback_hours)

    payloads: List[Dict[str, Any]] = []
    for entity in entities:
        signals = dict(entity.signals)

        # Real 24h headline mentions (stocks only — the only type with an
        # honest ticker link to the news corpus).
        if entity.type == "stock" and entity.symbol:
            count = mentions.get(entity.symbol.upper())
            if count is not None:
                signals["news_mentions_24h"] = count

        # Real recorded interest: views + searches + an explicit watchlist add.
        bucket = interest.get(entity.id, {"view": 0, "search": 0, "total": 0})
        in_watchlist = 1 if entity.id in watchlist else 0
        signals["interest_count"] = int(bucket.get("total", 0)) + in_watchlist

        # Velocity from this entity's own stored observations, when the
        # collector had no richer native measure (news topics ship one).
        if signals.get("velocity") is None:
            points = velocity_points.get(entity.id) or []
            if len(points) >= 2:
                velocity = TrendEngine.velocity_from_history(
                    points, lookback_hours=discovery_settings.velocity_lookback_hours
                )
                if velocity is not None:
                    signals["velocity"] = velocity
                    signals.setdefault("velocity_kind", "activity")

        scored = trend_engine.score_signals(signals)
        payload = entity.base_dict()
        payload["trend"] = scored["trend"]
        payload["popularity"] = scored["popularity"]
        payload["scoreComponents"] = scored["components"]
        payload["signals"] = signals
        payload["interest"] = {
            "view": int(bucket.get("view", 0)),
            "search": int(bucket.get("search", 0)),
            "watchlist": in_watchlist,
            "total": int(bucket.get("total", 0)) + in_watchlist,
        }
        payload["personal"] = {
            "watchlist": bool(in_watchlist),
            "recentlyViewed": entity.id in viewed,
            "preferredCategory": False,  # filled per request from `prefer`
        }
        payloads.append(payload)

    result = {
        "entities": payloads,
        "sources": reports,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    await _cache.set("universe", result, ttl_seconds=discovery_settings.universe_cache_ttl_seconds)
    return result


# ---------------------------------------------------------------------------
# 4. filtering / ranking
# ---------------------------------------------------------------------------
def _matches(
    item: Dict[str, Any],
    *,
    category: Optional[str],
    tag: Optional[str],
    entity_type: Optional[str],
    status: Optional[str],
    source: Optional[str],
    since: Optional[str],
    q: Optional[str],
) -> bool:
    if category and (item.get("category") or "").lower() != category.lower():
        return False
    if tag:
        wanted = normalize_tag(tag).lower()
        if not any(normalize_tag(t).lower() == wanted for t in item.get("tags") or []):
            return False
    if entity_type and item.get("type") != entity_type:
        return False
    if status and (item.get("status") or "").upper() != status.upper():
        return False
    if source and source.lower() not in (item.get("source") or "").lower():
        return False
    if since:
        created = item.get("createdAt")
        if not created or str(created) < since:
            return False
    if q:
        needle = q.strip().lower()
        haystack = " ".join(
            [str(item.get("name") or ""), str(item.get("symbol") or ""), " ".join(item.get("tags") or [])]
        ).lower()
        if needle not in haystack:
            return False
    return True


def _timestamp(value: Any) -> float:
    """Unix seconds for sorting; -1 when there is no real timestamp."""
    if not value:
        return -1.0
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return -1.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


async def get_feed(
    *,
    mode: str = "trending",
    category: Optional[str] = None,
    tag: Optional[str] = None,
    entity_type: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    since: Optional[str] = None,
    q: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    personalize: bool = False,
    prefer: Optional[Sequence[str]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """One discovery feed (spec §9): filter → rank → paginate → sample."""
    mode = (mode or "trending").lower()
    if mode not in FEED_MODES:
        mode = "trending"
    limit = max(1, min(int(limit or discovery_settings.feed_default_limit), discovery_settings.feed_max_limit))
    offset = max(0, int(offset))

    universe = await get_universe_and_remember(force=force)
    entities: List[Dict[str, Any]] = universe["entities"]

    preferred = {normalize_category(c) or c for c in (prefer or []) if c}
    personalize = bool(personalize and discovery_settings.personalization_enabled)

    matched: List[Dict[str, Any]] = []
    excluded_no_created = 0
    for item in entities:
        if not _matches(
            item,
            category=category, tag=tag, entity_type=entity_type, status=status,
            source=source, since=since, q=q,
        ):
            continue
        if mode == "new" and not item.get("createdAt"):
            # Spec §2: NEW shows genuine creation timestamps only.
            excluded_no_created += 1
            continue
        # Personalization: explicit signals only (watchlist / own views /
        # categories this client selected). Disclosed on the item.
        item = dict(item)
        personal = dict(item.get("personal") or {})
        personal["preferredCategory"] = bool(preferred) and item.get("category") in preferred
        item["personal"] = personal
        item["personalized"] = personalize and any(personal.values())
        matched.append(item)

    boost = discovery_settings.personalization_boost

    def _rank(item: Dict[str, Any]) -> float:
        if mode == "new":
            base = _timestamp(item.get("createdAt"))
        elif mode == "recent":
            base = _timestamp(item.get("updatedAt"))
        elif mode == "popular":
            base = item.get("popularity", {}).get("score")
            base = -1.0 if base is None else float(base)
        else:
            base = item.get("trend", {}).get("score")
            base = -1.0 if base is None else float(base)
        if personalize and item.get("personalized") and base is not None and base >= 0:
            base = base * (1.0 + boost)
        return base

    matched.sort(key=lambda item: (-_rank(item), str(item.get("name") or "")))
    total = len(matched)
    page = matched[offset : offset + limit]
    for item in page:
        rank = _rank(item)
        item["rankScore"] = round(rank, 3) if rank >= 0 else None
        item["personalBoostApplied"] = bool(
            personalize and item.get("personalized") and mode in ("trending", "popular")
        )

    # Real search activity: a returned match for a real query is a real event.
    recorded_searches = 0
    if q and page:
        recorded_searches = store.record_events([item["id"] for item in page[:limit]], store.KIND_SEARCH)

    # Real trend observations: throttled per entity, top of the ranked list.
    sampled = 0
    if mode in ("trending", "popular") and not q:
        sampled = await sample_observations(matched[: discovery_settings.observation_sample_top_k])

    return {
        "mode": mode,
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + limit < total,
        "generatedAt": universe["generatedAt"],
        "sources": universe["sources"],
        "engine": trend_engine.describe(),
        "filters": {
            "category": category, "tag": tag, "type": entity_type, "status": status,
            "source": source, "since": since, "q": q,
        },
        "personalization": {
            "enabled": personalize,
            "signals": ["watchlist", "recently_viewed", "preferred_categories"] if personalize else [],
            "boost": boost if personalize else 0,
            "note": (
                "Only explicit actions are used (watchlist additions, entities "
                "this client opened, categories this client selected). "
                "Preferences are never inferred from content."
            ),
        },
        "excludedNoCreatedAt": excluded_no_created,
        "recordedSearches": recorded_searches,
        "sampledObservations": sampled,
        "notes": FEED_NOTES,
    }


# ---------------------------------------------------------------------------
# 5. observation sampling (real history for sparklines)
# ---------------------------------------------------------------------------
async def sample_observations(items: Sequence[Dict[str, Any]]) -> int:
    """Append {timestamp, activity, score} rows for ranked entities.

    Throttled per entity by ``observation_sample_interval_seconds`` so reading
    the page repeatedly cannot spam the table.
    """
    candidates = [
        item
        for item in items
        if item.get("id") and item.get("trend", {}).get("score") is not None
    ]
    if not candidates:
        return 0
    ids = [item["id"] for item in candidates]
    last_times = store.last_sample_times(ids)
    now = datetime.now(timezone.utc)
    interval = timedelta(seconds=discovery_settings.observation_sample_interval_seconds)

    rows = []
    for item in candidates:
        previous = last_times.get(item["id"])
        if previous is not None:
            previous_aware = previous if previous.tzinfo else previous.replace(tzinfo=timezone.utc)
            if now - previous_aware < interval:
                continue
        rows.append(
            {
                "entity_id": item["id"],
                "activity": (item.get("activity") or {}).get("value"),
                "score": item.get("trend", {}).get("score"),
                "popularity": item.get("popularity", {}).get("score"),
                "source": "sample",
            }
        )
    return store.record_observations(rows)


# ---------------------------------------------------------------------------
# taxonomy / history / meta
# ---------------------------------------------------------------------------
async def get_taxonomy(*, force: bool = False) -> Dict[str, Any]:
    """Category + tag navigation built from the real entity set (spec §6, §13)."""
    universe = await get_universe(force=force)
    model = taxonomy_from(universe["entities"])
    model["generatedAt"] = universe["generatedAt"]
    model["sources"] = universe["sources"]
    model["note"] = (
        "Counts are live entity counts. Tags come from real attributes "
        "(sector groups, source categories) plus a deterministic keyword "
        "lexicon applied to names — clicking a tag filters exactly the "
        "entities that carry it."
    )
    return model


async def get_history(entity_id: str, hours: Optional[int] = None) -> Dict[str, Any]:
    """Trend history for one entity (spec §12).

    News topics have real hourly activity buckets from Phase 17 — those are
    used when they exist. Otherwise the series is the observation history this
    engine has actually sampled. With fewer than two points the analytics say
    so instead of inventing a trend.
    """
    hours = int(hours or discovery_settings.trend_history_hours)
    await get_universe_and_remember()  # keeps the entity lookup warm (and
    # re-throttles collection through the cache instead of re-fetching).
    entity_id = str(entity_id or "").strip()
    points: List[Dict[str, Any]] = []
    source_label = "sampled_observations"

    if entity_id.startswith("topic:"):
        timeline_points = _topic_timeline_points(entity_id.split(":", 1)[1], hours)
        if len(timeline_points) >= 2:
            points = timeline_points
            source_label = "news_timeline"

    if not points:
        points = store.observation_history(entity_id, hours)

    analytics = analyze_history(points)
    return {
        "entityId": entity_id,
        "entity": find_entity(entity_id),
        "hours": hours,
        "seriesSource": source_label if points else None,
        "points": points,
        "analytics": analytics,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Points are stored observations of this entity's real activity and "
            "score. Fewer than two points means history is still accumulating."
        ),
    }


def _topic_timeline_points(topic_id: str, hours: int) -> List[Dict[str, Any]]:
    """Real hourly activity buckets the Phase 17 engine already stored."""
    try:
        from ..db import session_scope
        from ..breaking_news.models.models import TopicTimeline
        from ..breaking_news.timeutil import utcnow

        cutoff = utcnow().replace(tzinfo=None) - timedelta(hours=max(hours, 1))
        with session_scope() as db:
            rows = (
                db.query(TopicTimeline)
                .filter(TopicTimeline.topic_id == topic_id, TopicTimeline.timestamp >= cutoff)
                .order_by(TopicTimeline.timestamp.asc())
                .limit(1000)
                .all()
            )
            # Read inside the session — commit expires ORM attributes, so a
            # detached row raises "not bound to a Session" when serialized.
            return [
                {
                    "timestamp": row.timestamp.replace(tzinfo=timezone.utc).isoformat()
                    if row.timestamp.tzinfo
                    else row.timestamp.isoformat(),
                    "activity": row.mention_count,
                    "score": row.trend_score,
                    "source": "news_timeline",
                }
                for row in rows
            ]
    except Exception as exc:
        logger.debug("topic timeline unavailable for %s: %s", topic_id, exc)
        return []


def find_entity(entity_id: str) -> Optional[Dict[str, Any]]:
    """Look one entity up in the last universe produced by this service.

    Callers that need the *fresh* universe must ``await get_universe()``
    first — this helper intentionally does no I/O.
    """
    universe = _last_universe
    if not universe:
        return None
    for item in universe.get("entities", []):
        if item.get("id") == entity_id:
            return item
    return None


_last_universe: Optional[Dict[str, Any]] = None


def remember_universe(universe: Dict[str, Any]) -> None:
    global _last_universe
    _last_universe = universe


async def get_universe_and_remember(*, force: bool = False) -> Dict[str, Any]:
    universe = await get_universe(force=force)
    remember_universe(universe)
    return universe


__all__ = [
    "DiscoveryNotConfigured",
    "FEED_NOTES",
    "configure",
    "is_configured",
    "get_universe",
    "get_universe_and_remember",
    "get_feed",
    "get_taxonomy",
    "get_history",
    "sample_observations",
    "find_entity",
]
