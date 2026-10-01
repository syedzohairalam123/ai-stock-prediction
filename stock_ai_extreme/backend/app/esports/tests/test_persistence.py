"""
Phase 21A §12 — persistence tests.

Runs against an in-memory SQLite database (never the app's file DB), so the
upsert semantics and bounded sweep are asserted without any real storage.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.esports.database.models import (
    EsportsGame,
    EsportsMap,
    EsportsMatch,
    EsportsPlayer,
    EsportsSeries,
    EsportsTeam,
    EsportsTournament,
)
from app.esports.providers.base import Game, Match, MatchStatus, Player, Team, Tournament
from app.esports.services import persistence

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _match(mid: str = "cs2-m1", *, score: tuple[int, int] = (2, 0)) -> Match:
    return Match(
        id=mid,
        external_id="2396949",
        game_id="cs2",
        tournament_id="cs2-tour-1",
        series_id=f"{mid}-series",
        status=MatchStatus.COMPLETED,
        scheduled_at=NOW,
        team_a_id="cs2-t7020",
        team_b_id="cs2-t11283",
        started_at=NOW,
        ended_at=NOW,
        best_of=3,
        current_map="Ancient",
        map_number=2,
        score_a=score[0],
        score_b=score[1],
        winner_id="cs2-t7020",
        source="csapi.de",
        source_timestamp=NOW,
        meta_data={
            "source": "csapi.de",
            "league": "BLAST Open Porto 2026",
            "maps": [
                {"map_number": 1, "name": "Nuke", "team_a_score": 13, "team_b_score": 8},
                {"map_number": 2, "name": "Ancient", "team_a_score": 13, "team_b_score": 11},
            ],
        },
    )


def _game() -> Game:
    return Game(id="cs2", external_id="cs2", name="Counter-Strike 2", short_name="CS2", source="csapi.de")


def test_persist_match_writes_match_series_and_maps(db):
    persistence.persist_game(db, _game())
    persistence.persist_match(db, _match())
    db.commit()

    assert db.query(EsportsGame).count() == 1
    assert db.query(EsportsMatch).count() == 1
    assert db.query(EsportsSeries).count() == 1
    assert db.query(EsportsMap).count() == 2

    row = db.query(EsportsMatch).one()
    assert row.score_a == 2 and row.source == "csapi.de"
    assert row.tournament_id == "cs2-tour-1"
    maps = {m.name: m for m in db.query(EsportsMap).all()}
    assert maps["Nuke"].team_a_score == 13
    assert maps["Ancient"].team_b_score == 11


def test_upsert_updates_in_place_without_duplicating(db):
    persistence.persist_match(db, _match(score=(2, 0)))
    db.commit()
    created_at = db.query(EsportsMatch).one().created_at

    persistence.persist_match(db, _match(score=(2, 1)))  # correction
    db.commit()

    assert db.query(EsportsMatch).count() == 1
    row = db.query(EsportsMatch).one()
    assert row.score_b == 1
    # created_at is never clobbered by an update.
    assert row.created_at == created_at


def test_maps_without_a_published_name_are_skipped_not_invented(db):
    match = _match()
    match.meta_data["maps"] = [
        {"map_number": 1, "name": "Nuke", "team_a_score": 13, "team_b_score": 8},
        {"map_number": 2, "name": None, "team_a_score": 13, "team_b_score": 11},
    ]
    persistence.persist_match(db, match)
    db.commit()
    assert db.query(EsportsMap).count() == 1


def test_catalog_counts_reports_every_table(db):
    persistence.persist_game(db, _game())
    persistence.persist_team(
        db, Team(id="cs2-t7020", external_id="7020", name="Spirit", short_name="SPIR", game_id="cs2")
    )
    persistence.persist_match(db, _match())
    db.commit()

    counts = persistence.catalog_counts(db)
    assert counts["games"] == 1
    assert counts["teams"] == 1
    assert counts["matches"] == 1
    assert counts["maps"] == 2
    assert counts["tournaments"] == 0


class _FakeProvider:
    def __init__(self) -> None:
        self.roster_calls = 0

    def get_provider_name(self) -> str:
        return "csapi.de"

    async def get_games(self):
        return [_game()]

    async def get_tournaments(self, game_id):
        return [
            Tournament(
                id="cs2-tour-1", external_id="tour-1", name="BLAST", game_id=game_id,
                start_date=NOW, end_date=NOW, status="completed",
                meta_data={"source": "csapi.de"},
            )
        ]

    async def get_teams(self, game_id):
        return [
            Team(id="cs2-t7020", external_id="7020", name="Spirit", short_name="SPIR", game_id=game_id,
                 meta_data={"source": "csapi.de"}),
            Team(id="cs2-t11283", external_id="11283", name="Falcons", short_name="FALC", game_id=game_id,
                 meta_data={"source": "csapi.de"}),
        ]

    async def get_matches(self, game_id, tournament_id=None):
        return [_match()]

    async def get_players(self, team_id):
        self.roster_calls += 1
        # A provider player id is unique per source, so each team's player here
        # gets a distinct external id — matching how the real adapters behave.
        return [
            Player(id=f"{team_id}-p1", external_id=f"player-{team_id}", name="donk", handle="donk",
                   team_id=team_id, game_id="cs2", meta_data={"source": "csapi.de"})
        ]


class _FakeManager:
    def __init__(self, providers) -> None:
        self.providers = providers


@pytest.mark.asyncio
async def test_persist_catalog_sweeps_and_is_bounded(db):
    provider = _FakeProvider()
    manager = _FakeManager([provider])

    counts = await persistence.persist_catalog(
        manager, db, max_matches=50, max_teams=10, persist_players=False
    )

    assert counts["games"] == 1
    assert counts["tournaments"] == 1
    assert counts["teams"] == 2
    assert counts["matches"] == 1
    assert counts["maps"] == 2
    assert "players" not in counts
    assert provider.roster_calls == 0  # rosters are opt-in

    assert db.query(EsportsMatch).count() == 1
    assert db.query(EsportsTournament).count() == 1


@pytest.mark.asyncio
async def test_persist_catalog_can_include_rosters(db):
    provider = _FakeProvider()
    counts = await persistence.persist_catalog(
        _FakeManager([provider]), db, persist_players=True, max_player_teams=2
    )
    assert counts["players"] == 2
    assert db.query(EsportsPlayer).count() == 2
    assert provider.roster_calls == 2


@pytest.mark.asyncio
async def test_persist_catalog_contains_a_failing_provider(db):
    class Broken:
        def get_provider_name(self):
            return "broken"

        async def get_games(self):
            raise RuntimeError("upstream down")

    counts = await persistence.persist_catalog(_FakeManager([Broken(), _FakeProvider()]), db)
    assert counts["matches"] == 1  # the healthy provider still persisted
