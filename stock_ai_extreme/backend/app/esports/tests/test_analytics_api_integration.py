"""
Phase 21C §15 — analytics API integration test.

Drives the real ``/api/v1/esports`` router through the real
``EsportsAnalyticsService`` with deterministic in-memory providers, so the
serialization, the caching layer, the validation rules and the Prometheus
exposition are all exercised without a network call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.esports.analytics.routes import analytics_router
from app.esports.analytics.service import analytics_service
from app.esports.analytics.store import analytics_store
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
from app.esports.services.manager import EsportsDataManager

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

TEAM_A = "cs2-t7020"
TEAM_B = "cs2-t11283"


def _match(mid: str, *, status: MatchStatus = MatchStatus.COMPLETED,
           minutes_ago: int = 60, score: tuple[int, int] = (2, 1)) -> Match:
    scheduled = NOW - timedelta(minutes=minutes_ago)
    return Match(
        id=mid,
        external_id=mid,
        game_id="cs2",
        tournament_id="cs2-tour-1",
        series_id=f"{mid}-series",
        status=status,
        scheduled_at=scheduled,
        team_a_id=TEAM_A,
        team_b_id=TEAM_B,
        started_at=scheduled,
        ended_at=scheduled if status == MatchStatus.COMPLETED else None,
        best_of=3,
        current_map="Ancient",
        map_number=2,
        score_a=score[0],
        score_b=score[1],
        winner_id=TEAM_A if score[0] > score[1] else TEAM_B,
        source="csapi.de",
        source_timestamp=scheduled,
        received_at=NOW,
        meta_data={
            "source": "csapi.de",
            "league": "BLAST Open Porto 2026",
            "data_mode": "DELAYED",
            "team_names": {TEAM_A: "Spirit", TEAM_B: "Falcons"},
            "maps": [
                {"map_number": 1, "name": "Nuke", "team_a_score": 13, "team_b_score": 8},
                {"map_number": 2, "name": "Ancient", "team_a_score": 11, "team_b_score": 13},
            ],
        },
    )


class FakeCS2Provider(EsportsDataProvider):
    def __init__(self) -> None:
        self._matches = [_match(f"cs2-m{i}", minutes_ago=60 * i) for i in range(1, 6)]

    async def get_games(self):
        return [Game(id="cs2", external_id="cs2", name="Counter-Strike 2", short_name="CS2", source="csapi.de")]

    async def get_tournaments(self, game_id):
        return [
            Tournament(id="cs2-tour-1", external_id="tour-1", name="BLAST", game_id=game_id,
                        start_date=NOW - timedelta(days=1), end_date=NOW, status="completed",
                        meta_data={"source": "csapi.de"})
        ]

    async def get_matches(self, game_id, tournament_id=None):
        return [m for m in self._matches if m.game_id == game_id]

    async def get_match(self, match_id):
        return next((m for m in self._matches if m.id == match_id), None)

    async def get_teams(self, game_id):
        return [Team(id=TEAM_A, external_id="7020", name="Spirit", short_name="SPIR", game_id="cs2")]

    async def get_team(self, team_id):
        return None

    async def get_players(self, team_id):
        if team_id != TEAM_A:
            return []
        return [
            Player(id="cs2-p21167", external_id="21167", name="donk", handle="donk", team_id=TEAM_A,
                   game_id="cs2", meta_data={"source": "csapi.de", "rating": 1.51, "adr": 96.0,
                                             "kast": 77.6, "k": 754, "d": 541})
        ]

    async def get_live_events(self, game_id):
        return []

    async def get_match_events(self, match_id):
        return [
            GameEvent(id=f"{match_id}-e1", match_id=match_id, game_id="cs2", type=EventType.MAP_STARTED,
                      timestamp=NOW, sequence=1, payload={"map_name": "Nuke"}, source="csapi.de"),
            GameEvent(id=f"{match_id}-e2", match_id=match_id, game_id="cs2", type=EventType.MAP_ENDED,
                      timestamp=NOW + timedelta(seconds=5), sequence=2, payload={}, source="csapi.de"),
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
        return {"request_count": 4, "error_count": 0, "last_success": NOW.isoformat(),
                "avg_latency_ms": 30.0, "data_mode": "DELAYED", "refresh": "daily"}


@pytest.fixture(autouse=True)
def _clean_cache():
    """The analytics cache is a process singleton; never leak it between tests."""
    analytics_store.invalidate()
    yield
    analytics_store.invalidate()


def _client() -> TestClient:
    manager = EsportsDataManager([FakeCS2Provider()])
    manager._load_snapshot_from_db = lambda match_id: None  # type: ignore[assignment]
    analytics_service.configure(manager)
    app = FastAPI()
    app.include_router(analytics_router)
    return TestClient(app)


def test_engine_endpoint_discloses_the_model():
    body = _client().get("/api/v1/esports/analytics/engine").json()
    assert body["trending_weights"]["live"] == pytest.approx(0.35)
    assert body["saturation"] > 0
    assert "cs2" in body["player_metric_schema"]


def test_trending_games_returns_measured_signals():
    body = _client().get("/api/v1/esports/trending/games").json()
    assert body["games"]
    row = body["games"][0]
    assert row["game_id"] == "cs2"
    assert row["live_matches"] == 0  # every fake match is completed
    assert row["signals"]["viewer"] is None  # never invented
    assert "confidence" in row and "score" in row
    assert body["engine"]["weights"]["live"] == pytest.approx(0.35)


def test_trending_matches_discloses_its_weights_and_paginates():
    body = _client().get("/api/v1/esports/trending/matches", params={"limit": 2}).json()
    assert body["selection"]["weights"]["live_state"] == pytest.approx(0.45)
    assert body["limit"] == 2
    assert len(body["matches"]) <= 2


def test_data_quality_reports_an_aggregate_label():
    body = _client().get("/api/v1/esports/data-quality").json()
    assert body["aggregate"]["label"] in ("HIGH", "MEDIUM", "LOW", "UNAVAILABLE")
    assert body["matches"][0]["source"] == "csapi.de"


def test_team_analytics_uses_real_per_map_records():
    body = _client().get(f"/api/v1/esports/analytics/team/{TEAM_A}").json()
    assert body["form"]["value"]["wins"] >= 1
    assert body["map_analytics"]["available"] is True
    maps = {entry["map"] for entry in body["map_analytics"]["maps"]}
    assert maps == {"Nuke", "Ancient"}


def test_match_analytics_includes_anomaly_scan_and_team_form():
    body = _client().get("/api/v1/esports/analytics/match/cs2-m1").json()
    assert body["match_id"] == "cs2-m1"
    assert body["anomaly_detection"]["label"] in ("ANOMALY DETECTED", "NO ANOMALY")
    assert body["team_a"]["form"]["value"]["wins"] >= 1


def test_match_analytics_unknown_is_404():
    assert _client().get("/api/v1/esports/analytics/match/does-not-exist").status_code == 404


def test_player_analytics_resolves_within_the_bounded_scan():
    body = _client().get("/api/v1/esports/analytics/player/cs2-p21167").json()
    assert body["game_id"] == "cs2"
    assert body["players"][0]["handle"] == "donk"
    assert body["metric_schema"] == ["rating", "adr", "kast", "k", "d", "kd_ratio"]


def test_observability_reports_the_cache_backend():
    body = _client().get("/api/v1/esports/observability").json()
    assert body["observability"]["analytics_store"]["backend"] == "in-process-async-ttl"
    assert body["manager_stats"] is not None


def test_prometheus_exposition_is_scrapeable_text():
    text = _client().get("/api/v1/esports/metrics/prometheus").text
    assert "# TYPE esports_connected_clients gauge" in text
    assert "esports_connected_clients " in text


def test_interest_recording_accepts_real_signals_only():
    client = _client()
    ok = client.post("/api/v1/esports/interest", json={"game_id": "cs2", "kind": "view"})
    assert ok.status_code == 200 and ok.json()["recorded"] is True

    bad_kind = client.post("/api/v1/esports/interest", json={"game_id": "cs2", "kind": "bet"})
    assert bad_kind.status_code == 422

    bad_game = client.post("/api/v1/esports/interest", json={"game_id": "overwatch", "kind": "view"})
    assert bad_game.status_code == 400


def test_identifiers_are_validated_before_reaching_a_provider():
    client = _client()
    assert client.get("/api/v1/esports/analytics/team/id;drop").status_code == 400
    assert client.get("/api/v1/esports/analytics/team/valid-id", params={"game_id": "overwatch"}).status_code == 400
