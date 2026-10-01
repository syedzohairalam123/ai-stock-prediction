"""
Esports feed service — Phase 21B.

Pure, testable view logic over the Phase 21A data manager. It never invents a
value: every field is read from a provider-supplied ``Match``/``Team``/
``Player``/``GameEvent``, and the featured ranking is a deterministic function
of the real match state (status priority, then recency). Keeping this logic out
of the route handlers is what makes §28's tests possible without a live
network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.esports.providers.base import GameEvent, Match, MatchStatus, Team, per_game_records
from app.esports.services.manager import EsportsDataManager

# Lower number = shown first in a mixed feed / more likely featured.
STATUS_PRIORITY: Dict[str, int] = {
    MatchStatus.LIVE.value: 0,
    MatchStatus.PAUSED.value: 1,
    MatchStatus.MAP_BREAK.value: 2,
    MatchStatus.UPCOMING.value: 3,
    MatchStatus.SCHEDULED.value: 3,
    MatchStatus.POSTPONED.value: 5,
    MatchStatus.COMPLETED.value: 6,
    MatchStatus.CANCELLED.value: 7,
    MatchStatus.UNKNOWN.value: 8,
}

LIVE_STATES = {MatchStatus.LIVE.value, MatchStatus.PAUSED.value, MatchStatus.MAP_BREAK.value}
UPCOMING_STATES = {MatchStatus.UPCOMING.value, MatchStatus.SCHEDULED.value}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def compute_data_quality(match: Match, now: Optional[datetime] = None) -> str:
    """
    LIVE / DELAYED / STALE / UNAVAILABLE for one match.

    For a live match this is the age of the newest provider timestamp. For a
    finished or scheduled match it is the freshness mode the source itself
    publishes (``meta_data['data_mode']``), so a daily-refresh source is
    labelled DELAYED rather than falsely advertised as live.
    """
    now = now or _now()
    status = match.status.value if isinstance(match.status, MatchStatus) else str(match.status)
    reference = _as_aware(match.source_timestamp) or _as_aware(match.received_at)
    if status in LIVE_STATES:
        if reference is None:
            return "UNAVAILABLE"
        age = (now - reference).total_seconds()
        if age < 30:
            return "LIVE"
        if age < 300:
            return "DELAYED"
        return "STALE"
    mode = str((match.meta_data or {}).get("data_mode") or "").upper()
    if mode in ("LIVE", "DELAYED", "STALE"):
        return mode
    return "DELAYED"


def data_mode(match: Match) -> str:
    mode = str((match.meta_data or {}).get("data_mode") or "").upper()
    if mode in ("LIVE", "DELAYED", "STALE", "UNAVAILABLE"):
        return mode
    status = match.status.value if isinstance(match.status, MatchStatus) else str(match.status)
    return "LIVE" if status in LIVE_STATES else "DELAYED"


def match_sort_key(match: Match) -> tuple:
    """Deterministic feed order: status priority, then time (as appropriate)."""
    status = match.status.value if isinstance(match.status, MatchStatus) else str(match.status)
    priority = STATUS_PRIORITY.get(status, 8)
    scheduled = _as_aware(match.scheduled_at) or _now()
    if status in LIVE_STATES:
        reference = _as_aware(match.source_timestamp) or scheduled
        return (priority, -reference.timestamp())
    if status in UPCOMING_STATES:
        return (priority, scheduled.timestamp())
    return (priority, -scheduled.timestamp())


def serialize_match(match: Match, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A complete, frontend-ready match record — only provider-supplied data."""
    now = now or _now()
    meta = match.meta_data or {}
    names = meta.get("team_names") or {}
    logos = meta.get("team_logos") or {}
    status = match.status.value if isinstance(match.status, MatchStatus) else str(match.status)
    last_updated = _as_aware(match.source_timestamp) or _as_aware(match.received_at)
    # CS2 publishes its per-map list under ``maps`` and Dota/LoL under
    # ``games``; normalize both so the UI's per-map breakdown is real for every
    # source that supplies one (instead of only the two MOBA feeds).
    games = per_game_records(meta)
    game_time = meta.get("game_time_seconds")
    if game_time is None and games:
        game_time = games[-1].get("duration")

    return {
        "id": match.id,
        "external_id": match.external_id,
        "game_id": match.game_id,
        "tournament_id": match.tournament_id,
        "tournament_name": meta.get("league") or meta.get("event") or None,
        "series_id": match.series_id,
        "status": status,
        "scheduled_at": _as_aware(match.scheduled_at).isoformat() if match.scheduled_at else None,
        "started_at": _as_aware(match.started_at).isoformat() if match.started_at else None,
        "ended_at": _as_aware(match.ended_at).isoformat() if match.ended_at else None,
        "best_of": match.best_of,
        "current_map": match.current_map,
        "map_number": match.map_number,
        "score_a": match.score_a,
        "score_b": match.score_b,
        "winner_id": match.winner_id,
        "team_a": {"id": match.team_a_id, "name": names.get(match.team_a_id), "logo_url": logos.get(match.team_a_id)},
        "team_b": {"id": match.team_b_id, "name": names.get(match.team_b_id), "logo_url": logos.get(match.team_b_id)},
        "source": match.source,
        "last_updated": last_updated.isoformat() if last_updated else None,
        "data_mode": data_mode(match),
        "data_quality": compute_data_quality(match, now),
        "game_state": meta.get("game_state") or {},
        "games": games,
        "game_time_seconds": game_time,
        "region": meta.get("region"),
    }


def rank_matches(matches: Sequence[Match], now: Optional[datetime] = None) -> List[Match]:
    return sorted(matches, key=match_sort_key)


def select_featured(matches: Sequence[Match], now: Optional[datetime] = None) -> Optional[Match]:
    """
    Featured-match selection (§3): never merely the first row.

    A live match always outranks an upcoming one, which outranks a finished
    one; ties break by recency (live) or proximity (upcoming). Because it is a
    pure function of the current match set, the UI updates automatically the
    moment the backend's data changes.
    """
    candidates = [m for m in matches if m.status != MatchStatus.CANCELLED]
    if not candidates:
        return None
    return rank_matches(candidates, now)[0]


def match_matches_filters(match: Match, filters: Dict[str, Any]) -> bool:
    status = match.status.value if isinstance(match.status, MatchStatus) else str(match.status)
    game = filters.get("game")
    if game and match.game_id != game:
        return False
    statuses = filters.get("statuses")
    if statuses and status not in statuses:
        return False
    if filters.get("live") and status not in LIVE_STATES:
        return False
    if filters.get("upcoming") and status not in UPCOMING_STATES:
        return False
    if filters.get("tournament_id") and match.tournament_id != filters["tournament_id"]:
        return False
    region = filters.get("region")
    if region:
        match_region = str((match.meta_data or {}).get("region") or "")
        if match_region.lower() != region.lower():
            return False
    query = filters.get("q")
    if query:
        haystack = " ".join(
            str(part)
            for part in [
                (match.meta_data or {}).get("league"),
                (match.meta_data or {}).get("event"),
                *((match.meta_data or {}).get("team_names") or {}).values(),
                match.external_id,
            ]
            if part
        ).lower()
        if query.lower() not in haystack:
            return False
    date_from = _as_aware(filters.get("date_from"))
    date_to = _as_aware(filters.get("date_to"))
    scheduled = _as_aware(match.scheduled_at)
    if scheduled:
        if date_from and scheduled < date_from:
            return False
        if date_to and scheduled > date_to:
            return False
    return True


async def gather_matches(
    manager: EsportsDataManager,
    game_id: Optional[str] = None,
    tournament_id: Optional[str] = None,
) -> List[Match]:
    """Fetch matches across games (or one game) through the manager."""
    if game_id:
        return await manager.get_matches(game_id, tournament_id)
    games = await manager.get_games()
    collected: List[Match] = []
    seen: set[str] = set()
    for game in games:
        for match in await manager.get_matches(game.id):
            if match.id in seen:
                continue
            seen.add(match.id)
            collected.append(match)
    return collected


async def build_feed(
    manager: EsportsDataManager,
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Cross-game (or single-game) match feed with server-side filtering (§24)."""
    filters = filters or {}
    now = _now()
    matches = await gather_matches(manager, filters.get("game"), filters.get("tournament_id"))
    # Tournament filter for a cross-game feed must also be applied here because
    # gather_matches only forwards it to a single provider.
    matches = [m for m in matches if match_matches_filters(m, filters)]
    ordered = rank_matches(matches, now)
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return {
        "matches": [serialize_match(m, now) for m in page],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
        "generated_at": now.isoformat(),
        "filters": {k: v for k, v in filters.items() if v not in (None, "", [], False)},
    }


async def featured_match(manager: EsportsDataManager, game_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    now = _now()
    matches = [m for m in await gather_matches(manager, game_id)]
    best = select_featured(matches, now)
    if best is None:
        return None
    return serialize_match(best, now)


async def game_summary(manager: EsportsDataManager, game_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Per-game activity counts for the hub category cards (§5).

    Counts are literal counts of the matches the provider actually returned in
    this fetch — never an invented "volume" number. ``activity`` therefore
    carries the unit it was measured in.
    """
    now = _now()
    games = await manager.get_games() if not game_id else [g for g in await manager.get_games() if g.id == game_id]
    summaries: List[Dict[str, Any]] = []
    for game in games:
        try:
            matches = await manager.get_matches(game.id)
        except Exception:  # a single game failing must not blank the hub
            matches = []
        try:
            tournaments = await manager.get_tournaments(game.id)
        except Exception:
            tournaments = []
        live = sum(1 for m in matches if (m.status.value if isinstance(m.status, MatchStatus) else str(m.status)) in LIVE_STATES)
        upcoming = sum(1 for m in matches if (m.status.value if isinstance(m.status, MatchStatus) else str(m.status)) in UPCOMING_STATES)
        recent = sum(1 for m in matches if (m.status.value if isinstance(m.status, MatchStatus) else str(m.status)) == MatchStatus.COMPLETED.value)
        newest = max(
            (m.source_timestamp for m in matches if m.source_timestamp is not None),
            default=None,
        )
        summaries.append(
            {
                "game_id": game.id,
                "name": game.name,
                "short_name": game.short_name,
                "source": game.source,
                "counts": {
                    "live": live,
                    "upcoming": upcoming,
                    "recent": recent,
                    "total": len(matches),
                    "tournaments": len(tournaments),
                },
                "activity": {"label": "matches returned by source", "value": len(matches)},
                "last_updated": _as_aware(newest).isoformat() if newest else None,
                "data_mode": (game.meta_data or {}).get("data_mode") or "DELAYED",
                "tournament_count_window_days": 30,
            }
        )
    return {
        "games": summaries,
        "generated_at": now.isoformat(),
        "window": {"recent_days": 14, "note": "counts reflect the provider response used for this request"},
    }


async def match_detail(manager: EsportsDataManager, match_id: str) -> Optional[Dict[str, Any]]:
    """Everything the live match page needs, assembled from real sub-fetches."""
    now = _now()
    match = await manager.get_match(match_id)
    if match is None:
        return None
    detail = serialize_match(match, now)

    team_a = await manager.get_team(match.team_a_id)
    team_b = await manager.get_team(match.team_b_id)
    for side, team in (("team_a", team_a), ("team_b", team_b)):
        if team is None:
            continue
        detail[side]["name"] = detail[side]["name"] or team.name
        detail[side]["logo_url"] = detail[side]["logo_url"] or team.logo_url
        detail[side]["short_name"] = team.short_name
        detail[side]["region"] = team.region
        detail[side]["metadata"] = team.meta_data

    players_a = await manager.get_players(match.team_a_id)
    players_b = await manager.get_players(match.team_b_id)
    detail["players"] = {
        "team_a": [p.to_dict() for p in players_a],
        "team_b": [p.to_dict() for p in players_b],
    }

    events = await manager.get_match_events(match_id)
    try:
        snapshot = await manager.get_live_snapshot(match_id)
    except Exception:  # a snapshot-store hiccup must not blank the match page
        snapshot = None
    detail["snapshot"] = snapshot.to_dict() if snapshot else None
    detail["events"] = [e.to_dict() for e in events]
    detail["event_count"] = len(events)
    detail["data_sources"] = await manager.provider_health_report()
    return detail


async def tournament_detail(manager: EsportsDataManager, tournament_id: str) -> Optional[Dict[str, Any]]:
    """One tournament plus its real related matches (§14)."""
    now = _now()
    target = None
    matches: List[Match] = []
    for game in await manager.get_games():
        try:
            tournaments = await manager.get_tournaments(game.id)
        except Exception:
            tournaments = []
        for tournament in tournaments:
            if tournament.id == tournament_id:
                target = tournament
        if target is not None:
            try:
                matches = await manager.get_matches(game.id, tournament_id)
            except Exception:
                matches = []
            break
    if target is None:
        return None
    status = target.status
    if status not in ("upcoming", "live", "completed"):
        status = "completed" if _as_aware(target.end_date) and _as_aware(target.end_date) < now else "upcoming"
    return {
        "id": target.id,
        "external_id": target.external_id,
        "name": target.name,
        "game_id": target.game_id,
        "start_date": _as_aware(target.start_date).isoformat() if target.start_date else None,
        "end_date": _as_aware(target.end_date).isoformat() if target.end_date else None,
        "prize_pool": target.prize_pool,
        "region": target.region,
        "status": status,
        "metadata": target.meta_data,
        "matches": [serialize_match(m, now) for m in rank_matches(matches, now)],
        "match_count": len(matches),
        "generated_at": now.isoformat(),
    }


def event_to_dict(event: GameEvent) -> Dict[str, Any]:
    return event.to_dict()
