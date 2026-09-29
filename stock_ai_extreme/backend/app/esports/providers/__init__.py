"""
Esports data providers for Phase 21A

This package contains provider-specific adapters for different esports games and data sources.
Following the existing provider pattern in the project for consistency.
"""

from .base import (
    EsportsDataProvider,
    EsportsDataStatus,
    EsportsProviderError,
    Game,
    Tournament,
    Series,
    Match,
    Team,
    Player,
    Map,
    GameEvent,
    LiveSnapshot,
    EventType,
    MatchStatus,
)

__all__ = [
    "EsportsDataProvider",
    "EsportsDataStatus",
    "EsportsProviderError",
    "Game",
    "Tournament",
    "Series",
    "Match",
    "Team",
    "Player",
    "Map",
    "GameEvent",
    "LiveSnapshot",
    "EventType",
    "MatchStatus",
]
