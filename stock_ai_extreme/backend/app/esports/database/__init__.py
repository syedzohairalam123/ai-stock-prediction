"""
Database models for Phase 21A

This package contains SQLAlchemy ORM models for esports data persistence.
"""

from .models import (
    EsportsGame,
    EsportsTournament,
    EsportsSeries,
    EsportsMatch,
    EsportsTeam,
    EsportsPlayer,
    EsportsMap,
    EsportsGameEvent,
    EsportsMatchSnapshot,
    EsportsDataSource,
    EsportsProviderHealth,
)

__all__ = [
    "EsportsGame",
    "EsportsTournament",
    "EsportsSeries",
    "EsportsMatch",
    "EsportsTeam",
    "EsportsPlayer",
    "EsportsMap",
    "EsportsGameEvent",
    "EsportsMatchSnapshot",
    "EsportsDataSource",
    "EsportsProviderHealth",
]
