"""
League of Legends provider adapter — Phase 21B real integration.

Source: https://esports-api.lolesports.com (Riot's public esports gateway).

The gateway requires an ``x-api-key`` header. Riot publishes a well-known
public key used by the official LoL Esports web client; it is used as the
default here and can be overridden through ``ESPORTS_LOL_API_KEY``. The
schedule, live and event-detail endpoints give real teams, logos, series
scores, best-of counts, game states and start times. Riot does not publish
player rosters through this gateway, so ``get_players`` honestly returns an
empty list rather than inventing a roster.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

import httpx

from .base import (
    EsportsDataProvider,
    EsportsProviderError,
    Game,
    Tournament,
    Match,
    Team,
    Player,
    GameEvent,
    EventType,
    MatchStatus,
    ProviderHealth,
)
from ._support import AsyncTTLCache, parse_iso, safe_int, make_id, slug, utcnow

logger = logging.getLogger("neural_market.esports.providers.lol")

PREFIX = "lol"
GAME_ID = "lol"
SOURCE = "lolesports.com"
BASE_URL = "https://esports-api.lolesports.com/persisted/gw"
# Riot's public client key (not a secret; overridable via config/env).
PUBLIC_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"

_STATE_MAP = {
    "completed": MatchStatus.COMPLETED,
    "inprogress": MatchStatus.LIVE,
    "unstarted": MatchStatus.SCHEDULED,
    "canceled": MatchStatus.CANCELLED,
    "postponed": MatchStatus.POSTPONED,
}


class LoLAdapter(EsportsDataProvider):
    """League of Legends adapter backed by Riot's public esports gateway."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = BASE_URL):
        self.api_key = api_key or PUBLIC_KEY
        self.base_url = base_url
        self.provider_name = SOURCE
        self._client: Optional[httpx.AsyncClient] = None
        self._cache = AsyncTTLCache()
        self._health_status = ProviderHealth.AVAILABLE
        self._metrics = {
            "request_count": 0,
            "error_count": 0,
            "last_success": None,
            "last_error": None,
            "avg_latency_ms": 0.0,
        }

    # ------------------------------------------------------------------ http
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=20.0,
                headers={
                    "Accept": "application/json",
                    "x-api-key": self.api_key or "",
                    "User-Agent": "NeuralMarket/2.3 (esports)",
                },
            )
        return self._client

    async def _get_json(self, endpoint: str, params: Optional[Dict[str, Any]], ttl_seconds: float) -> Any:
        key = f"{endpoint}?{sorted((params or {}).items())}"

        async def _fetch() -> Any:
            self._metrics["request_count"] += 1
            started = utcnow()
            try:
                client = await self._get_client()
                response = await client.get(endpoint, params=params)
                response.raise_for_status()
                data = response.json()
                latency = (utcnow() - started).total_seconds() * 1000
                try:  # Phase 21C observability: real per-source latency (spec §17)
                    from app.esports.analytics.observability import esports_metrics

                    esports_metrics.record_provider_latency(self.provider_name, latency)
                except Exception:
                    pass
                count = max(1, self._metrics["request_count"])
                self._metrics["avg_latency_ms"] = (
                    self._metrics["avg_latency_ms"] * (count - 1) + latency
                ) / count
                self._metrics["last_success"] = utcnow().isoformat()
                self._health_status = ProviderHealth.AVAILABLE
                return data
            except httpx.HTTPError as exc:
                self._metrics["error_count"] += 1
                self._metrics["last_error"] = str(exc)
                self._health_status = (
                    ProviderHealth.DEGRADED if self._metrics["error_count"] < 5 else ProviderHealth.DOWN
                )
                raise EsportsProviderError(self.provider_name, f"HTTP error: {exc}") from exc
            except Exception as exc:
                self._metrics["error_count"] += 1
                self._metrics["last_error"] = str(exc)
                self._health_status = ProviderHealth.DEGRADED
                raise EsportsProviderError(self.provider_name, f"Request error: {exc}") from exc

        try:
            return await self._cache.get_or_set(key, ttl_seconds, _fetch)
        except EsportsProviderError:
            stale = self._cache.peek(key)
            if stale is not None:
                return stale
            raise

    # -------------------------------------------------------------- mapping
    def _team_id(self, name: str) -> str:
        return make_id(f"{PREFIX}-t-", slug(name, max_length=30))

    def _map_team_from_schedule(self, team: Dict[str, Any]) -> Team:
        name = team.get("name") or "TBD"
        return Team(
            id=self._team_id(name),
            external_id=slug(name, 30),
            name=name,
            short_name=(team.get("code") or name[:4] or "TBD").upper(),
            game_id=GAME_ID,
            logo_url=team.get("image") or None,
            region=None,
            meta_data={"source": SOURCE, "record": team.get("record")},
        )

    def _map_match(self, event: Dict[str, Any]) -> Optional[Match]:
        match = event.get("match") or {}
        teams = match.get("teams") or []
        if len(teams) < 2:
            return None
        start = parse_iso(event.get("startTime")) or utcnow()
        state = str(event.get("state") or "").lower().replace("-", "").replace("_", "")
        status = _STATE_MAP.get(state, MatchStatus.UNKNOWN)
        league = event.get("league") or {}
        strategy = match.get("strategy") or {}
        a, b = teams[0], teams[1]
        score_a = safe_int((a.get("result") or {}).get("gameWins"))
        score_b = safe_int((b.get("result") or {}).get("gameWins"))
        winner_id = None
        outcome_a = (a.get("result") or {}).get("outcome")
        outcome_b = (b.get("result") or {}).get("outcome")
        if outcome_a == "win":
            winner_id = self._team_id(a.get("name"))
        elif outcome_b == "win":
            winner_id = self._team_id(b.get("name"))
        return Match(
            id=make_id(f"{PREFIX}-m", match.get("id") or event.get("id")),
            external_id=str(match.get("id") or event.get("id")),
            game_id=GAME_ID,
            tournament_id=make_id(f"{PREFIX}-tour-", slug(league.get("slug") or league.get("name") or "")),
            series_id=make_id(f"{PREFIX}-m", match.get("id") or event.get("id")),
            status=status,
            scheduled_at=start,
            team_a_id=self._team_id(a.get("name")),
            team_b_id=self._team_id(b.get("name")),
            started_at=start if status in (MatchStatus.LIVE, MatchStatus.COMPLETED) else None,
            ended_at=start if status == MatchStatus.COMPLETED else None,
            best_of=safe_int(strategy.get("count"), 1) or 1,
            current_map=None,
            map_number=0,
            score_a=score_a,
            score_b=score_b,
            winner_id=winner_id,
            source=SOURCE,
            source_timestamp=start,
            received_at=utcnow(),
            meta_data={
                "source": SOURCE,
                "league": league.get("name"),
                "block": event.get("blockName"),
                "data_mode": "LIVE" if status == MatchStatus.LIVE else "DELAYED",
                "team_names": {
                    self._team_id(a.get("name")): a.get("name"),
                    self._team_id(b.get("name")): b.get("name"),
                },
                "team_logos": {
                    self._team_id(a.get("name")): a.get("image"),
                    self._team_id(b.get("name")): b.get("image"),
                },
            },
        )

    async def _schedule_events(self, live_only: bool = False) -> List[Dict[str, Any]]:
        if live_only:
            data = await self._get_json("/getLive", {"hl": "en-US"}, ttl_seconds=20)
        else:
            data = await self._get_json("/getSchedule", {"hl": "en-US"}, ttl_seconds=120)
        events = (((data or {}).get("data") or {}).get("schedule") or {}).get("events") or []
        rows = [e for e in events if isinstance(e, dict) and e.get("type") == "match"]
        if live_only:
            rows = [e for e in rows if str(e.get("state", "")).lower() == "inprogress"]
        return rows

    # ------------------------------------------------------------- interface
    async def get_games(self) -> List[Game]:
        return [
            Game(
                id=GAME_ID,
                external_id=GAME_ID,
                name="League of Legends",
                short_name="LoL",
                source=SOURCE,
                meta_data={"genre": "MOBA", "publisher": "Riot Games", "data_mode": "LIVE"},
            )
        ]

    async def get_tournaments(self, game_id: str) -> List[Tournament]:
        if game_id != GAME_ID:
            return []
        rows = await self._schedule_events()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for event in rows:
            league = event.get("league") or {}
            key = league.get("slug") or league.get("name") or "unknown"
            grouped.setdefault(key, []).append(event)
        now = utcnow()
        out: List[Tournament] = []
        for key, events in grouped.items():
            starts = sorted(parse_iso(e.get("startTime")) for e in events if e.get("startTime"))
            starts = [s for s in starts if s is not None]
            start = starts[0] if starts else now
            end = starts[-1] if starts else None
            has_live = any(str(e.get("state", "")).lower() == "inprogress" for e in events)
            if has_live:
                status = "live"
            elif start > now:
                status = "upcoming"
            else:
                status = "completed"
            name = (events[0].get("league") or {}).get("name") or key
            out.append(
                Tournament(
                    id=make_id(f"{PREFIX}-tour-", slug(key)),
                    external_id=key,
                    name=name,
                    game_id=GAME_ID,
                    start_date=start,
                    end_date=end,
                    prize_pool=None,
                    region=None,
                    status=status,
                    meta_data={"source": SOURCE, "matches": len(events)},
                )
            )
        return out

    async def get_matches(self, game_id: str, tournament_id: Optional[str] = None) -> List[Match]:
        if game_id != GAME_ID:
            return []
        rows = await self._schedule_events()
        mapped = [m for m in (self._map_match(e) for e in rows) if m is not None]
        if tournament_id:
            mapped = [m for m in mapped if m.tournament_id == tournament_id]
        mapped.sort(key=lambda m: m.scheduled_at)
        return mapped

    async def get_match(self, match_id: str) -> Optional[Match]:
        if not match_id.startswith(f"{PREFIX}-m"):
            return None
        external = match_id[len(f"{PREFIX}-m"):]
        try:
            data = await self._get_json("/getEventDetails", {"hl": "en-US", "id": external}, ttl_seconds=60)
        except EsportsProviderError:
            data = None
        event = ((data or {}).get("data") or {}).get("event")
        if isinstance(event, dict):
            event = dict(event)
            event.setdefault("state", "completed" if event.get("match", {}).get("games") else "unstarted")
            # eventDetails has no per-match state; infer from games when present.
            games = (event.get("match") or {}).get("games") or []
            if games and all(g.get("state") == "completed" for g in games):
                event["state"] = "completed"
            elif any(g.get("state") == "inProgress" for g in games):
                event["state"] = "inProgress"
            mapped = self._map_match(event)
            if mapped is not None:
                # Enrich with map/game number information from the detail payload.
                mapped.map_number = len(games)
                if games:
                    mapped.current_map = None
                    last = games[-1]
                    mapped.meta_data["games"] = [
                        {"number": g.get("number"), "state": g.get("state")} for g in games
                    ]
                return mapped
        for row in await self._schedule_events():
            if str((row.get("match") or {}).get("id")) == external:
                return self._map_match(row)
        for row in await self._schedule_events(live_only=True):
            if str((row.get("match") or {}).get("id")) == external:
                return self._map_match(row)
        return None

    async def get_teams(self, game_id: str) -> List[Team]:
        if game_id != GAME_ID:
            return []
        rows = await self._schedule_events()
        teams: Dict[str, Team] = {}
        for event in rows:
            for team in ((event.get("match") or {}).get("teams") or []):
                mapped = self._map_team_from_schedule(team)
                teams.setdefault(mapped.id, mapped)
        return list(teams.values())

    async def get_team(self, team_id: str) -> Optional[Team]:
        """Optional extra (not in the base interface): resolve a schedule team."""
        if not team_id.startswith(f"{PREFIX}-t"):
            return None
        external = team_id[len(f"{PREFIX}-t-"):]
        for event in await self._schedule_events():
            for team in ((event.get("match") or {}).get("teams") or []):
                if slug(team.get("name") or "", 30) == external:
                    return self._map_team_from_schedule(team)
        return None

    async def get_players(self, team_id: str) -> List[Player]:
        # The public gateway exposes no rosters; empty (not invented) is honest.
        return []

    async def get_live_events(self, game_id: str) -> List[GameEvent]:
        if game_id != GAME_ID:
            return []
        try:
            rows = await self._schedule_events(live_only=True)
        except EsportsProviderError:
            return []
        events: List[GameEvent] = []
        for event in rows:
            match = event.get("match") or {}
            teams = match.get("teams") or []
            if len(teams) < 2:
                continue
            match_id = make_id(f"{PREFIX}-m", match.get("id") or event.get("id"))
            start = parse_iso(event.get("startTime")) or utcnow()
            a, b = teams[0], teams[1]
            score_a = safe_int((a.get("result") or {}).get("gameWins"))
            score_b = safe_int((b.get("result") or {}).get("gameWins"))
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match_id}-start", max_length=48),
                    match_id=match_id,
                    game_id=GAME_ID,
                    type=EventType.MATCH_STARTED,
                    timestamp=start,
                    sequence=1,
                    team_id=None,
                    player_id=None,
                    payload={"source": SOURCE},
                    source=SOURCE,
                    source_timestamp=start,
                )
            )
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match_id}-score-{score_a}-{score_b}", max_length=48),
                    match_id=match_id,
                    game_id=GAME_ID,
                    type=EventType.SCORE_CHANGED,
                    timestamp=utcnow(),
                    sequence=2 + score_a + score_b,
                    team_id=None,
                    player_id=None,
                    payload={
                        "team_a_score": score_a,
                        "team_b_score": score_b,
                        "team_a_name": a.get("name"),
                        "team_b_name": b.get("name"),
                    },
                    source=SOURCE,
                    source_timestamp=utcnow(),
                )
            )
        return events

    async def get_match_events(self, match_id: str) -> List[GameEvent]:
        if not match_id.startswith(f"{PREFIX}-m"):
            return []
        external = match_id[len(f"{PREFIX}-m"):]
        try:
            data = await self._get_json("/getEventDetails", {"hl": "en-US", "id": external}, ttl_seconds=60)
        except EsportsProviderError:
            return []
        event = ((data or {}).get("data") or {}).get("event") or {}
        games = (event.get("match") or {}).get("games") or []
        base = parse_iso(event.get("startTime")) or utcnow()
        events: List[GameEvent] = []
        sequence = 0
        for game in games:
            sequence += 1
            number = safe_int(game.get("number"), sequence)
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{external}-g{number}-start", max_length=48),
                    match_id=match_id,
                    game_id=GAME_ID,
                    type=EventType.MAP_STARTED,
                    timestamp=base,
                    sequence=sequence,
                    payload={"map_number": number, "state": game.get("state"), "timestamp_precision": "date"},
                    source=SOURCE,
                    source_timestamp=base,
                )
            )
            if game.get("state") == "completed":
                sequence += 1
                events.append(
                    GameEvent(
                        id=make_id(f"{PREFIX}-e", f"{external}-g{number}-end", max_length=48),
                        match_id=match_id,
                        game_id=GAME_ID,
                        type=EventType.MAP_ENDED,
                        timestamp=base,
                        sequence=sequence,
                        payload={"map_number": number, "timestamp_precision": "date"},
                        source=SOURCE,
                        source_timestamp=base,
                    )
                )
        return events

    async def subscribe_to_match(self, match_id: str, callback) -> None:  # pragma: no cover - polling source
        return None

    async def unsubscribe_from_match(self, match_id: str) -> None:  # pragma: no cover - polling source
        return None

    def get_provider_name(self) -> str:
        return self.provider_name

    async def get_provider_health(self) -> ProviderHealth:
        return self._health_status

    async def get_provider_metrics(self) -> Dict[str, Any]:
        return {**self._metrics, "source": SOURCE, "data_mode": "LIVE", "refresh": "realtime"}

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
