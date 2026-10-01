"""
Unit tests for the Phase 21B esports feed service.

These run entirely against in-memory fake providers — no network, no database
— because the feed service is pure view logic over the Phase 21A models. That
is exactly what makes §28's "hero match / filters / missing data" cases
testable deterministically.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.esports.providers.base import (
    EsportsDataProvider,
    Game,
    GameEvent,
    EventType,
    Match,
    MatchStatus,
    Player,
    ProviderHealth,
    Team,
    Tournament,
)
from app.esports.services.manager import EsportsDataManager
from app.esports.services import feed

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _match(mid, status, *, game="cs2", minutes_ago=10, score=(1, 0), source="test", **meta):
    scheduled = NOW - timedelta(minutes=minutes_ago)
    return Match(
        id=mid,
        external_id=mid,
        game_id=game,
        tournament_id=f"{game}-tour-1",
        series_id=f"{game}-s-1",
        status=status,
        scheduled_at=scheduled,
        team_a_id="ta",
        team_b_id="tb",
        started_at=scheduled,
        ended_at=scheduled if status == MatchStatus.COMPLETED else None,
        best_of=3,
        current_map="Mirage",
        map_number=1,
        score_a=score[0],
        score_b=score[1],
        winner_id=None,
        source=source,
        source_timestamp=scheduled,
        received_at=NOW,
        meta_data={
            "team_names": {"ta": "Alpha", "tb": "Beta"},
            "league": "Test League",
            **meta,
        },
    )


class FakeProvider(EsportsDataProvider):
    def __init__(self, name, games, matches, events=None, players=None):
        self._name = name
        self._games = games
        self._matches = matches
        self._events = events or []
        self._players = players or []
        self._teams = [
            Team(id="ta", external_id="ta", name="Alpha", short_name="ALP", game_id=games[0].id, logo_url="http://x/a.png"),
            Team(id="tb", external_id="tb", name="Beta", short_name="BET", game_id=games[0].id, logo_url=None),
        ]

    async def get_games(self):
        return self._games

    async def get_tournaments(self, game_id):
        return [
            Tournament(
                id=f"{game_id}-tour-1",
                external_id="tour-1",
                name="Test Cup",
                game_id=game_id,
                start_date=NOW - timedelta(days=2),
                end_date=NOW,
                status="completed",
            )
        ] if game_id in {g.id for g in self._games} else []

    async def get_matches(self, game_id, tournament_id=None):
        return [m for m in self._matches if m.game_id == game_id]

    async def get_match(self, match_id):
        return next((m for m in self._matches if m.id == match_id), None)

    async def get_teams(self, game_id):
        return self._teams

    async def get_team(self, team_id):
        return next((t for t in self._teams if t.id == team_id), None)

    async def get_players(self, team_id):
        if team_id == "ta":
            return [
                Player(id="p1", external_id="p1", name="P One", handle="p1", team_id="ta", game_id="cs2")
            ]
        return self._players

    async def get_live_events(self, game_id):
        return []

    async def get_match_events(self, match_id):
        return [
            GameEvent(
                id=f"{match_id}-e1",
                match_id=match_id,
                game_id="cs2",
                type=EventType.MAP_STARTED,
                timestamp=NOW,
                sequence=1,
                payload={"map_name": "Mirage"},
                source="test",
            )
        ]

    async def subscribe_to_match(self, match_id, callback):
        return None

    async def unsubscribe_from_match(self, match_id):
        return None

    def get_provider_name(self):
        return self._name

    async def get_provider_health(self):
        return ProviderHealth.AVAILABLE

    async def get_provider_metrics(self):
        return {"request_count": 3, "error_count": 0, "last_success": NOW.isoformat(), "data_mode": "DELAYED"}


def _manager():
    cs2 = FakeProvider(
        "csapi.de",
        [Game(id="cs2", external_id="cs2", name="Counter-Strike 2", short_name="CS2", source="csapi.de")],
        [
            _match("cs2-m1", MatchStatus.COMPLETED, minutes_ago=60, data_mode="DELAYED"),
            _match("cs2-m2", MatchStatus.LIVE, minutes_ago=1, score=(2, 1), data_mode="LIVE"),
        ],
    )
    lol = FakeProvider(
        "lolesports.com",
        [Game(id="lol", external_id="lol", name="League of Legends", short_name="LoL", source="lolesports.com")],
        [_match("lol-m1", MatchStatus.SCHEDULED, game="lol", minutes_ago=-30, score=(0, 0), data_mode="LIVE")],
    )
    return EsportsDataManager([cs2, lol])


# --------------------------------------------------------------------------
# §3 — featured-match ranking
# --------------------------------------------------------------------------

def test_select_featured_prefers_live_over_completed():
    live = _match("live", MatchStatus.LIVE)
    upcoming = _match("upcoming", MatchStatus.UPCOMING, minutes_ago=-30)
    done = _match("done", MatchStatus.COMPLETED, minutes_ago=120)
    assert feed.select_featured([done, upcoming, live], NOW).id == "live"


def test_select_featured_prefers_upcoming_over_completed():
    upcoming = _match("upcoming", MatchStatus.UPCOMING, minutes_ago=-30)
    done = _match("done", MatchStatus.COMPLETED, minutes_ago=120)
    assert feed.select_featured([done, upcoming], NOW).id == "upcoming"


def test_select_featured_empty():
    assert feed.select_featured([], NOW) is None


def test_status_priority_orders_map_break_after_live():
    live = _match("live", MatchStatus.LIVE)
    brk = _match("brk", MatchStatus.MAP_BREAK)
    assert feed.rank_matches([brk, live], NOW)[0].id == "live"


# --------------------------------------------------------------------------
# §15 — data quality / mode
# --------------------------------------------------------------------------

def test_data_quality_live_is_live_when_fresh():
    fresh = _match("m", MatchStatus.LIVE, minutes_ago=0)
    assert feed.compute_data_quality(fresh, NOW) == "LIVE"


def test_data_quality_live_goes_stale_over_time():
    old = _match("m", MatchStatus.LIVE, minutes_ago=60)
    assert feed.compute_data_quality(old, NOW) == "STALE"


def test_data_quality_for_completed_uses_source_mode():
    done = _match("m", MatchStatus.COMPLETED, minutes_ago=120, data_mode="DELAYED")
    assert feed.compute_data_quality(done, NOW) == "DELAYED"


def test_serialize_match_carries_real_fields_only():
    record = feed.serialize_match(_match("cs2-m1", MatchStatus.COMPLETED), NOW)
    assert record["team_a"]["name"] == "Alpha"
    assert record["tournament_name"] == "Test League"
    assert record["team_b"]["logo_url"] is None  # never invented
    assert set(["data_mode", "data_quality", "last_updated", "source"]).issubset(record)


def test_serialize_match_surfaces_cs2_per_map_records():
    """csapi.de publishes ``maps``; the feed must not drop that real data."""
    maps = [
        {"map_number": 1, "name": "Nuke", "team_a_score": 13, "team_b_score": 8},
        {"map_number": 2, "name": "Ancient", "team_a_score": 13, "team_b_score": 11},
    ]
    record = feed.serialize_match(_match("cs2-m1", MatchStatus.COMPLETED, maps=maps), NOW)
    assert [entry["name"] for entry in record["games"]] == ["Nuke", "Ancient"]
    assert record["games"][0]["team_a_score"] == 13
    assert record["games"][0]["team_b_score"] == 8


# --------------------------------------------------------------------------
# §24 — server-side filtering
# --------------------------------------------------------------------------

def test_filter_by_game_status_and_query():
    matches = _manager().providers[0]._matches
    assert len([m for m in matches if feed.match_matches_filters(m, {"game": "cs2"})]) == 2
    assert len([m for m in matches if feed.match_matches_filters(m, {"live": True})]) == 1
    assert len([m for m in matches if feed.match_matches_filters(m, {"statuses": ["COMPLETED"]})]) == 1
    assert len([m for m in matches if feed.match_matches_filters(m, {"q": "beta"})]) == 2
    assert feed.match_matches_filters(matches[0], {"q": "no-such-team"}) is False


def test_filter_date_range():
    m = _match("m", MatchStatus.COMPLETED, minutes_ago=60)
    assert feed.match_matches_filters(m, {"date_from": NOW - timedelta(hours=2)}) is True
    assert feed.match_matches_filters(m, {"date_from": NOW}) is False


# --------------------------------------------------------------------------
# async feed / summary
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_feed_sorts_and_pages():
    out = await feed.build_feed(_manager(), {}, limit=2)
    assert out["total"] == 3
    assert len(out["matches"]) == 2
    assert out["has_more"] is True
    # live first, then the soonest upcoming
    assert out["matches"][0]["status"] == "LIVE"


@pytest.mark.asyncio
async def test_game_summary_counts_are_literal():
    out = await feed.game_summary(_manager())
    by_game = {g["game_id"]: g for g in out["games"]}
    assert by_game["cs2"]["counts"]["live"] == 1
    assert by_game["cs2"]["counts"]["recent"] == 1
    assert by_game["cs2"]["counts"]["tournaments"] == 1
    assert by_game["lol"]["counts"]["upcoming"] == 1


@pytest.mark.asyncio
async def test_featured_match_across_games():
    featured = await feed.featured_match(_manager())
    assert featured is not None
    assert featured["status"] == "LIVE"
    assert featured["game_id"] == "cs2"


@pytest.mark.asyncio
async def test_manager_merges_and_orders_match_events():
    manager = _manager()
    events = await manager.get_match_events("cs2-m1")
    assert [e.id for e in events] == ["cs2-m1-e1"]


@pytest.mark.asyncio
async def test_provider_health_report_shape():
    report = await _manager().provider_health_report()
    assert {row["name"] for row in report} == {"csapi.de", "lolesports.com"}
    assert all("status" in row for row in report)
