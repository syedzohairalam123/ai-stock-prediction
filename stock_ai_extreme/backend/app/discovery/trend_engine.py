"""
Trend score engine (spec §3, §4, §17).

``TrendEngine`` turns *measured* signals into a 0–100 score while keeping every
individual component separate and inspectable:

    calculate_recency_score()     age of the entity's real timestamps
    calculate_activity_score()    price/volume/participation/mention activity
    calculate_velocity_score()    rate of change of that activity
    calculate_interest_score()    real recorded interest (views/searches/
                                  watchlist additions — never simulated)
    calculate_news_score()        news breadth (distinct publishers) or
                                  24h headline mentions, where measurable
    calculate_trend_score()       weighted aggregate of the above
    calculate_popularity_score()  the POPULAR feed's interest-first aggregate

Rules:

    * A component with no measurement returns ``None``. The aggregate then
      renormalizes over the components that *are* available and reports which
      ones were missing — an entity is never punished for a signal nobody
      collects, and no missing signal is silently replaced with 0.
    * Every weight and saturation comes from
      :class:`app.discovery.config.DiscoverySettings`; nothing is hard-coded
      inside the scoring functions.
    * Scores are deterministic: same signals in, same score out.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import DiscoverySettings, discovery_settings


def _parse_ts(value: Any) -> Optional[datetime]:
    """Accept ISO strings (with/without tz) or datetimes; ``None`` otherwise."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), digits)


class TrendEngine:
    """Configurable, explainable trend/popularity scoring."""

    def __init__(self, settings: Optional[DiscoverySettings] = None):
        self.settings = settings or discovery_settings

    # ------------------------------------------------------------------ meta
    @property
    def weights(self) -> Dict[str, float]:
        return dict(self.settings.trend_weights)

    @property
    def popularity_weights(self) -> Dict[str, float]:
        return dict(self.settings.popularity_weights)

    def describe(self) -> Dict[str, Any]:
        """Everything that shapes a score — returned with every API response."""
        s = self.settings
        return {
            "trendWeights": self.weights,
            "popularityWeights": self.popularity_weights,
            "recencyHalfLifeHours": s.recency_half_life_hours,
            "saturations": {
                "activityChangePct": s.activity_saturation_change_pct,
                "activityEventVolume": s.activity_saturation_event_volume,
                "activityEventParticipants": s.activity_saturation_event_participants,
                "activityTopicMentions": s.activity_saturation_topic_mentions,
                "velocityTopicPerHour": s.velocity_saturation_topic_per_hour,
                "velocityActivityPerHour": s.velocity_saturation_activity_per_hour,
                "interestEvents": s.interest_saturation,
                "newsSourceCount": s.news_saturation_source_count,
                "newsMentions24h": s.news_saturation_mentions_24h,
            },
            "note": (
                "Components without a real measurement are excluded and the "
                "remaining weights are renormalized; every response lists the "
                "components that were used and the ones that were missing."
            ),
        }

    # ------------------------------------------------------------- components
    def calculate_recency_score(self, timestamp: Any, *, now: Optional[datetime] = None) -> Optional[float]:
        """Exponential decay over the entity's own timestamp, in [0, 1].

        Uses whichever real timestamp the caller passes (``createdAt`` for the
        NEW feed, ``updatedAt``/``last_seen`` for freshness). ``None`` when no
        timestamp exists — stocks, for example, have no "created" date here.
        """
        dt = _parse_ts(timestamp)
        if dt is None:
            return None
        reference = now or datetime.now(timezone.utc)
        age_hours = max((reference - dt).total_seconds() / 3600.0, 0.0)
        half_life = max(float(self.settings.recency_half_life_hours), 1e-6)
        return _clamp(math.pow(0.5, age_hours / half_life))

    def calculate_activity_score(self, value: Any, kind: Optional[str] = None) -> Optional[float]:
        """Normalize a real activity measurement against its saturation."""
        if value is None:
            return None
        try:
            raw = abs(float(value))
        except (TypeError, ValueError):
            return None
        if math.isnan(raw) or math.isinf(raw):
            return None
        s = self.settings
        saturations = {
            "change_pct": s.activity_saturation_change_pct,
            "event_volume": s.activity_saturation_event_volume,
            "event_participants": s.activity_saturation_event_participants,
            "topic_mentions": s.activity_saturation_topic_mentions,
        }
        saturation = saturations.get(kind or "", s.activity_saturation_change_pct)
        return _clamp(raw / max(saturation, 1e-9))

    def calculate_velocity_score(self, velocity: Any, kind: Optional[str] = None) -> Optional[float]:
        """Normalize a rate-of-change measurement (per hour) against its cap."""
        if velocity is None:
            return None
        try:
            raw = float(velocity)
        except (TypeError, ValueError):
            return None
        if math.isnan(raw) or math.isinf(raw):
            return None
        saturation = (
            self.settings.velocity_saturation_topic_per_hour
            if kind == "topic"
            else self.settings.velocity_saturation_activity_per_hour
        )
        return _clamp(raw / max(saturation, 1e-9))

    def calculate_interest_score(self, count: Any) -> Optional[float]:
        """Recorded interest (views + searches + watchlist additions).

        A count of 0 is a *real* observation ("nothing recorded yet") and maps
        to 0.0; ``None`` is reserved for "interest tracking is switched off".
        """
        if count is None:
            return None
        if not self.settings.personalization_enabled and not self.settings.interest_saturation:
            return None
        try:
            raw = float(count)
        except (TypeError, ValueError):
            return None
        if raw < 0:
            return None
        return _clamp(raw / max(self.settings.interest_saturation, 1e-9))

    def calculate_news_score(
        self,
        *,
        source_count: Any = None,
        mentions_24h: Any = None,
    ) -> Optional[float]:
        """News breadth for an entity, where a source legitimately measures it.

        News topics: distinct publishers covering it (breadth). Stocks: real
        headlines naming the ticker in the last 24h. Other types have no
        honest link to the news corpus, so this returns ``None`` for them.
        """
        s = self.settings
        if source_count is not None:
            try:
                return _clamp(float(source_count) / max(s.news_saturation_source_count, 1e-9))
            except (TypeError, ValueError):
                return None
        if mentions_24h is not None:
            try:
                return _clamp(float(mentions_24h) / max(s.news_saturation_mentions_24h, 1e-9))
            except (TypeError, ValueError):
                return None
        return None

    # -------------------------------------------------------------- velocity
    @staticmethod
    def velocity_from_history(
        points: Sequence[Tuple[Any, Any]],
        *,
        lookback_hours: float,
        now: Optional[datetime] = None,
    ) -> Optional[float]:
        """Per-hour change of an entity's activity from its own observations.

        ``points`` is ``[(timestamp, activity), ...]`` sorted ascending. Only
        points inside ``lookback_hours`` are used, and at least two distinct
        points are required — one observation cannot measure velocity, and
        admitting that honestly is the point of returning ``None``.
        """
        reference = now or datetime.now(timezone.utc)
        window_start = reference.timestamp() - max(lookback_hours, 1e-6) * 3600.0
        usable: List[Tuple[datetime, float]] = []
        for ts, activity in points:
            dt = _parse_ts(ts)
            if dt is None or activity is None:
                continue
            try:
                value = float(activity)
            except (TypeError, ValueError):
                continue
            if math.isnan(value) or math.isinf(value) or dt.timestamp() < window_start:
                continue
            usable.append((dt, value))
        if len(usable) < 2:
            return None
        usable.sort(key=lambda pair: pair[0])
        (t0, v0), (t1, v1) = usable[0], usable[-1]
        hours = (t1 - t0).total_seconds() / 3600.0
        if hours <= 0:
            return None
        return (v1 - v0) / hours

    # ------------------------------------------------------------- aggregate
    def calculate_trend_score(self, components: Dict[str, Optional[float]]) -> Dict[str, Any]:
        """Weighted aggregate of the supplied components, in 0–100.

        Components that are ``None`` (unavailable) are dropped and the weights
        of the remaining ones are renormalized. The result reports both the
        used weights and the missing components, so the score can be
        reproduced by hand from the response alone.
        """
        weights = self.weights
        used = {name: value for name, value in components.items() if name in weights and value is not None}
        missing = sorted({name for name, value in components.items() if value is None})
        unknown = sorted({name for name in components if name not in weights})
        weights_used = {name: weights[name] for name in used}
        total_weight = sum(weights_used.values())
        if not used or total_weight <= 0:
            return {
                "score": None,
                "components": {k: _round(v) for k, v in components.items()},
                "weightsUsed": {},
                "missing": missing,
                "unknown": unknown,
            }
        score = 100.0 * sum(components[name] * weights[name] for name in used) / total_weight
        return {
            "score": round(_clamp(score / 100.0) * 100.0, 2),
            "components": {k: _round(v) for k, v in components.items()},
            "weightsUsed": {k: round(v, 4) for k, v in weights_used.items()},
            "missing": missing,
            "unknown": unknown,
        }

    def calculate_popularity_score(self, components: Dict[str, Optional[float]]) -> Dict[str, Any]:
        """Interest-first aggregate used by the POPULAR feed (spec §1–§3)."""
        weights = self.popularity_weights
        used = {name: value for name, value in components.items() if name in weights and value is not None}
        missing = sorted({name for name, value in components.items() if value is None})
        weights_used = {name: weights[name] for name in used}
        total_weight = sum(weights_used.values())
        if not used or total_weight <= 0:
            return {
                "score": None,
                "components": {k: _round(v) for k, v in components.items()},
                "weightsUsed": {},
                "missing": missing,
            }
        score = 100.0 * sum(components[name] * weights[name] for name in used) / total_weight
        return {
            "score": round(_clamp(score / 100.0) * 100.0, 2),
            "components": {k: _round(v) for k, v in components.items()},
            "weightsUsed": {k: round(v, 4) for k, v in weights_used.items()},
            "missing": missing,
        }

    # -------------------------------------------------------------- pipeline
    def score_signals(self, signals: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Score one entity's raw signal dict → trend + popularity blocks.

        ``signals`` keys (all optional, all real measurements — see
        ``discovery.entities.DiscoverableEntity.signals``):

        ``created_at`` / ``updated_at``   timestamps (ISO or datetime)
        ``activity_value`` + ``activity_kind``
        ``velocity`` + ``velocity_kind``  per-hour change ("topic"|"activity")
        ``interest_count``                recorded views/searches/watchlist
        ``news_sources`` / ``news_mentions_24h``
        """
        recency_source = signals.get("updated_at") or signals.get("created_at")
        # Freshness is about the newest real timestamp; for entities that have
        # both, the later one wins so a stale createdAt cannot mask an update.
        newer = _pick_newer(signals.get("created_at"), signals.get("updated_at"))
        recency_source = newer or recency_source

        components = {
            "recency": self.calculate_recency_score(recency_source, now=now),
            "activity": self.calculate_activity_score(
                signals.get("activity_value"), signals.get("activity_kind")
            ),
            "velocity": self.calculate_velocity_score(
                signals.get("velocity"), signals.get("velocity_kind")
            ),
            "interest": self.calculate_interest_score(signals.get("interest_count")),
            "news": self.calculate_news_score(
                source_count=signals.get("news_sources"),
                mentions_24h=signals.get("news_mentions_24h"),
            ),
        }
        trend = self.calculate_trend_score(components)
        popularity = self.calculate_popularity_score(
            {"interest": components["interest"], "activity": components["activity"]}
        )
        return {
            "trend": trend,
            "popularity": popularity,
            "components": components,
            "recencySource": recency_source.isoformat() if isinstance(recency_source, datetime) else recency_source,
        }


def _pick_newer(first: Any, second: Any) -> Any:
    a, b = _parse_ts(first), _parse_ts(second)
    if a is None:
        return second if b is not None else None
    if b is None:
        return first
    return first if a >= b else second


#: One shared instance — the engine is stateless and cheap to construct, but a
#: single object keeps "the" configuration unambiguous across routes/jobs.
engine = TrendEngine()


def scores_for(entities: Iterable[Dict[str, Any]], *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Convenience: attach ``trend``/``popularity``/``components`` to dicts
    that already carry a ``signals`` mapping. Returns the same list object."""
    for entity in entities:
        result = engine.score_signals(entity.get("signals") or {}, now=now)
        entity["trend"] = result["trend"]
        entity["popularity"] = result["popularity"]
        entity["scoreComponents"] = result["components"]
    return list(entities)


__all__ = [
    "TrendEngine",
    "engine",
    "scores_for",
]
