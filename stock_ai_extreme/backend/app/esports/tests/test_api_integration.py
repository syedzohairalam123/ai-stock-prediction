"""
Phase 21B §22 — real esports API integration test.

Unlike the pure unit tests, this drives the **actual FastAPI routes**
(`app.esports.routes`) through the **actual `EsportsDataManager`** and the
WebSocket gateway, with deterministic in-memory providers standing in for the
three real sources. That exercises the parts a unit test cannot: route wiring,
query-parameter parsing, response serialization, match-detail assembly (teams +
players + events + snapshot), provider-health reporting and the WebSocket
subscribe/snapshot protocol.

It is hermetic on purpose — no network call and no database round-trip:
the manager's snapshot lookup is served from a seeded in-memory state engine and
its persistence hook is stubbed, so the DB is never touched. That lets the
WebSocket broadcast test push a genuinely normalized event through the real
`EsportsDataManager.process_live_event` pipeline and prove it reaches only the
client subscribed to that match.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.esports.providers.base import (
    EsportsDataProvider,
    EventType,
    Game,
    GameEvent,
    Match,
    MatchStatus,
    Player,
    ProviderHealth,
    Team,
    Tournament,
)
from app.esports.routes import configure_esports, esports_router
from app.esports.services.manager import EsportsDataManager
from app.esports.state.event_engine import MatchStateEngine
from app.esports.websocket.manager import esports_ws_manager

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# deterministic providers
# ---------------------------------------------------------------------------
def _match(mid: str, status: MatchStatus, *, game: str = "cs2", minutes_ago: int = 30,
           score: tuple[int, int] = (2, 1), maps: list | None = None) -> Match:
    scheduled = NOW - timedelta(minutes=minutes_ago)
    meta = {
        "team_names": {"ta": "Alpha", "tb": "Beta"},
        "league": "Integration Cup",
        "data_mode": "LIVE" if status == MatchStatus.LIVE else "DELAYED",
    }
    if maps is not None:
        meta["maps"] = maps
    return Match(
        id=mid,
        external_id=mid,
        game_id=game,
        tournament_id="cs2-tour-1",
        series_id=f"{mid}-series",
        status=status,
        scheduled_at=scheduled,
        team_a_id="ta",
        team_b_id="tb",
        started_at=scheduled,
        ended_at=scheduled if status == MatchStatus.COMPLETED else None,
        best_of=3,
        current_map="Nuke",
        map_number=2,
        score_a=score[0],
        score_b=score[1],
        winner_id="ta" if status == MatchStatus.COMPLETED and score[0] > score[1] else None,
        source="csapi.de",
        source_timestamp=scheduled,
        received_at=NOW,
        meta_data=meta,
    )


class FakeCS2Provider(EsportsDataProvider):
    """In-memory stand-in with the same contract as the real CS2 adapter."""

    def __init__(self, matches):
        self._matches = matches
        self._games = [
            Game(id="cs2", external_id="cs2", name="Counter-Strike 2", short_name="CS2", source="csapi.de")
        ]
        self._teams = [
            Team(id="ta", external_id="ta", name="Alpha", short_name="ALP", game_id="cs2",
                 logo_url=None, region="EU", meta_data={"current_win_streak": 7}),
            Team(id="tb", external_id="tb", name="Beta", short_name="BET", game_id="cs2"),
        ]

    async def get_games(self):
        return self._games

    async def get_tournaments(self, game_id):
        return [
            Tournament(id="cs2-tour-1", external_id="tour-1", name="Integration Cup", game_id=game_id,
                        start_date=NOW - timedelta(days=1), end_date=NOW, status="completed")
        ]

    async def get_matches(self, game_id, tournament_id=None):
        return [m for m in self._matches if m.game_id == game_id]

    async def get_match(self, match_id):
        return next((m for m in self._matches if m.id == match_id), None)

    async def get_teams(self, game_id):
        return self._teams

    async def get_team(self, team_id):
        return next((t for t in self._teams if t.id == team_id), None)

    async def get_players(self, team_id):
        return [
            Player(id="p1", external_id="p1", name="p one", handle="p1", team_id="ta", game_id="cs2",
                   meta_data={"rating": 1.24, "adr": 82.5, "source": "csapi.de"})
        ]

    async def get_live_events(self, game_id):
        return []

    async def get_match_events(self, match_id):
        return [
            GameEvent(id=f"{match_id}-e1", match_id=match_id, game_id="cs2", type=EventType.MAP_STARTED,
                      timestamp=NOW, sequence=1, payload={"map_name": "Nuke"}, source="csapi.de"),
            GameEvent(id=f"{match_id}-e2", match_id=match_id, game_id="cs2", type=EventType.SCORE_CHANGED,
                      timestamp=NOW, sequence=2, payload={"team_a_score": 2, "team_b_score": 1},
                      source="csapi.de"),
        ]

    async def subscribe_to_match(self, match_id, callback):
        return None

    async def unsubscribe_from_match(self, match_id):
        return None

    def get_provider_name(self):
        return "csapi.de"

    async def get_provider_health(self):
        return ProviderHealth.AVAILABLE

    async def get_provider_metrics(self):
        return {"request_count": 5, "error_count": 0, "last_success": NOW.isoformat(),
                "avg_latency_ms": 42.0, "data_mode": "LIVE", "refresh": "realtime"}


async def _noop_persist(_event) -> None:
    return None


def _build() -> tuple[FastAPI, EsportsDataManager]:
    live = _match("cs2-m1", MatchStatus.LIVE, minutes_ago=5, score=(1, 0))
    done = _match("cs2-m2", MatchStatus.COMPLETED, minutes_ago=90)
    manager = EsportsDataManager([FakeCS2Provider([live, done])])
    # Hermetic: snapshots come from seeded state engines and persistence is a
    # no-op, so the DB is never opened by this suite.
    manager._load_snapshot_from_db = lambda match_id: None  # type: ignore[assignment]
    manager._persist_event = _noop_persist  # type: ignore[assignment]
    manager.state_engines["cs2-m1"] = MatchStateEngine(live)
    manager.state_engines["cs2-m2"] = MatchStateEngine(done)
    configure_esports(manager)

    app = FastAPI()
    app.include_router(esports_router)
    return app, manager


def _client() -> TestClient:
    app, _manager = _build()
    return TestClient(app)


def _reset_ws_manager() -> None:
    """Never leak a test client into the process-wide WebSocket singleton."""
    esports_ws_manager.active_connections.clear()
    esports_ws_manager.channel_subscribers.clear()
    esports_ws_manager.connection_metadata.clear()
    esports_ws_manager.heartbeat_tasks.clear()


def _event(eid: str, match_id: str, *, sequence: int, score: tuple[int, int] = (1, 0)) -> GameEvent:
    """A normalized score event, exactly as an adapter would emit it."""
    return GameEvent(
        id=eid,
        match_id=match_id,
        game_id="cs2",
        type=EventType.SCORE_CHANGED,
        timestamp=NOW,
        sequence=sequence,
        payload={"team_a_score": score[0], "team_b_score": score[1]},
        source="csapi.de",
        source_timestamp=NOW,
    )


# ---------------------------------------------------------------------------
# REST surface
# ---------------------------------------------------------------------------
def test_games_endpoint_returns_the_provider_games():
    client = _client()
    body = client.get("/api/esports/games").json()
    assert body["count"] == 1
    assert body["games"][0]["id"] == "cs2"


def test_featured_match_prefers_the_live_game():
    client = _client()
    body = client.get("/api/esports/featured").json()
    assert body["featured"]["id"] == "cs2-m1"
    assert body["featured"]["status"] == "LIVE"
    assert body["featured"]["source"] == "csapi.de"


def test_match_feed_filters_live_only():
    client = _client()
    body = client.get("/api/esports/matches", params={"live": True}).json()
    assert body["total"] == 1
    assert body["matches"][0]["id"] == "cs2-m1"


def test_match_detail_assembles_teams_players_events_and_snapshot():
    client = _client()
    detail = client.get("/api/esports/matches/cs2-m1/detail").json()
    assert detail["team_a"]["name"] == "Alpha"
    assert detail["players"]["team_a"][0]["handle"] == "p1"
    assert detail["event_count"] == 2
    assert detail["events"][0]["type"] == "MAP_STARTED"
    assert detail["data_sources"][0]["name"] == "csapi.de"
    # Real provider metadata (the CS2 streak) flows all the way to the payload.
    assert detail["team_a"]["metadata"]["current_win_streak"] == 7


def test_match_events_endpoint_is_sequenced():
    client = _client()
    body = client.get("/api/esports/matches/cs2-m1/events").json()
    assert [event["sequence"] for event in body["events"]] == [1, 2]


def test_tournament_detail_lists_related_matches():
    client = _client()
    body = client.get("/api/esports/tournaments/cs2-tour-1").json()
    assert body["name"] == "Integration Cup"
    assert body["match_count"] == 2


def test_game_summary_counts_are_literal():
    client = _client()
    body = client.get("/api/esports/games/summary").json()
    counts = body["games"][0]["counts"]
    assert counts["live"] == 1
    assert counts["recent"] == 1
    assert counts["total"] == 2


def test_unknown_match_is_a_404():
    client = _client()
    assert client.get("/api/esports/matches/nope").status_code == 404


def test_sources_reports_provider_health():
    client = _client()
    body = client.get("/api/esports/sources").json()
    assert body["providers"][0]["status"] == "AVAILABLE"


def test_health_endpoint_reports_ok():
    client = _client()
    body = client.get("/api/esports/health").json()
    assert body["status"] == "ok"
    assert body["stats"]["provider_errors"] == 0


# ---------------------------------------------------------------------------
# WebSocket protocol
# ---------------------------------------------------------------------------
def test_websocket_subscribe_delivers_a_snapshot_and_scopes_the_channel():
    client = _client()
    try:
        with client.websocket_connect("/api/esports/ws/int-a") as ws:
            assert ws.receive_json()["type"] == "connected"
            ws.send_json({"type": "subscribe", "match_id": "cs2-m1"})
            assert ws.receive_json()["type"] == "subscription_confirmed"
            # Subscribing pushes the current snapshot immediately (snapshot+event model).
            initial = ws.receive_json()
            assert initial["type"] == "snapshot"
            assert initial["data"]["match_id"] == "cs2-m1"

            # The subscription is scoped to exactly this client + channel.
            assert esports_ws_manager.get_channel_subscribers("esports:match:cs2-m1") == {"int-a"}
            # And a different match's channel stays empty for this client.
            assert esports_ws_manager.get_channel_subscribers("esports:match:cs2-m2") == set()

            # An explicit snapshot request answers on demand (reconnect recovery).
            ws.send_json({"type": "snapshot", "match_id": "cs2-m1"})
            frame = ws.receive_json()
            assert frame["type"] == "snapshot"
            assert frame["data"]["match_id"] == "cs2-m1"

            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
    finally:
        _reset_ws_manager()


def test_websocket_broadcast_reaches_only_the_subscribed_match():
    """A real normalized event fans out to the subscriber of that match only."""
    app, manager = _build()
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/api/esports/ws/client-a") as a, client.websocket_connect(
                "/api/esports/ws/client-b"
            ) as b:
                assert a.receive_json()["type"] == "connected"
                assert b.receive_json()["type"] == "connected"

                a.send_json({"type": "subscribe", "match_id": "cs2-m1"})
                assert a.receive_json()["type"] == "subscription_confirmed"
                assert a.receive_json()["type"] == "snapshot"

                b.send_json({"type": "subscribe", "match_id": "cs2-m2"})
                assert b.receive_json()["type"] == "subscription_confirmed"
                assert b.receive_json()["type"] == "snapshot"

                # Push a real event for match 1 through the live pipeline.
                client.portal.call(manager.process_live_event, _event("evt-a", "cs2-m1", sequence=10))

                frame = a.receive_json()
                assert frame["type"] == "event"
                assert frame["data"]["id"] == "evt-a"
                assert frame["channel"] == "esports:match:cs2-m1"

                # Push a real event for match 2; client B sees this one.
                client.portal.call(manager.process_live_event, _event("evt-b", "cs2-m2", sequence=11))

                frame = b.receive_json()
                assert frame["type"] == "event"
                assert frame["data"]["id"] == "evt-b"
                assert frame["channel"] == "esports:match:cs2-m2"

                # Isolation proof: A's next frame is its own m1 snapshot, never
                # the m2 event it was not subscribed to.
                next_for_a = a.receive_json()
                assert next_for_a["type"] == "snapshot"
                assert esports_ws_manager.get_channel_subscribers("esports:match:cs2-m1") == {"client-a"}
                assert esports_ws_manager.get_channel_subscribers("esports:match:cs2-m2") == {"client-b"}
    finally:
        _reset_ws_manager()
