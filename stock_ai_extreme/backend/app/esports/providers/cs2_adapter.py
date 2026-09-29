"""
Counter-Strike 2 provider adapter — Phase 21B real integration.

Source: https://api.csapi.de (public, no API key required).

The upstream publishes professional CS2 match results, world team rankings,
team rosters and aggregate player statistics, refreshed daily. It does **not**
publish round-by-round live telemetry, so this adapter never fabricates a live
state: matches are surfaced with the status the source actually supports
(COMPLETED results), carry a DELAYED data mode, and match events are derived
from the real per-map scores the source provides. A missing logo, country or
role stays ``None`` and the UI renders its labelled fallback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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

logger = logging.getLogger("neural_market.esports.providers.cs2")

PREFIX = "cs2"
GAME_ID = "cs2"
SOURCE = "csapi.de"
BASE_URL = "https://api.csapi.de"


class CS2Adapter(EsportsDataProvider):
    """Counter-Strike 2 adapter backed by the keyless csapi.de feed."""

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
                follow_redirects=True,
            )
        return self._client

    async def _get_json(self, endpoint: str, ttl_seconds: float) -> Any:
        """GET JSON with a TTL cache; raises EsportsProviderError on failure."""

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
            except Exception as exc:  # malformed JSON etc.
                self._metrics["error_count"] += 1
                self._metrics["last_error"] = str(exc)
                self._health_status = ProviderHealth.DEGRADED
                raise EsportsProviderError(self.provider_name, f"Request error: {exc}") from exc

        try:
            return await self._cache.get_or_set(endpoint, ttl_seconds, _fetch)
        except EsportsProviderError:
            # On a transient outage prefer the last good payload (still labelled
            # STALE/DELAYED downstream) over hard-failing the whole request.
            stale = self._cache.peek(endpoint)
            if stale is not None:
                return stale
            raise

    # -------------------------------------------------------------- mapping
    def _map_tournament(self, event: str, matches: List[Dict[str, Any]]) -> Tournament:
        event = event or "Unknown event"
        dates = sorted(m.get("date") for m in matches if m.get("date"))
        start = parse_iso(dates[0]) if dates else utcnow()
        end = parse_iso(dates[-1]) if dates else None
        now = utcnow()
        if end and end < now:
            status = "completed"
        elif start and start <= now <= (end or start):
            status = "live"
        else:
            status = "upcoming"
        return Tournament(
            id=make_id(f"{PREFIX}-tour-", slug(event)),
            external_id=event,
            name=event,
            game_id=GAME_ID,
            start_date=start,
            end_date=end,
            prize_pool=None,
            region=None,
            status=status,
            meta_data={"source": SOURCE, "matches": len(matches)},
        )

    def _map_team(self, team: Dict[str, Any]) -> Team:
        name = team.get("name") or "TBD"
        ext_id = str(team.get("id") or slug(name))
        return Team(
            id=make_id(f"{PREFIX}-t", ext_id),
            external_id=ext_id,
            name=name,
            short_name=(name[:4] if name else "TBD").upper(),
            game_id=GAME_ID,
            logo_url=None,  # csapi.de publishes no team logo
            region=None,
            meta_data={
                "source": SOURCE,
                "world_rank": safe_int(team.get("rank")) or None,
                "world_points": team.get("points"),
            },
        )

    def _map_match(self, raw: Dict[str, Any]) -> Optional[Match]:
        team1 = raw.get("team1") or {}
        team2 = raw.get("team2") or {}
        if not team1 or not team2:
            return None
        date_raw = raw.get("date")
        scheduled = parse_iso(date_raw) or utcnow()
        winner = raw.get("winner") or {}
        maps = raw.get("maps") or []
        # The source publishes finished results only; a future-dated row would
        # be UPCOMING, everything else COMPLETED. Nothing is labelled LIVE that
        # the source cannot confirm.
        status = MatchStatus.UPCOMING if scheduled > utcnow() else MatchStatus.COMPLETED
        current_map = maps[-1].get("name") if maps else None
        last_map_scores = maps[-1] if maps else {}
        winner_id = None
        if winner.get("id") is not None:
            winner_id = make_id(f"{PREFIX}-t", winner.get("id"))
        return Match(
            id=make_id(f"{PREFIX}-m", raw.get("id")),
            external_id=str(raw.get("id")),
            game_id=GAME_ID,
            tournament_id=make_id(f"{PREFIX}-tour-", slug(raw.get("event") or "")),
            series_id=make_id(f"{PREFIX}-s", raw.get("id")),
            status=status,
            scheduled_at=scheduled,
            team_a_id=make_id(f"{PREFIX}-t", team1.get("id")),
            team_b_id=make_id(f"{PREFIX}-t", team2.get("id")),
            started_at=scheduled,
            ended_at=scheduled if status == MatchStatus.COMPLETED else None,
            best_of=safe_int(raw.get("best_of"), 1) or 1,
            current_map=current_map,
            map_number=len(maps),
            score_a=safe_int(team1.get("score")),
            score_b=safe_int(team2.get("score")),
            winner_id=winner_id,
            source=SOURCE,
            source_timestamp=scheduled,
            received_at=utcnow(),
            meta_data={
                "source": SOURCE,
                "event": raw.get("event"),
                "data_mode": "DELAYED",
                "maps": [
                    {
                        "map_number": index + 1,
                        "name": m.get("name"),
                        "team_a_score": safe_int(m.get("team1_score")),
                        "team_b_score": safe_int(m.get("team2_score")),
                    }
                    for index, m in enumerate(maps)
                ],
                "team_names": {
                    make_id(f"{PREFIX}-t", team1.get("id")): team1.get("name"),
                    make_id(f"{PREFIX}-t", team2.get("id")): team2.get("name"),
                },
            },
        )

    # ------------------------------------------------------------- interface
    async def get_games(self) -> List[Game]:
        return [
            Game(
                id=GAME_ID,
                external_id=GAME_ID,
                name="Counter-Strike 2",
                short_name="CS2",
                source=SOURCE,
                meta_data={"genre": "FPS", "publisher": "Valve", "data_mode": "DELAYED"},
            )
        ]

    async def _all_matches(self) -> List[Dict[str, Any]]:
        data = await self._get_json("/matches/", ttl_seconds=300)
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    async def get_tournaments(self, game_id: str) -> List[Tournament]:
        if game_id != GAME_ID:
            return []
        matches = await self._all_matches()
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for match in matches:
            grouped.setdefault(match.get("event") or "Unknown event", []).append(match)
        return [self._map_tournament(name, rows) for name, rows in grouped.items()]

    async def get_matches(self, game_id: str, tournament_id: Optional[str] = None) -> List[Match]:
        if game_id != GAME_ID:
            return []
        matches = await self._all_matches()
        mapped = [m for m in (self._map_match(row) for row in matches) if m is not None]
        if tournament_id:
            mapped = [m for m in mapped if m.tournament_id == tournament_id]
        # Newest first — the honest "latest results" order the source uses.
        mapped.sort(key=lambda m: m.scheduled_at, reverse=True)
        return mapped

    async def get_match(self, match_id: str) -> Optional[Match]:
        if not match_id.startswith(f"{PREFIX}-m"):
            return None
        external = match_id[len(f"{PREFIX}-m"):]
        try:
            raw = await self._get_json(f"/matches/{external}", ttl_seconds=300)
        except EsportsProviderError:
            raw = None
        if isinstance(raw, dict) and raw.get("team1"):
            return self._map_match(raw)
        # Fall back to the list endpoint if a detail lookup isn't available.
        for row in await self._all_matches():
            if str(row.get("id")) == external:
                return self._map_match(row)
        return None

    async def get_teams(self, game_id: str) -> List[Team]:
        if game_id != GAME_ID:
            return []
        data = await self._get_json("/rankings", ttl_seconds=900)
        rows = data.get("rankings") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        return [self._map_team(row) for row in rows]

    async def get_team(self, team_id: str) -> Optional[Team]:
        """Optional extra (not in the base interface): resolve a ranked team."""
        if not team_id.startswith(f"{PREFIX}-t"):
            return None
        external = team_id[len(f"{PREFIX}-t"):]
        try:
            data = await self._get_json("/rankings", ttl_seconds=900)
        except EsportsProviderError:
            return None
        rows = data.get("rankings") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if str(row.get("id")) == external:
                    return self._map_team(row)
        return None

    async def get_players(self, team_id: str) -> List[Player]:
        if not team_id.startswith(f"{PREFIX}-t"):
            return []
        external = team_id[len(f"{PREFIX}-t"):]
        try:
            data = await self._get_json(f"/teams/{external}", ttl_seconds=900)
        except EsportsProviderError:
            return []
        roster = data.get("roster") if isinstance(data, dict) else None
        if not isinstance(roster, list):
            return []
        # Phase 21C §5: join the published per-player statistics so the
        # analytics layer can report real CS2 metrics (rating/ADR/KAST/K/D).
        stats_by_id = await self._player_stats()
        players: List[Player] = []
        for row in roster:
            pid = make_id(f"{PREFIX}-p", row.get("id"))
            stats = stats_by_id.get(str(row.get("id")), {})
            players.append(
                Player(
                    id=pid,
                    external_id=str(row.get("id")),
                    name=row.get("name") or "Unknown player",
                    handle=row.get("name") or "unknown",
                    team_id=team_id,
                    game_id=GAME_ID,
                    role=None,
                    country=None,
                    meta_data={
                        "source": SOURCE,
                        "rating": stats.get("rating"),
                        "adr": stats.get("adr"),
                        "kast": stats.get("kast"),
                        "k": stats.get("k"),
                        "d": stats.get("d"),
                        "maps_played": stats.get("N"),
                        "stats_sample": "provider aggregate",
                    },
                )
            )
        return players

    async def _player_stats(self) -> Dict[str, Dict[str, Any]]:
        """Top-player statistics keyed by provider player id (cached)."""
        try:
            data = await self._get_json("/players/stats", ttl_seconds=900)
        except EsportsProviderError:
            return {}
        if not isinstance(data, list):
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        for row in data:
            if isinstance(row, dict) and row.get("id") is not None:
                result[str(row["id"])] = row
        return result

    async def get_live_events(self, game_id: str) -> List[GameEvent]:
        # csapi.de publishes no live telemetry; returning [] (not a made-up
        # event) is the honest answer and the UI shows its empty state.
        return []

    async def get_match_events(self, match_id: str) -> List[GameEvent]:
        match = await self.get_match(match_id)
        if match is None:
            return []
        events: List[GameEvent] = []
        base = match.source_timestamp or match.scheduled_at
        maps = (match.meta_data or {}).get("maps") or []
        sequence = 0
        for index, m in enumerate(maps):
            sequence += 1
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-ms{index + 1}", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MAP_STARTED,
                    timestamp=base,
                    sequence=sequence,
                    team_id=None,
                    player_id=None,
                    payload={
                        "map_number": m.get("map_number"),
                        "map_name": m.get("name"),
                        "timestamp_precision": "date",
                    },
                    source=SOURCE,
                    source_timestamp=base,
                )
            )
            sequence += 1
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-me{index + 1}", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MAP_ENDED,
                    timestamp=base,
                    sequence=sequence,
                    team_id=None,
                    player_id=None,
                    payload={
                        "map_number": m.get("map_number"),
                        "map_name": m.get("name"),
                        "team_a_score": m.get("team_a_score"),
                        "team_b_score": m.get("team_b_score"),
                        "timestamp_precision": "date",
                    },
                    source=SOURCE,
                    source_timestamp=base,
                )
            )
        if match.status == MatchStatus.COMPLETED:
            sequence += 1
            events.append(
                GameEvent(
                    id=make_id(f"{PREFIX}-e", f"{match.external_id}-end", max_length=48),
                    match_id=match.id,
                    game_id=GAME_ID,
                    type=EventType.MATCH_ENDED,
                    timestamp=base,
                    sequence=sequence,
                    payload={
                        "winner_id": match.winner_id,
                        "score_a": match.score_a,
                        "score_b": match.score_b,
                        "timestamp_precision": "date",
                    },
                    source=SOURCE,
                    source_timestamp=base,
                )
            )
        return events

    async def subscribe_to_match(self, match_id: str, callback) -> None:  # pragma: no cover - no push feed
        return None

    async def unsubscribe_from_match(self, match_id: str) -> None:  # pragma: no cover - no push feed
        return None

    def get_provider_name(self) -> str:
        return self.provider_name

    async def get_provider_health(self) -> ProviderHealth:
        return self._health_status

    async def get_provider_metrics(self) -> Dict[str, Any]:
        return {**self._metrics, "source": SOURCE, "data_mode": "DELAYED", "refresh": "daily"}

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
