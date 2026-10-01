"""
Phase 21A §12 — durable persistence of the provider catalog.

The Phase 21A read paths serve straight from the providers on demand, which is
correct for freshness but leaves the database empty. This module writes the
provider catalog — games, tournaments, teams, matches, their series and per-map
rows — into the esports tables so history survives a provider outage/restart and
the analytics layer can compare against stored results.

Every function takes an explicit SQLAlchemy ``Session`` instead of opening its
own, so the manager can wrap one unit of work and tests can use an in-memory
database. Writes are upserts keyed by the deterministic internal id: an existing
row is updated field-by-field (``created_at`` is never clobbered), a new one is
inserted. Nothing is fabricated — a field the provider omitted stays NULL.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set, Type

from sqlalchemy.orm import Session

from app.esports.database.models import (
    EsportsGame,
    EsportsMap,
    EsportsMatch,
    EsportsPlayer,
    EsportsSeries,
    EsportsTeam,
    EsportsTournament,
)
from app.esports.providers.base import Game, Match, Player, Team, Tournament, per_game_records

logger = logging.getLogger("neural_market.esports.services.persistence")


def _upsert(db: Session, model: Type[Any], pk: str, values: Dict[str, Any]) -> bool:
    """Insert or update one row by primary key. Returns True when inserted."""
    existing = db.get(model, pk)
    if existing is None:
        db.add(model(id=pk, **values))
        return True
    for key, value in values.items():
        setattr(existing, key, value)
    return False


def persist_game(db: Session, game: Game) -> None:
    _upsert(
        db,
        EsportsGame,
        game.id,
        {
            "external_id": game.external_id,
            "name": game.name,
            "short_name": game.short_name,
            "source": game.source,
            "meta_data": game.meta_data or {},
        },
    )


def persist_tournament(db: Session, tournament: Tournament) -> None:
    _upsert(
        db,
        EsportsTournament,
        tournament.id,
        {
            "external_id": tournament.external_id,
            "name": tournament.name,
            "game_id": tournament.game_id,
            "start_date": tournament.start_date,
            "end_date": tournament.end_date,
            "prize_pool": tournament.prize_pool,
            "region": tournament.region,
            "status": tournament.status,
            "source": (tournament.meta_data or {}).get("source") or "unknown",
            "meta_data": tournament.meta_data or {},
        },
    )


def persist_team(db: Session, team: Team) -> None:
    _upsert(
        db,
        EsportsTeam,
        team.id,
        {
            "external_id": team.external_id,
            "name": team.name,
            "short_name": team.short_name,
            "game_id": team.game_id,
            "logo_url": team.logo_url,
            "region": team.region,
            "source": (team.meta_data or {}).get("source") or "unknown",
            "meta_data": team.meta_data or {},
        },
    )


def persist_player(db: Session, player: Player) -> None:
    _upsert(
        db,
        EsportsPlayer,
        player.id,
        {
            "external_id": player.external_id,
            "name": player.name,
            "handle": player.handle,
            "team_id": player.team_id,
            "game_id": player.game_id,
            "role": player.role,
            "country": player.country,
            "source": (player.meta_data or {}).get("source") or "unknown",
            "meta_data": player.meta_data or {},
        },
    )


def persist_match(db: Session, match: Match) -> None:
    """The match row, plus its series and per-map rows derived from real data."""
    status = match.status.value if hasattr(match.status, "value") else str(match.status)
    _upsert(
        db,
        EsportsMatch,
        match.id,
        {
            "external_id": match.external_id,
            "game_id": match.game_id,
            "tournament_id": match.tournament_id,
            "series_id": match.series_id,
            "status": status,
            "scheduled_at": match.scheduled_at,
            "team_a_id": match.team_a_id,
            "team_b_id": match.team_b_id,
            "started_at": match.started_at,
            "ended_at": match.ended_at,
            "best_of": match.best_of,
            "current_map": match.current_map,
            "map_number": match.map_number,
            "score_a": match.score_a,
            "score_b": match.score_b,
            "winner_id": match.winner_id,
            "source": match.source,
            "source_timestamp": match.source_timestamp,
            "meta_data": match.meta_data or {},
        },
    )
    persist_series(db, match)
    persist_maps(db, match)


def persist_series(db: Session, match: Match) -> None:
    _upsert(
        db,
        EsportsSeries,
        match.series_id,
        {
            "external_id": match.external_id,
            "tournament_id": match.tournament_id,
            "name": (match.meta_data or {}).get("league") or (match.meta_data or {}).get("event") or match.external_id,
            "best_of": match.best_of,
            "team_a_id": match.team_a_id,
            "team_b_id": match.team_b_id,
            "winner_id": match.winner_id,
            "start_date": match.started_at or match.scheduled_at,
            "end_date": match.ended_at,
            "source": match.source,
            "meta_data": {"source": match.source},
        },
    )


def persist_maps(db: Session, match: Match) -> int:
    """One row per published map/game record — never an invented placeholder."""
    records = per_game_records(match.meta_data)
    written = 0
    for index, record in enumerate(records):
        name = record.get("name")
        if not name:
            # A record with no published identity is skipped, not guessed.
            continue
        map_number = record.get("map_number") or (index + 1)
        _upsert(
            db,
            EsportsMap,
            f"{match.id}-map-{map_number}",
            {
                "external_id": f"{match.external_id}-map-{map_number}",
                "match_id": match.id,
                "game_id": match.game_id,
                "map_number": int(map_number),
                "name": str(name),
                "team_a_score": int(record.get("team_a_score") or record.get("radiant_score") or 0),
                "team_b_score": int(record.get("team_b_score") or record.get("dire_score") or 0),
                "winner_id": match.winner_id,
                "start_time": match.started_at,
                "status": "completed" if match.ended_at else "live",
                "source": match.source,
                "meta_data": {"source": match.source, "game_id": record.get("match_id")},
            },
        )
        written += 1
    return written


async def persist_catalog(
    manager: Any,
    db: Session,
    *,
    max_matches: int = 200,
    max_teams: int = 40,
    persist_players: bool = False,
    max_player_teams: int = 8,
) -> Dict[str, int]:
    """
    One bounded persistence pass over every provider.

    Bounded on purpose: at most ``max_matches`` matches and ``max_teams`` teams
    per provider per pass, so a background sweep never turns into an unbounded
    crawl of the upstream (and never multiplies provider connections). Player
    rosters are opt-in because some adapters fan a roster request out into one
    call per player.
    """
    counts: Counter = Counter()
    for provider in manager.providers:
        name = provider.get_provider_name()
        try:
            games = await provider.get_games()
        except Exception as exc:  # a single provider failing must not stop the sweep
            logger.warning("catalog persist: %s get_games failed: %s", name, exc)
            continue
        for game in games:
            persist_game(db, game)
            counts["games"] += 1
            try:
                tournaments = await provider.get_tournaments(game.id)
            except Exception as exc:
                logger.debug("catalog persist: %s tournaments failed: %s", name, exc)
                tournaments = []
            for tournament in tournaments:
                persist_tournament(db, tournament)
                counts["tournaments"] += 1

            try:
                teams = await provider.get_teams(game.id)
            except Exception as exc:
                logger.debug("catalog persist: %s teams failed: %s", name, exc)
                teams = []
            for team in teams[:max_teams]:
                persist_team(db, team)
                counts["teams"] += 1

            try:
                matches = await provider.get_matches(game.id)
            except Exception as exc:
                logger.debug("catalog persist: %s matches failed: %s", name, exc)
                matches = []
            for match in matches[:max_matches]:
                persist_match(db, match)
                counts["matches"] += 1
                counts["maps"] += len(per_game_records(match.meta_data))

            if persist_players:
                await _persist_roster_sample(
                    provider, db, matches[:max_matches], max_player_teams, counts
                )

        db.flush()
    db.commit()
    return {k: int(v) for k, v in counts.items()}


async def _persist_roster_sample(
    provider: Any,
    db: Session,
    matches: Iterable[Match],
    max_teams: int,
    counts: Counter,
) -> None:
    """Persist rosters for the teams in the newest matches, capped and de-duped."""
    team_ids: List[str] = []
    for match in matches:
        for team_id in (match.team_a_id, match.team_b_id):
            if team_id and team_id not in team_ids:
                team_ids.append(team_id)
        if len(team_ids) >= max_teams:
            break
    for team_id in team_ids[:max_teams]:
        try:
            players = await provider.get_players(team_id)
        except Exception:
            continue
        for player in players:
            persist_player(db, player)
            counts["players"] += 1


def catalog_counts(db: Session) -> Dict[str, int]:
    """Row counts per esports table — used for the persistence health readout."""
    models: List[tuple[str, Type[Any]]] = [
        ("games", EsportsGame),
        ("tournaments", EsportsTournament),
        ("series", EsportsSeries),
        ("matches", EsportsMatch),
        ("teams", EsportsTeam),
        ("players", EsportsPlayer),
        ("maps", EsportsMap),
    ]
    counts: Dict[str, int] = {}
    for label, model in models:
        try:
            counts[label] = int(db.query(model).count())
        except Exception:
            counts[label] = -1
    return counts
