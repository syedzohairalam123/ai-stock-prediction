"""
Phase 21C §6–§9 — the trending engine.

Two rules drive this module:

1. **Only real signals.** A signal is either measured by this application
   (live matches it is currently tracking, events it actually ingested, searches
   and follows it actually recorded) or it is absent. Absent signals are listed
   and *reduce confidence*; they are never filled with a plausible-looking
   number. There is no viewer count unless a provider publishes one.
2. **Weights live in one place.** ``TrendingWeights`` is built from settings and
   passed down; no weight is hardcoded in a route or a UI component (§7).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.esports.providers.base import Match, MatchStatus

#: Minimum weight-sum share of available signals before a score is trusted.
CONFIDENCE_HIGH = 0.8
CONFIDENCE_MEDIUM = 0.5


@dataclass(frozen=True)
class TrendingWeights:
    """Central, configurable weights for the trending score (spec §7)."""

    live: float = 0.35
    event: float = 0.25
    start_rate: float = 0.20
    search: float = 0.10
    watchlist: float = 0.10
    viewer: float = 0.15

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)

    def total(self) -> float:
        return sum(self.as_dict().values())

    @classmethod
    def from_settings(cls, settings) -> "TrendingWeights":
        return cls(
            live=getattr(settings, "esports_trend_weight_live", 0.35),
            event=getattr(settings, "esports_trend_weight_event", 0.25),
            start_rate=getattr(settings, "esports_trend_weight_start_rate", 0.20),
            search=getattr(settings, "esports_trend_weight_search", 0.10),
            watchlist=getattr(settings, "esports_trend_weight_watchlist", 0.10),
            viewer=getattr(settings, "esports_trend_weight_viewer", 0.15),
        )


#: Signal catalogue — the single source of truth for keys/labels/weights.
SIGNAL_SPECS: List[Dict[str, str]] = [
    {"key": "live", "weight": "live", "label": "Live matches (this app's feed)"},
    {"key": "event", "weight": "event", "label": "Events ingested (event velocity)"},
    {"key": "start_rate", "weight": "start_rate", "label": "Match start rate"},
    {"key": "search", "weight": "search", "label": "Search velocity (app-recorded)"},
    {"key": "watchlist", "weight": "watchlist", "label": "Follows / watchlist adds (app-recorded)"},
    {"key": "viewer", "weight": "viewer", "label": "Viewer count (only if a provider publishes one)"},
]


def _status(match: Match) -> str:
    return match.status.value if isinstance(match.status, MatchStatus) else str(match.status)


def normalize_signal(value: Optional[float], saturation: float, *, log_scale: bool = False) -> Optional[float]:
    """
    Map a raw count onto 0..1 with saturating (optionally log) scaling.

    Normalization happens *before* aggregation so one wildly large signal cannot
    dominate the weighted sum (§7). A missing value stays missing.
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return 0.0
    if saturation <= 0:
        saturation = 1.0
    if log_scale:
        return min(1.0, math.log1p(numeric) / math.log1p(saturation))
    return min(1.0, numeric / saturation)


def calculate_trending_score(
    signals: Mapping[str, Optional[float]],
    weights: TrendingWeights,
    *,
    saturation: float = 25.0,
    log_signals: Sequence[str] = ("event", "search", "watchlist"),
) -> Dict[str, Any]:
    """
    Weighted, confidence-aware trending score.

    Returns the score, the per-signal normalized contribution, every missing
    signal, and the confidence label derived from how much of the weight budget
    had real data behind it.
    """
    weight_map = weights.as_dict()
    components: Dict[str, Optional[float]] = {}
    weighted_sum = 0.0
    available_weight = 0.0
    missing: List[str] = []
    contributions: Dict[str, float] = {}

    for spec in SIGNAL_SPECS:
        key = spec["key"]
        weight = float(weight_map.get(spec["weight"], 0.0))
        raw = signals.get(key)
        normalized = normalize_signal(raw, saturation, log_scale=key in log_signals)
        components[key] = normalized
        if normalized is None:
            missing.append(key)
            continue
        available_weight += weight
        contribution = normalized * weight
        contributions[key] = round(contribution, 6)
        weighted_sum += contribution

    total_weight = weights.total()
    score = (weighted_sum / available_weight) if available_weight > 0 else None
    confidence_ratio = (available_weight / total_weight) if total_weight > 0 else 0.0
    if confidence_ratio >= CONFIDENCE_HIGH:
        confidence = "HIGH"
    elif confidence_ratio >= CONFIDENCE_MEDIUM:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "score": round(score, 6) if score is not None else None,
        "score_0_100": round(score * 100, 2) if score is not None else None,
        "components": components,
        "contributions": contributions,
        "missing_signals": missing,
        "available_weight": round(available_weight, 6),
        "total_weight": round(total_weight, 6),
        "confidence": confidence,
        "confidence_ratio": round(confidence_ratio, 4),
        "weights": weights.as_dict(),
        "saturation": saturation,
    }


class TrendingGameEngine:
    """
    Ranks games by measured activity (spec §6, §8).

    Input is a list of plain dicts — one per game — whose values are counts this
    application actually has: live matches, ingested events, starts observed,
    recorded searches/follows, and `viewer_count` only when a provider supplied
    one. Any signal left as ``None`` is reported as missing.
    """

    def __init__(self, weights: Optional[TrendingWeights] = None, *, saturation: float = 25.0,
                 window: timedelta = timedelta(hours=24)):
        self.weights = weights or TrendingWeights()
        self.saturation = saturation
        self.window = window

    def compute(self, games: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        ranked: List[Dict[str, Any]] = []
        for game in games:
            signals = {
                "live": game.get("live_match_count"),
                "event": game.get("event_count_window"),
                "start_rate": game.get("match_start_rate"),
                "search": game.get("search_count"),
                "watchlist": game.get("watchlist_count"),
                "viewer": game.get("viewer_count"),
            }
            scored = calculate_trending_score(signals, self.weights, saturation=self.saturation)
            ranked.append(
                {
                    "game_id": game.get("game_id"),
                    "name": game.get("name"),
                    "short_name": game.get("short_name"),
                    "signals": {k: signals[k] for k in signals},
                    "live_matches": signals["live"],
                    "activity_metric": _activity_metric(signals),
                    "last_updated": game.get("last_updated"),
                    "data_mode": game.get("data_mode"),
                    **scored,
                }
            )
        ranked.sort(key=lambda row: (row["score"] is None, -(row["score"] or 0.0), row["game_id"] or ""))
        return {
            "games": ranked,
            "generated_at": now.isoformat(),
            "window_hours": round(self.window.total_seconds() / 3600, 2),
            "engine": {
                "weights": self.weights.as_dict(),
                "saturation": self.saturation,
                "signals": SIGNAL_SPECS,
                "note": (
                    "Signals are counts this application recorded or the provider published. "
                    "A signal with no source is reported as missing and lowers confidence — "
                    "no activity number is ever invented."
                ),
            },
        }


def _activity_metric(signals: Mapping[str, Optional[float]]) -> Dict[str, Any]:
    """
    The single most meaningful real activity number for a game, with its unit.

    Viewer count wins only when a provider actually published one; otherwise the
    metric falls back to a count this application measured.
    """
    if signals.get("viewer") is not None:
        return {"label": "active viewers", "value": signals["viewer"], "source": "provider"}
    if signals.get("event") is not None:
        return {"label": "events ingested", "value": signals["event"], "source": "this app"}
    if signals.get("live") is not None:
        return {"label": "live matches", "value": signals["live"], "source": "this app"}
    return {"label": "activity unavailable", "value": None, "source": None}


# ---------------------------------------------------------------------------
# §9 — trending matches (measurable activity, not a hardcoded list)
# ---------------------------------------------------------------------------

def rank_trending_matches(
    matches: Sequence[Match],
    *,
    event_counts: Optional[Mapping[str, int]] = None,
    start_counts: Optional[Mapping[str, int]] = None,
    now: Optional[datetime] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Rank matches by *measured* activity.

    Components (all disclosed per match): live state, events observed for the
    match, matches started in the window, and recency. A finished match with no
    events cannot outrank a live one, but between two live matches the one with
    more ingested events wins.
    """
    now = now or datetime.now(timezone.utc)
    event_counts = event_counts or {}
    start_counts = start_counts or {}
    scored: List[Dict[str, Any]] = []
    for match in matches:
        status = _status(match)
        live_score = 1.0 if status in (MatchStatus.LIVE.value, MatchStatus.MAP_BREAK.value, MatchStatus.PAUSED.value) else (
            0.5 if status in (MatchStatus.UPCOMING.value, MatchStatus.SCHEDULED.value) else 0.0
        )
        events = int(event_counts.get(match.id, 0))
        event_score = normalize_signal(events, 20.0, log_scale=True) or 0.0
        starts = int(start_counts.get(match.id, 0))
        start_score = normalize_signal(starts, 5.0) or 0.0
        reference = match.source_timestamp or match.scheduled_at
        recency_score = 0.0
        if reference is not None:
            aware = reference if reference.tzinfo else reference.replace(tzinfo=timezone.utc)
            age_minutes = max(0.0, (now - aware).total_seconds() / 60.0)
            recency_score = max(0.0, 1.0 - min(age_minutes / 240.0, 1.0))
        total = 0.45 * live_score + 0.25 * event_score + 0.15 * start_score + 0.15 * recency_score
        scored.append(
            {
                "match_id": match.id,
                "game_id": match.game_id,
                "status": status,
                "score": round(total, 6),
                "components": {
                    "live_state": round(live_score, 4),
                    "events_observed": events,
                    "starts_observed": starts,
                    "recency": round(recency_score, 4),
                },
            }
        )
    scored.sort(key=lambda row: -row["score"])
    return scored[:limit]
