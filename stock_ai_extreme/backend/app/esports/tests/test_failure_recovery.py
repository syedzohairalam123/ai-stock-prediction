"""
Phase 21C §19, §20 — failure recovery and data-integrity tests.

Each test simulates a real failure mode and asserts the system degrades in a
*documented* way: it either recovers, reports the failure, or refuses the input —
it never corrupts match state and never invents data to cover the gap.

Simulated failures:
    provider down · cache/Redis down · database unavailable · WebSocket outage ·
    network interruption · malformed event · duplicate event · out-of-order
    event · correction event · provider latency spike · reconnect storm
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.esports.analytics.data_quality import evaluate_data_quality
from app.esports.providers.base import (
    EsportsDataProvider,
    EsportsProviderError,
    EventType,
    Game,
    GameEvent,
    Match,
    MatchStatus,
    ProviderHealth,
    Team,
)
from app.esports.services.event_deduplication import EventDeduplicationService
from app.esports.services.manager import EsportsDataManager
from app.esports.state.event_engine import MatchStateEngine
from app.esports.websocket.manager import EsportsWebSocketManager

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class FlakyProvider(EsportsDataProvider):
    """A provider whose every failure mode can be switched on."""

    def __init__(self, name="csapi.de", game="cs2"):
        self._name = name
        self._game = game
        self.down = False
        self.slow_seconds = 0.0
        self.requests = 0
        self.errors = 0

    def _guard(self):
        self.requests += 1
        if self.down:
            self.errors += 1
            raise EsportsProviderError(f"{self._name} is unavailable")

    async def get_games(self):
        self._guard()
        return [Game(id=self._game, external_id=self._game, name="Counter-Strike 2",
                     short_name="CS2", source=self._name)]

    async def get_tournaments(self, game_id):
        self._guard()
        return []

    async def get_matches(self, game_id, tournament_id=None):
        self._guard()
        if self.slow_seconds:
            await asyncio.sleep(self.slow_seconds)
        return [_match("m1")]

    async def get_match(self, match_id):
        self._guard()
        return _match(match_id) if match_id == "m1" else None

    async def get_teams(self, game_id):
        self._guard()
        return [Team(id="ta", external_id="ta", name="Alpha", short_name="ALP", game_id=self._game),
                Team(id="tb", external_id="tb", name="Beta", short_name="BET", game_id=self._game)]

    async def get_players(self, team_id):
        self._guard()
        return []

    async def get_live_events(self, game_id):
        self._guard()
        return []

    async def get_match_events(self, match_id):
        self._guard()
        return []

    async def subscribe_to_match(self, match_id, callback):
        return None

    async def unsubscribe_from_match(self, match_id):
        return None

    def get_provider_name(self):
        return self._name

    async def get_provider_health(self):
        return ProviderHealth.DOWN if self.down else ProviderHealth.AVAILABLE

    async def get_provider_metrics(self):
        return {"request_count": self.requests, "error_count": self.errors, "data_mode": "LIVE"}


def _match(mid="m1", status=MatchStatus.LIVE) -> Match:
    return Match(
        id=mid, external_id=mid, game_id="cs2", tournament_id="t1", series_id="s1",
        status=status, scheduled_at=NOW - timedelta(minutes=5), team_a_id="ta", team_b_id="tb",
        started_at=NOW - timedelta(minutes=5), ended_at=None, best_of=3, current_map="Mirage",
        map_number=1, score_a=1, score_b=0, winner_id=None, source="csapi.de",
        source_timestamp=NOW, received_at=NOW,
        meta_data={"team_names": {"ta": "Alpha", "tb": "Beta"}, "league": "Test League", "data_mode": "LIVE"},
    )


def _event(eid="e1", sequence=1, event_type=EventType.SCORE_CHANGED, payload=None, match_id="m1") -> GameEvent:
    """A normalized provider event, exactly as an adapter would hand it over."""
    stamp = NOW + timedelta(seconds=sequence)
    return GameEvent(
        id=eid,
        match_id=match_id,
        game_id="cs2",
        type=event_type,
        timestamp=stamp,
        sequence=sequence,
        payload=payload if payload is not None else {"team_a_score": 1, "team_b_score": 0},
        source="csapi.de",
        source_timestamp=stamp,
        received_at=stamp,
    )


class FakeSocket:
    """A WebSocket stand-in that can be told to fail on send."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list = []

    async def accept(self):
        if self.fail:
            raise RuntimeError("socket refused")

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("socket is dead")
        self.sent.append(message)


# ===========================================================================
# §19 — provider failures
# ===========================================================================

class TestProviderFailures:
    @pytest.mark.asyncio
    async def test_provider_down_yields_an_empty_feed_not_an_exception(self):
        provider = FlakyProvider()
        manager = EsportsDataManager([provider])
        assert len(await manager.get_matches("cs2")) == 1
        provider.down = True
        assert await manager.get_matches("cs2") == []
        assert await manager.get_games() == []
        assert manager.get_stats()["provider_errors"] >= 1

    @pytest.mark.asyncio
    async def test_provider_down_is_reported_as_down_health(self):
        provider = FlakyProvider()
        manager = EsportsDataManager([provider])
        provider.down = True
        await manager.get_matches("cs2")  # a real failed call
        report = await manager.provider_health_report()
        assert report[0]["status"] == "DOWN"
        assert report[0]["error_count"] >= 1

    @pytest.mark.asyncio
    async def test_one_provider_down_does_not_blank_the_others(self):
        healthy = FlakyProvider("lolesports.com", "lol")
        broken = FlakyProvider("csapi.de", "cs2")
        broken.down = True
        manager = EsportsDataManager([healthy, broken])
        games = await manager.get_games()
        assert [game.id for game in games] == ["lol"]
        report = {row["name"]: row["status"] for row in await manager.provider_health_report()}
        assert report == {"lolesports.com": "AVAILABLE", "csapi.de": "DOWN"}

    @pytest.mark.asyncio
    async def test_provider_latency_spike_does_not_corrupt_later_reads(self):
        provider = FlakyProvider()
        manager = EsportsDataManager([provider])
        provider.slow_seconds = 0.05
        assert len(await manager.get_matches("cs2")) == 1
        provider.slow_seconds = 0.0
        assert len(await manager.get_matches("cs2")) == 1

    @pytest.mark.asyncio
    async def test_provider_failure_marks_quality_low_with_a_reason(self):
        provider = FlakyProvider()
        provider.down = True
        report = await EsportsDataManager([provider]).provider_health_report()
        result = evaluate_data_quality(_match(), providers=report, now=NOW)
        assert result["provider_status"] == "DOWN"
        # §25: a down provider can never grade HIGH, however fresh the last
        # record it managed to send looked.
        assert result["label"] == "LOW"
        assert any("DOWN" in reason for reason in result["reasons"])


# ===========================================================================
# §19 — cache / database outages
# ===========================================================================

class TestCacheAndDatabaseOutages:
    @pytest.mark.asyncio
    async def test_cache_backend_failure_falls_through_to_live_state(self):
        manager = EsportsDataManager([FlakyProvider()])
        engine = MatchStateEngine(_match())
        manager.state_engines["m1"] = engine

        class DeadCache:
            async def get(self, _key):
                raise RuntimeError("cache backend down")

            async def set(self, *_args, **_kwargs):
                raise RuntimeError("cache backend down")

        manager.live_match_cache = DeadCache()
        # The cache is an optimisation, not the source of truth: a cache outage
        # must not break the live snapshot path or corrupt the state it returns.
        snapshot = await manager.get_live_snapshot("m1")
        assert snapshot is not None
        assert snapshot.match_id == "m1"
        assert snapshot.score_a == engine.get_current_snapshot().score_a

    @pytest.mark.asyncio
    async def test_database_outage_returns_unavailable_not_an_exception(self, monkeypatch):
        manager = EsportsDataManager([FlakyProvider()])

        def exploding(**_kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr("app.esports.services.manager.session_scope", exploding)
        # Nothing castable is available: report UNAVAILABLE (None), never invent one.
        assert await manager.get_live_snapshot("unknown-match") is None

    @pytest.mark.asyncio
    async def test_healthy_cache_serves_and_refreshes_snapshots(self):
        manager = EsportsDataManager([FlakyProvider()])
        manager.state_engines["m1"] = MatchStateEngine(_match())
        first = await manager.get_live_snapshot("m1")
        second = await manager.get_live_snapshot("m1")
        assert first is not None and second is not None
        assert second.match_id == "m1"

    @pytest.mark.asyncio
    async def test_event_persistence_failure_is_contained(self, monkeypatch):
        """A database outage must not stop live event processing (§19)."""
        manager = EsportsDataManager([FlakyProvider()])
        manager.state_engines["m1"] = MatchStateEngine(_match())

        def exploding_session():
            raise RuntimeError("database unavailable")

        monkeypatch.setattr("app.esports.services.manager.session_scope", exploding_session)
        await manager.process_live_event(_event("db-1", sequence=1, payload={"team_a_score": 4, "team_b_score": 2}))
        # The event still applied to live state: persistence failed, but the
        # in-memory pipeline and the snapshot the client reads are intact.
        assert manager.get_stats()["total_events_processed"] == 1
        snapshot = manager.state_engines["m1"].get_current_snapshot()
        assert snapshot.score_a == 4
        assert snapshot.score_b == 2


# ===========================================================================
# §19 — WebSocket outages and reconnect storms
# ===========================================================================

class TestWebSocketFailures:
    @pytest.mark.asyncio
    async def test_broadcast_to_a_dead_socket_disconnects_it_without_raising(self):
        manager = EsportsWebSocketManager()
        await manager.connect(FakeSocket(), "alive")
        await manager.connect(FakeSocket(), "dead")
        await manager.subscribe_to_channel("alive", "esports:all")
        await manager.subscribe_to_channel("dead", "esports:all")
        manager.active_connections["dead"].fail = True

        await manager.broadcast_to_channel("esports:all", {"type": "event", "data": {}})

        assert "dead" not in manager.active_connections
        assert "alive" in manager.active_connections
        assert manager.get_channel_subscribers("esports:all") == {"alive"}

    @pytest.mark.asyncio
    async def test_broadcast_with_no_subscribers_is_a_noop(self):
        manager = EsportsWebSocketManager()
        await manager.broadcast_to_channel("esports:all", {"type": "event"})
        assert manager.get_connection_stats()["active_connections"] == 0

    @pytest.mark.asyncio
    async def test_reconnect_storm_leaves_no_orphaned_tasks_or_subscriptions(self):
        manager = EsportsWebSocketManager()
        for _ in range(50):
            await manager.connect(FakeSocket(), "storm")
            await manager.subscribe_to_channel("storm", "esports:all")
        # Exactly one registration survives — no leaked heartbeat tasks.
        stats = manager.get_connection_stats()
        assert stats["active_connections"] == 1
        assert len(manager.heartbeat_tasks) == 1
        assert manager.get_channel_subscribers("esports:all") == {"storm"}

    @pytest.mark.asyncio
    async def test_disconnect_clears_every_registry_entry(self):
        manager = EsportsWebSocketManager()
        await manager.connect(FakeSocket(), "c1")
        await manager.subscribe_to_channel("c1", "esports:game:cs2")
        await manager.disconnect("c1")
        assert manager.active_connections == {}
        assert manager.connection_metadata == {}
        assert manager.channel_subscribers == {}
        # Idempotent: a second disconnect (reconnect race) is harmless.
        await manager.disconnect("c1")

    @pytest.mark.asyncio
    async def test_stale_connections_are_cleaned_up(self):
        manager = EsportsWebSocketManager()
        await manager.connect(FakeSocket(), "stale")
        manager.connection_metadata["stale"]["last_heartbeat"] = datetime.utcnow() - timedelta(hours=1)
        await manager.cleanup_stale_connections(timeout_seconds=60)
        assert manager.get_connection_stats()["active_connections"] == 0


# ===========================================================================
# §19 — malformed / duplicate / out-of-order / correction events
# ===========================================================================

class TestEventIntegrity:
    @pytest.mark.asyncio
    async def test_malformed_event_is_rejected_without_corrupting_state(self):
        manager = EsportsDataManager([FlakyProvider()])
        manager.state_engines["m1"] = MatchStateEngine(_match())
        before = manager.state_engines["m1"].get_current_snapshot()

        # A 60-char id exceeds the schema's 50-char limit: the provider payload
        # is malformed and must be refused, not half-applied.
        await manager.process_live_event(_event("x" * 60, sequence=1))

        after = manager.state_engines["m1"].get_current_snapshot()
        assert after.status == before.status
        assert after.score_a == before.score_a
        assert manager.get_stats()["total_events_processed"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_event_is_deduplicated(self):
        service = EventDeduplicationService()
        event = _event("dup-1", sequence=1)
        first = await service.is_duplicate(event)
        await service.register_event(event)
        second = await service.is_duplicate(_event("dup-1", sequence=1))
        assert first is False
        assert second is True
        assert service.get_stats()["duplicates_found"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_event_does_not_double_apply_the_score(self):
        manager = EsportsDataManager([FlakyProvider()])
        engine = MatchStateEngine(_match())
        manager.state_engines["m1"] = engine

        first = _event("s1", sequence=1, payload={"team_a_score": 2, "team_b_score": 0})
        await manager.process_live_event(first)
        duplicate = _event("s1", sequence=1, payload={"team_a_score": 2, "team_b_score": 0})
        await manager.process_live_event(duplicate)

        snapshot = engine.get_current_snapshot()
        assert snapshot.score_a == 2
        assert manager.get_stats()["total_events_processed"] == 1

    @pytest.mark.asyncio
    async def test_out_of_order_event_is_rejected_by_the_state_engine(self):
        engine = MatchStateEngine(_match())
        later = _event("e10", sequence=10, payload={"team_a_score": 5, "team_b_score": 1})
        assert engine.process_event(later) is True
        earlier = _event("e3", sequence=3, payload={"team_a_score": 1, "team_b_score": 0})
        assert engine.process_event(earlier) is False
        assert engine.get_current_snapshot().score_a == 5

    def test_correction_event_overwrites_the_value_it_corrects(self):
        engine = MatchStateEngine(_match())
        engine.process_event(_event("c1", sequence=1, payload={"team_a_score": 3, "team_b_score": 0}))
        assert engine.get_current_snapshot().score_a == 3
        # A provider correction carries the righted value at a later sequence.
        engine.process_event(_event("c2", sequence=2, payload={"team_a_score": 2, "team_b_score": 0}))
        snapshot = engine.get_current_snapshot()
        assert snapshot.score_a == 2  # corrected, not accumulated
        assert engine.last_processed_sequence == 2

    @pytest.mark.asyncio
    async def test_interrupted_network_delivery_resumes_from_snapshot(self):
        manager = EsportsDataManager([FlakyProvider()])
        engine = MatchStateEngine(_match())
        manager.state_engines["m1"] = engine
        await manager.process_live_event(_event("n1", sequence=1, payload={"team_a_score": 1, "team_b_score": 0}))
        # Connection drops here; the client re-reads the snapshot on reconnect.
        snapshot = await manager.get_live_snapshot("m1")
        assert snapshot is not None and snapshot.score_a == 1
        # Delivery resumes with the next sequence.
        await manager.process_live_event(_event("n2", sequence=2, payload={"team_a_score": 2, "team_b_score": 0}))
        assert engine.get_current_snapshot().score_a == 2


# ===========================================================================
# §20 — data integrity: normalized → snapshot → frontend state
# ===========================================================================

class TestDataIntegrity:
    @pytest.mark.asyncio
    async def test_normalized_event_reaches_the_snapshot_unchanged(self):
        manager = EsportsDataManager([FlakyProvider()])
        engine = MatchStateEngine(_match())
        manager.state_engines["m1"] = engine

        raw = _event("i1", sequence=4, payload={"team_a_score": 7, "team_b_score": 3})
        await manager.process_live_event(raw)

        snapshot = await manager.get_live_snapshot("m1")
        assert snapshot.score_a == raw.payload["team_a_score"]
        assert snapshot.score_b == raw.payload["team_b_score"]
        assert snapshot.match_id == "m1"
        assert snapshot.team_a_id == "ta"

    @pytest.mark.asyncio
    async def test_snapshot_serialization_is_stable_for_the_client(self):
        manager = EsportsDataManager([FlakyProvider()])
        manager.state_engines["m1"] = MatchStateEngine(_match())
        snapshot = await manager.get_live_snapshot("m1")
        as_dict = snapshot.to_dict()
        assert {"match_id", "game_id", "status", "score_a", "score_b"}.issubset(as_dict)
        # Round-tripping the client payload loses nothing that was published.
        for key in ("match_id", "game_id", "status", "score_a", "score_b"):
            assert as_dict[key] == getattr(snapshot, key)

    @pytest.mark.asyncio
    async def test_internal_diagnostic_is_emitted_on_a_provider_mismatch(self):
        """§20: a contradiction becomes a labelled diagnostic, not a silent fix."""
        from app.esports.analytics.source_consistency import detect_discrepancies

        a = _match("a1")
        b = _match("b1")
        b.source = "other-feed"
        b.score_a = 0  # disagrees with a's 1-0
        result = detect_discrepancies([a, b])
        assert result["label"] == "SOURCE DISCREPANCY"
        assert result["discrepancies"][0]["match_ids"] == ["a1", "b1"]
        # The authoritative values are untouched.
        assert a.score_a == 1 and b.score_a == 0

    @pytest.mark.asyncio
    async def test_state_engine_rejects_a_team_score_that_cannot_be_a_score(self):
        """Malformed provider payloads never become a published score."""
        engine = MatchStateEngine(_match())
        engine.process_event(_event("x1", sequence=1, payload={"team_a_score": None, "team_b_score": None}))
        snapshot = engine.get_current_snapshot()
        assert isinstance(snapshot.score_a, int)
        assert isinstance(snapshot.score_b, int)

    @pytest.mark.asyncio
    async def test_live_snapshot_reports_data_freshness_honestly(self):
        engine = MatchStateEngine(_match())
        engine.process_event(_event("f1", sequence=1))
        snapshot = engine.get_current_snapshot()
        assert snapshot.data_age_seconds is not None
        assert snapshot.data_age_seconds >= 0
        assert snapshot.data_status is not None
