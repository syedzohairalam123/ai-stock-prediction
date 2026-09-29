"""
Phase 21A - Real-Time Esports Data Ingestion + Live Match Engine

This module provides the backend infrastructure for ingesting, validating, normalizing,
storing, and streaming real esports match data from authorized providers.

Architecture:
- Provider adapters for different games (CS2, LoL, Dota2)
- Normalization pipeline with schema validation
- Match state machine with deterministic transitions
- Event deduplication and ordering
- Live state reconstruction
- WebSocket streaming for real-time updates
- Database persistence with Redis caching
- Provider health monitoring
- 10,000-user scalable architecture
"""

from .providers.base import (
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
)

from .normalization.pipeline import NormalizationPipeline
from .state.match_state_machine import MatchStateMachine, MatchState
from .state.event_engine import MatchStateEngine
from .services.event_deduplication import EventDeduplicationService
from .services.event_ordering import EventOrderingService
from .websocket.manager import EsportsWebSocketManager
from .database.models import (
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
from .services.manager import EsportsDataManager
# Phase 21B fix: `main.py` calls `esports_mod.configure_esports(...)` to inject
# the data manager at startup, but the package never re-exported it, so the app
# raised AttributeError during import. Export it (and the additive feed service)
# so the real-time esports engine is actually wired up.
from .routes import esports_router, configure_esports
from .services import feed as esports_feed

__all__ = [
    # Provider interfaces
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
    # Normalization
    "NormalizationPipeline",
    # State management
    "MatchStateMachine",
    "MatchState",
    "MatchStateEngine",
    # Services
    "EventDeduplicationService",
    "EventOrderingService",
    "EsportsWebSocketManager",
    "EsportsDataManager",
    # Database models
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
    # Router
    "esports_router",
    "configure_esports",
    # Feed views (Phase 21B)
    "esports_feed",
]
