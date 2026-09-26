"""
Persistence for Phase 19 discovery — real observations and real interest.

Two tables (``app.models``):

``TrendObservation``
    {timestamp, activity, score} sampled from an actually-computed feed. This
    is the only history sparklines ever draw from.

``DiscoveryEvent``
    One row per recorded view / search match. Interest scores are literally
    ``COUNT(*)`` over these rows — an app with no traffic shows 0, which is
    the truth, not a placeholder.

Everything here is best-effort: a database hiccup must degrade discovery (no
history, no interest counts) rather than break the endpoint, so each helper
catches and logs instead of raising, and returns an empty result.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func

from ..logging_config import get_logger
from ..models import DiscoveryEvent, TrendObservation, WatchlistItem

logger = get_logger("neural_market.discovery.store")

#: Real interest event kinds (the only two that exist — no synthetic kinds).
KIND_VIEW = "view"
KIND_SEARCH = "search"
VALID_KINDS = (KIND_VIEW, KIND_SEARCH)

_last_prune: float = 0.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    """SQLite stores naive datetimes; always convert before writing."""
    return value.replace(tzinfo=None) if value.tzinfo else value


# --------------------------------------------------------------------------- events
def record_event(entity_id: str, kind: str = KIND_VIEW) -> bool:
    """Store one real interest event. Returns False when it could not be stored."""
    if not entity_id or kind not in VALID_KINDS:
        return False
    try:
        from ..db import session_scope

        with session_scope() as db:
            db.add(DiscoveryEvent(entity_id=str(entity_id)[:120], kind=kind, occurred_at=_naive_utc(_utcnow())))
        return True
    except Exception as exc:
        logger.debug("discovery event not recorded (%s/%s): %s", entity_id, kind, exc)
        return False


def record_events(entity_ids: Iterable[str], kind: str = KIND_SEARCH) -> int:
    """Store several real events in one transaction (search-result matches)."""
    ids = [str(e)[:120] for e in dict.fromkeys(entity_ids) if e]
    if not ids or kind not in VALID_KINDS:
        return 0
    try:
        from ..db import session_scope

        now = _naive_utc(_utcnow())
        with session_scope() as db:
            for entity_id in ids:
                db.add(DiscoveryEvent(entity_id=entity_id, kind=kind, occurred_at=now))
        return len(ids)
    except Exception as exc:
        logger.debug("discovery events not recorded: %s", exc)
        return 0


def interest_counts(entity_ids: Sequence[str]) -> Dict[str, Dict[str, int]]:
    """``{entity_id: {"view": n, "search": m, "total": n+m}}`` — real counts."""
    result: Dict[str, Dict[str, int]] = {eid: {"view": 0, "search": 0, "total": 0} for eid in entity_ids}
    if not entity_ids:
        return result
    try:
        from ..db import session_scope

        with session_scope() as db:
            rows = (
                db.query(DiscoveryEvent.entity_id, DiscoveryEvent.kind, func.count(DiscoveryEvent.id))
                .filter(DiscoveryEvent.entity_id.in_(list(entity_ids)))
                .group_by(DiscoveryEvent.entity_id, DiscoveryEvent.kind)
                .all()
            )
        for entity_id, kind, count in rows:
            bucket = result.setdefault(str(entity_id), {"view": 0, "search": 0, "total": 0})
            bucket[kind if kind in bucket else "search"] = int(count)
            bucket["total"] += int(count)
        return result
    except Exception as exc:
        logger.debug("interest counts unavailable: %s", exc)
        return result


def watchlist_entity_ids() -> Dict[str, int]:
    """``{entity_id: 1}`` for stocks the user actually saved (real watchlist)."""
    try:
        from ..db import session_scope

        with session_scope() as db:
            tickers = [row[0] for row in db.query(WatchlistItem.ticker).all()]
        return {f"stock:{str(t).upper()}": 1 for t in tickers if t}
    except Exception as exc:
        logger.debug("watchlist lookup unavailable: %s", exc)
        return {}


def recently_viewed(limit: int = 50) -> List[str]:
    """Entity ids this client actually opened, most recent first, de-duplicated."""
    try:
        from ..db import session_scope

        cutoff = _naive_utc(_utcnow() - timedelta(hours=168))
        with session_scope() as db:
            rows = (
                db.query(DiscoveryEvent.entity_id, func.max(DiscoveryEvent.occurred_at))
                .filter(DiscoveryEvent.kind == KIND_VIEW, DiscoveryEvent.occurred_at >= cutoff)
                .group_by(DiscoveryEvent.entity_id)
                .order_by(func.max(DiscoveryEvent.occurred_at).desc())
                .limit(max(1, int(limit)))
                .all()
            )
        return [str(entity_id) for entity_id, _ts in rows]
    except Exception as exc:
        logger.debug("recently-viewed lookup unavailable: %s", exc)
        return []


# ------------------------------------------------------------------ observations
def last_sample_times(entity_ids: Sequence[str]) -> Dict[str, datetime]:
    """Most recent observation timestamp per entity (for sampling throttle)."""
    out: Dict[str, datetime] = {}
    if not entity_ids:
        return out
    try:
        from ..db import session_scope

        with session_scope() as db:
            rows = (
                db.query(TrendObservation.entity_id, func.max(TrendObservation.observed_at))
                .filter(TrendObservation.entity_id.in_(list(entity_ids)))
                .group_by(TrendObservation.entity_id)
                .all()
            )
        for entity_id, ts in rows:
            out[str(entity_id)] = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
        return out
    except Exception as exc:
        logger.debug("observation times unavailable: %s", exc)
        return out


def record_observations(rows: Sequence[Dict[str, Any]]) -> int:
    """Append observation rows. Each row: entity_id, activity, score, popularity.

    Callers throttle per entity via :func:`last_sample_times`; this only writes.
    """
    clean = [r for r in rows if r.get("entity_id")]
    if not clean:
        return 0
    try:
        from ..db import session_scope

        now = _naive_utc(_utcnow())
        with session_scope() as db:
            for row in clean:
                db.add(
                    TrendObservation(
                        entity_id=str(row["entity_id"])[:120],
                        observed_at=now,
                        activity=_maybe_float(row.get("activity")),
                        score=_maybe_float(row.get("score")),
                        popularity=_maybe_float(row.get("popularity")),
                        source=str(row.get("source") or "sample")[:40],
                    )
                )
        return len(clean)
    except Exception as exc:
        logger.debug("trend observations not recorded: %s", exc)
        return 0


def velocity_points(entity_ids: Sequence[str], lookback_hours: float) -> Dict[str, List[Tuple[datetime, float]]]:
    """Recent (timestamp, activity) pairs per entity — the velocity input."""
    out: Dict[str, List[Tuple[datetime, float]]] = {}
    if not entity_ids:
        return out
    try:
        from ..db import session_scope

        cutoff = _naive_utc(_utcnow() - timedelta(hours=max(lookback_hours, 0.25)))
        with session_scope() as db:
            rows = (
                db.query(TrendObservation.entity_id, TrendObservation.observed_at, TrendObservation.activity)
                .filter(
                    TrendObservation.entity_id.in_(list(entity_ids)),
                    TrendObservation.observed_at >= cutoff,
                    TrendObservation.activity.isnot(None),
                )
                .order_by(TrendObservation.observed_at.asc())
                .limit(20000)
                .all()
            )
        for entity_id, ts, activity in rows:
            if activity is None:
                continue
            out.setdefault(str(entity_id), []).append((ts, float(activity)))
        return out
    except Exception as exc:
        logger.debug("velocity points unavailable: %s", exc)
        return out


def observation_history(entity_id: str, hours: int) -> List[Dict[str, Any]]:
    """Stored {timestamp, activity, score} observations, oldest first."""
    try:
        from ..db import session_scope

        cutoff = _naive_utc(_utcnow() - timedelta(hours=max(int(hours), 1)))
        with session_scope() as db:
            rows = (
                db.query(TrendObservation)
                .filter(TrendObservation.entity_id == entity_id, TrendObservation.observed_at >= cutoff)
                .order_by(TrendObservation.observed_at.asc())
                .limit(2000)
                .all()
            )
            # Read inside the session: commit expires ORM attributes, and a
            # detached instance raises on refresh ("not bound to a Session").
            return [
                {
                    "timestamp": _iso(row.observed_at),
                    "activity": row.activity,
                    "score": row.score,
                    "popularity": row.popularity,
                    "source": row.source,
                }
                for row in rows
            ]
    except Exception as exc:
        logger.debug("observation history unavailable: %s", exc)
        return []


def news_mentions_24h() -> Dict[str, int]:
    """``{ticker: real headline count in the last 24h}`` from the news corpus."""
    try:
        from ..db import session_scope
        from ..models import NewsArticle

        cutoff = _naive_utc(_utcnow() - timedelta(hours=24))
        with session_scope() as db:
            rows = (
                db.query(NewsArticle.related_symbols)
                .filter(NewsArticle.published_at >= cutoff)
                .limit(5000)
                .all()
            )
        counts: Dict[str, int] = {}
        for (symbols,) in rows:
            for symbol in symbols or []:
                key = str(symbol).upper()
                counts[key] = counts.get(key, 0) + 1
        return counts
    except Exception as exc:
        logger.debug("news mention counts unavailable: %s", exc)
        return {}


# --------------------------------------------------------------------- pruning
def prune(force: bool = False) -> int:
    """Drop aged observation rows and aged/overflow interest events.

    Throttled to once every 10 minutes unless ``force``. Returns rows dropped.
    """
    global _last_prune
    now = time.monotonic()
    if not force and now - _last_prune < 600:
        return 0
    _last_prune = now
    dropped = 0
    try:
        from ..config import settings  # noqa: F401  (ensures app settings loaded)
        from ..db import session_scope
        from ..discovery.config import discovery_settings

        obs_cutoff = _naive_utc(_utcnow() - timedelta(hours=discovery_settings.observation_retention_hours))
        event_cutoff = _naive_utc(_utcnow() - timedelta(days=discovery_settings.event_retention_days))
        with session_scope() as db:
            dropped += (
                db.query(TrendObservation)
                .filter(TrendObservation.observed_at < obs_cutoff)
                .delete(synchronize_session=False)
            )
            dropped += (
                db.query(DiscoveryEvent)
                .filter(DiscoveryEvent.occurred_at < event_cutoff)
                .delete(synchronize_session=False)
            )
            # Bounded table size: if events grew past the cap, drop the oldest.
            total = db.query(func.count(DiscoveryEvent.id)).scalar() or 0
            overflow = int(total) - discovery_settings.event_max_rows
            if overflow > 0:
                ids = [
                    row[0]
                    for row in db.query(DiscoveryEvent.id)
                    .order_by(DiscoveryEvent.occurred_at.asc())
                    .limit(overflow)
                    .all()
                ]
                if ids:
                    dropped += (
                        db.query(DiscoveryEvent)
                        .filter(DiscoveryEvent.id.in_(ids))
                        .delete(synchronize_session=False)
                    )
    except Exception as exc:
        logger.debug("discovery prune failed: %s", exc)
    return dropped


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.isoformat()


def _maybe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


__all__ = [
    "KIND_VIEW",
    "KIND_SEARCH",
    "VALID_KINDS",
    "record_event",
    "record_events",
    "interest_counts",
    "watchlist_entity_ids",
    "recently_viewed",
    "last_sample_times",
    "record_observations",
    "velocity_points",
    "observation_history",
    "news_mentions_24h",
    "prune",
]
