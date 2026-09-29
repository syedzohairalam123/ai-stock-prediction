"""
Database models for Phase 21A - Real-Time Esports Data Ingestion

This module contains SQLAlchemy ORM models for esports data persistence.
Following the existing database patterns in the project.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, JSON, DateTime, Float, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EsportsGame(Base):
    """Games supported by the esports data system."""
    __tablename__ = "esports_games"
    __table_args__ = (UniqueConstraint("external_id", "source", name="uq_esports_game_external_source"),)

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsTournament(Base):
    """Tournaments for esports games."""
    __tablename__ = "esports_tournaments"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_esports_tournament_external_source"),
        Index("idx_esports_tournaments_game", "game_id"),
        Index("idx_esports_tournaments_dates", "start_date", "end_date"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    prize_pool: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="upcoming", index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsSeries(Base):
    """Series within tournaments (best-of formats)."""
    __tablename__ = "esports_series"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_esports_series_external_source"),
        Index("idx_esports_series_tournament", "tournament_id"),
        Index("idx_esports_series_teams", "team_a_id", "team_b_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    tournament_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    best_of: Mapped[int] = mapped_column(Integer, nullable=False)
    team_a_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    team_b_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    winner_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsMatch(Base):
    """Individual matches within series."""
    __tablename__ = "esports_matches"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_esports_match_external_source"),
        Index("idx_esports_matches_game", "game_id"),
        Index("idx_esports_matches_tournament", "tournament_id"),
        Index("idx_esports_matches_series", "series_id"),
        Index("idx_esports_matches_status", "status"),
        Index("idx_esports_matches_scheduled", "scheduled_at"),
        Index("idx_esports_matches_teams", "team_a_id", "team_b_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tournament_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    series_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    team_a_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    team_b_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    best_of: Mapped[int] = mapped_column(Integer, default=1)
    current_map: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    map_number: Mapped[int] = mapped_column(Integer, default=0)
    score_a: Mapped[int] = mapped_column(Integer, default=0)
    score_b: Mapped[int] = mapped_column(Integer, default=0)
    winner_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsTeam(Base):
    """Teams participating in esports competitions."""
    __tablename__ = "esports_teams"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_esports_team_external_source"),
        Index("idx_esports_teams_game", "game_id"),
        Index("idx_esports_teams_region", "region"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsPlayer(Base):
    """Players on esports teams."""
    __tablename__ = "esports_players"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_esports_player_external_source"),
        Index("idx_esports_players_team", "team_id"),
        Index("idx_esports_players_game", "game_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    handle: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsMap(Base):
    """Individual maps within matches."""
    __tablename__ = "esports_maps"
    __table_args__ = (
        UniqueConstraint("external_id", "source", name="uq_esports_map_external_source"),
        Index("idx_esports_maps_match", "match_id"),
        Index("idx_esports_maps_game", "game_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    match_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    map_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    team_a_score: Mapped[int] = mapped_column(Integer, default=0)
    team_b_score: Mapped[int] = mapped_column(Integer, default=0)
    winner_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="upcoming")
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta_data: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsGameEvent(Base):
    """Game events for live match tracking."""
    __tablename__ = "esports_game_events"
    __table_args__ = (
        Index("idx_esports_events_match", "match_id"),
        Index("idx_esports_events_game", "game_id"),
        Index("idx_esports_events_timestamp", "timestamp"),
        Index("idx_esports_events_sequence", "match_id", "sequence"),
        Index("idx_esports_events_type", "type"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    player_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EsportsMatchSnapshot(Base):
    """Live match snapshots for current state."""
    __tablename__ = "esports_match_snapshots"
    __table_args__ = (
        Index("idx_esports_snapshots_match", "match_id"),
        Index("idx_esports_snapshots_timestamp", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    current_map: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    map_number: Mapped[int] = mapped_column(Integer, default=0)
    score_a: Mapped[int] = mapped_column(Integer, default=0)
    score_b: Mapped[int] = mapped_column(Integer, default=0)
    team_a_id: Mapped[str] = mapped_column(String(50), nullable=False)
    team_b_id: Mapped[str] = mapped_column(String(50), nullable=False)
    current_map_scores: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    game_state: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    data_age_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    data_status: Mapped[str] = mapped_column(String(20), default="LIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class EsportsDataSource(Base):
    """Data sources and their configuration."""
    __tablename__ = "esports_data_sources"
    __table_args__ = (UniqueConstraint("source", "game_id", name="uq_esports_datasource_game"),)

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=lambda: {})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EsportsProviderHealth(Base):
    """Provider health monitoring."""
    __tablename__ = "esports_provider_health"
    __table_args__ = (UniqueConstraint("provider", "game_id", name="uq_esports_provider_game"),)

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    game_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE", index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    event_rate: Mapped[float] = mapped_column(Float, default=0.0)
    connection_status: Mapped[str] = mapped_column(String(20), default="disconnected")
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
