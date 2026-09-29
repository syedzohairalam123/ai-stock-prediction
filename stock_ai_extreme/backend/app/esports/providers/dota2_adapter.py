"""
Dota 2 provider adapter — Phase 21B real integration.

Source: https://api.opendota.com (public, no API key required).

OpenDota publishes recent professional match results (with per-game kill
scores, durations and series groupings), live games, team profiles, rosters,
player profiles and league metadata. Each professional series is surfaced as a
single match with a real series score derived by counting the games each side
won; the individual games remain available in ``meta_data`` and are the source
of the match timeline. Anonymous live games without published team names are
deliberately excluded rather than dressed up with invented identities.
"""

from __future__ import annotations

import asyncio
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
from ._support import (
    AsyncTTLCache,
    from_epoch,
    safe_int,
    make_id,
    slug,
    utcnow,
)

logger = logging.getLogger("neural_market.esports.providers.dota2")

PREFIX = "dota2"
GAME_ID = "dota2"
SOURCE = "opendota.com"
BASE_URL = "https://api.opendota.com/api"


class Dota2Adapter(EsportsDataProvider):
    """Dota 2 adapter backed by the keyless OpenDota API."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = BASE_URL):
        self.api_key = api_key
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
                headers={"Accept": "application/json", "User-Agent": "NeuralMarket/2.3 (esports)"},
            )
        return self._client

    async def _get_json(self, endpoint: str, ttl_seconds: float) -> Any:
        key = endpoint

        async def _fetch() -> Any:
            self._metrics["request_count"] += 1
            started = utcnow()
            try:
                client = await self._get_client()
                response = await client.get(endpoint)
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
    def _team_ref(self, team_id: Any, name: Any) -> Team:
        ext = str(team_id) if team_id else slug(name or "unknown", 30)
        return Team(
            id=make_id(f"{PREFIX}-t", ext),
            external_id=ext,
            name=name or "Unknown team",
            short_name=(name or "TBD")[:4].upper(),
            game_id=GAME_ID,
            logo_url=None,
            region=None,
            meta_data={"source": SOURCE},
        )

    async def _all_pro_matches(self) -> List[Dict[str, Any]]:
        data = await self._get_json("/proMatches", ttl_seconds=120)
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _group_series(self, rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("series_id") or f"m{row.get('match_id')}")
            groups.setdefault(key, []).append(row)
        return list(groups.values())

    def _map_series(self, games: List[Dict[str, Any]]) -> Optional[Match]:
        if not games:
            return None
        first = games[0]
        radiant_id = first.get("radiant_team_id")
        dire_id = first.get("dire_team_id")
        radiant_name = first.get("radiant_name")
        dire_name = first.get("dire_name")
        a_id = make_id(f"{PREFIX}-t", radiant_id or slug(radiant_name or "unknown", 30))
        b_id = make_id(f"{PREFIX}-t", dire_id or slug(dire_name or "unknown", 30))
        # Real series score: number of games each side won across the series.
        wins_a = sum(1 for g in games if g.get("radiant_win") is True)
        wins_b = sum(1 for g in games if g.get("radiant_win") is False)
        starts = [from_epoch(g.get("start_time")) for g in games]
        starts = [s for s in starts if s is not None]
        start = min(starts) if starts else utcnow()
        end = max(starts) if starts else None
        winner_id = a_id if wins_a > wins_b else (b_id if wins_b > wins_a else None)
        series_key = first.get("series_id") or first.get("match_id")
        return Match(
            id=make_id(f"{PREFIX}-m", series_key),
            external_id=str(series_key),
            game_id=GAME_ID,
            tournament_id=make_id(f"{PREFIX}-tour-", first.get("leagueid") or slug(first.get("league_name") or "")),
            series_id=make_id(f"{PREFIX}-s", series_key),
            status=MatchStatus.COMPLETED,
            scheduled_at=start,
            team_a_id=a_id,
            team_b_id=b_id,
            started_at=start,
            ended_at=end,
            best_of=max(len(games), 1),
            current_map=None,
            map_number=len(games),
            score_a=wins_a,
            score_b=wins_b,
            winner_id=winner_id,
            source=SOURCE,
            source_timestamp=end or start,
            received_at=utcnow(),
            meta_data={
                "source": SOURCE,
                "league": first.get("league_name"),
                "league_id": first.get("leagueid"),
                "data_mode": "DELAYED",
                "series_type": first.get("series_type"),
                "games": [
                    {
                        "match_id": g.get("match_id"),
                        "duration": safe_int(g.get("duration")),
                        "radiant_score": safe_int(g.get("radiant_score")),
                        "dire_score": safe_int(g.get("dire_score")),
                        "radiant_win": g.get("radiant_win"),
                        "start_time": g.get("start_time"),
                    }
                    for g in games
                ],
                "team_names": {a_id: radiant_name, b_id: dire_name},
            },
        )

    def _map_live(self, row: Dict[str, Any]) -> Optional[Match]:
        radiant_name = (row.get("team_name_radiant") or "").strip()
        dire_name = (row.get("team_name_dire") or "").strip()
        if not radiant_name or not dire_name:
            # No published identities — do not invent them.
            return None
        a_id = make_id(f"{PREFIX}-t", row.get("team_id_radiant") or slug(radiant_name, 30))
        b_id = make_id(f"{PREFIX}-t", row.get("team_id_dire") or slug(dire_name, 30))
        start = from_epoch(row.get("activate_time")) or utcnow()
        return Match(
            id=make_id(f"{PREFIX}-live-", row.get("match_id")),
            external_id=str(row.get("match_id")),
            game_id=GAME_ID,
            tournament_id=make_id(f"{PREFIX}-tour-", row.get("league_id") or "live"),
            series_id=make_id(f"{PREFIX}-live-", row.get("match_id")),
            status=MatchStatus.LIVE,
            scheduled_at=start,
            team_a_id=a_id,
            team_b_id=b_id,
            started_at=start,
            ended_at=None,
            best_of=1,
            current_map=None,
            map_number=1,
            score_a=safe_int(row.get("radiant_score")),
            score_b=safe_int(row.get("dire_score")),
            winner_id=None,
            source=SOURCE,
            source_timestamp=from_epoch(row.get("last_update_time")) or utcnow(),
            received_at=utcnow(),
            meta_data={
                "source": SOURCE,
                "data_mode": "LIVE",
                "game_time_seconds": safe_int(row.get("game_time")),
                "spectators": safe_int(row.get("spectators")),
                "average_mmr": safe_int(row.get("average_mmr")),
                "radiant_lead": safe_int(row.get("radiant_lead")),
                "team_names": {a_id: radiant_name, b_id: dire_name},
            },
        )

    async def _all_live(self) -> List[Dict[str, Any]]:
        data = await self._get_json("/live", ttl_seconds=25)
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    # ------------------------------------------------------------- interface
    async def get_games(self) -> List[Game]:
        return [
            Game(
                id=GAME_ID,
                external_id=GAME_ID,
                name="Dota 2",
                short_name="Dota2",
                source=SOURCE,
                meta_data={"genre": "MOBA", "publisher": "Valve", "data_mode": "LIVE"},
            )
        ]

    async def get_tournaments(self, game_id: str) -> List[Tournament]:
        if game_id != GAME_ID:
            return []
        rows = await self._all_pro_matches()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("leagueid") or slug(row.get("league_name") or "unknown"))
            grouped.setdefault(key, []).append(row)
        now = utcnow()
        out: List[Tournament] = []
        for key, games in grouped.items():
            starts = sorted(s for s in (from_epoch(g.get("start_time")) for g in games) if s is not None)
            start = starts[0] if starts else now
            end = starts[-1] if starts else None
            name = games[0].get("league_name") or f"League {key}"
            out.append(
                Tournament(
                    id=make_id(f"{PREFIX}-tour-", key),
                    external_id=key,
                    name=name,
                    game_id=GAME_ID,
                    start_date=start,
                    end_date=end,
                    prize_pool=None,
                    region=None,
                    status="completed" if end and end <= now else "upcoming",
                    meta_data={"source": SOURCE, "matches": len(games), "league_id": games[0].get("leagueid")},
                )
            )
        out.sort(key=lambda t: t.start_date, reverse=True)
        return out

    async def get_matches(self, game_id: str, tournament_id: Optional[str] = None) -> List[Match]:
        if game_id != GAME_ID:
            return []
        rows = await self._all_pro_matches()
        grouped = self._group_series(rows)
        mapped = [m for m in (self._map_series(g) for g in grouped) if m is not None]
        if tournament_id:
            mapped = [m for m in mapped if m.tournament_id == tournament_id]
        mapped.sort(key=lambda m: m.scheduled_at, reverse=True)
        return mapped

    async def _series_for(self, external: str) -> Optional[List[Dict[str, Any]]]:
        rows = await self._all_pro_matches()
        for games in self._group_series(rows):
            key = str(games[0].get("series_id") or f"m{games[0].get('match_id')}")
            if key == external or str(games[0].get("match_id")) == external:
                return games
        return None

    async def get_match(self, match_id: str) -> Optional[Match]:
        if match_id.startswith(f"{PREFIX}-live-"):
            external = match_id[len(f"{PREFIX}-live-"):]
            for row in await self._all_live():
                if str(row.get("match_id")) == external:
                    return self._map_live(row)
            return None
        if not match_id.startswith(f"{PREFIX}-m"):
            return None
        external = match_id[len(f"{PREFIX}-m"):]
        games = await self._series_for(external)
        if games:
            return self._map_series(games)
        # A live game id can also be requested without the live prefix.
        for row in await self._all_live():
            if str(row.get("match_id")) == external:
                return self._map_live(row)
        return None

    async def get_teams(self, game_id: str) -> List[Team]:
        if game_id != GAME_ID:
            return []
        rows = await self._all_pro_matches()
        teams: Dict[str, Team] = {}
        for row in rows:
            for tid, name in (
                (row.get("radiant_team_id"), row.get("radiant_name")),
                (row.get("dire_team_id"), row.get("dire_name")),
            ):
                if not name:
                    continue
                team = self._team_ref(tid, name)
                teams.setdefault(team.id, team)
        return list(teams.values())

    async def get_team(self, team_id: str) -> Optional[Team]:
        """Optional extra (not in the base interface): resolve a logo/region."""
        if not team_id.startswith(f"{PREFIX}-t"):
            return None
        external = team_id[len(f"{PREFIX}-t"):]
        try:
            data = await self._get_json(f"/teams/{external}", ttl_seconds=3600)
        except EsportsProviderError:
            return None
        if not isinstance(data, dict) or not data.get("name"):
            return None
        return Team(
            id=team_id,
            external_id=external,
            name=data.get("name"),
            short_name=(data.get("tag") or data.get("name")[:4]).upper(),
            game_id=GAME_ID,
            logo_url=data.get("logo_url") or None,
            region=None,
            meta_data={
                "source": SOURCE,
                "rating": data.get("rating"),
                "wins": data.get("wins"),
                "losses": data.get("losses"),
            },
        )

    async def get_players(self, team_id: str) -> List[Player]:
        if not team_id.startswith(f"{PREFIX}-t"):
            return []
        external = team_id[len(f"{PREFIX}-t"):]
        if not external.isdigit():
            return []
        try:
            roster = await self._get_json(f"/teams/{external}/players", ttl_seconds=3600)
        except EsportsProviderError:
            return []
        if not isinstance(roster, list):
            return []
        rows = [r for r in roster if isinstance(r, dict) and r.get("account_id")]

        async def _profile(account_id: int) -> Dict[str, Any]:
            try:
                return await self._get_json(f"/players/{account_id}", ttl_seconds=3600)
            except EsportsProviderError:
                return {}

        profiles = await asyncio.gather(*(_profile(r["account_id"]) for r in rows))
        players: List[Player] = []
        for row, profile in zip(rows, profiles):
            info = (profile or {}).get("profile") or {}
            handle = row.get("name") or info.get("personaname") or "unknown"
            players.append(
                Player(
                    id=make_id(f"{PREFIX}-p", row.get("account_id")),
                    external_id=str(row.get("account_id")),
                    name=info.get("name") or handle,
                    handle=handle,
                    team_id=team_id,
                    game_id=GAME_ID,
                    role=None,
                    country=info.get("country_code") or None,
                    meta_data={
                        "source": SOURCE,
                        "avatar_url": info.get("avatarfull") or info.get("avatarmedium"),
                        "games_played": row.get("games_played"),
                        "wins": row.get("wins"),
                        "is_current_team_member": row.get("is_current_team_member"),
                    },
                )
            )
        return players

    async def get_live_events(self, game_id: str) -> List[GameEvent]:
        if game_id != GAME_ID:
            return []
        try:
            rows = await self._all_live()
        except EsportsProviderError:
            return []
        events: List[GameEvent] = []
        for row in rows:
            match = self._map_live(row)
            if match is None:
                continue
            start = match.scheduled_at
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-start", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MATCH_STARTED,
                    timestamp=start,
                    sequence=1,
                    payload={"source": SOURCE},
                    source=SOURCE,
                    source_timestamp=start,
                )
            )
            events.append(
                GameEvent(
                    id=make_id(
                        f"{PREFIX}-e",
                        f"{match.external_id}-score-{match.score_a}-{match.score_b}",
                        max_length=48,
                    ),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.SCORE_CHANGED,
                    timestamp=utcnow(),
                    sequence=2 + match.score_a + match.score_b,
                    payload={
                        "team_a_score": match.score_a,
                        "team_b_score": match.score_b,
                        "team_a_name": (match.meta_data.get("team_names") or {}).get(match.team_a_id),
                        "team_b_name": (match.meta_data.get("team_names") or {}).get(match.team_b_id),
                        "game_time_seconds": match.meta_data.get("game_time_seconds"),
                    },
                    source=SOURCE,
                    source_timestamp=utcnow(),
                )
            )
        return events

    async def get_match_events(self, match_id: str) -> List[GameEvent]:
        match = await self.get_match(match_id)
        if match is None:
            return []
        events: List[GameEvent] = []
        games = (match.meta_data or {}).get("games") or []
        sequence = 0
        for index, game in enumerate(games):
            sequence += 1
            game_start = from_epoch(game.get("start_time")) or match.scheduled_at
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-g{index + 1}-start", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MAP_STARTED,
                    timestamp=game_start,
                    sequence=sequence,
                    payload={"map_number": index + 1, "game_id": game.get("match_id")},
                    source=SOURCE,
                    source_timestamp=game_start,
                )
            )
            sequence += 1
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-g{index + 1}-end", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MAP_ENDED,
                    timestamp=game_start,
                    sequence=sequence,
                    payload={
                        "map_number": index + 1,
                        "game_id": game.get("match_id"),
                        "duration_seconds": game.get("duration"),
                        "team_a_score": game.get("radiant_score"),
                        "team_b_score": game.get("dire_score"),
                        "winner_side": "a" if game.get("radiant_win") else "b",
                        "timestamp_precision": "game_start",
                    },
                    source=SOURCE,
                    source_timestamp=game_start,
                )
            )
        if match.status == MatchStatus.COMPLETED and games:
            sequence += 1
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-end", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MATCH_ENDED,
                    timestamp=match.source_timestamp or match.scheduled_at,
                    sequence=sequence,
                    payload={
                        "winner_id": match.winner_id,
                        "score_a": match.score_a,
                        "score_b": match.score_b,
                    },
                    source=SOURCE,
                    source_timestamp=match.source_timestamp or match.scheduled_at,
                )
            )
        # A live game's timeline is its running kill score.
        if match.status == MatchStatus.LIVE:
            sequence += 1
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-live-{match.score_a}-{match.score_b}", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.SCORE_CHANGED,
                    timestamp=utcnow(),
                    sequence=sequence,
                    payload={
                        "team_a_score": match.score_a,
                        "team_b_score": match.score_b,
                        "game_time_seconds": match.meta_data.get("game_time_seconds"),
                    },
                    source=SOURCE,
                    source_timestamp=utcnow(),
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
