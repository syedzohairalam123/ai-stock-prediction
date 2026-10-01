"""
Base provider abstraction for Phase 21A - Real-Time Esports Data Ingestion

This module defines the contract for esports data providers.
Following the existing provider pattern in the project for consistency.
"""

from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
import uuid


class EsportsDataStatus(str, Enum):
    """Data status for esports data freshness."""
    LIVE = "LIVE"
    RECENT = "RECENT"
    DELAYED = "DELAYED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class MatchStatus(str, Enum):
    """Deterministic match states with explicit allowed transitions."""
    SCHEDULED = "SCHEDULED"
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    MAP_BREAK = "MAP_BREAK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"
    UNKNOWN = "UNKNOWN"


class EventType(str, Enum):
    """Supported game event types - only create types the provider actually supports."""
    MATCH_STARTED = "MATCH_STARTED"
    MAP_STARTED = "MAP_STARTED"
    ROUND_STARTED = "ROUND_STARTED"
    ROUND_ENDED = "ROUND_ENDED"
    SCORE_CHANGED = "SCORE_CHANGED"
    PLAYER_EVENT = "PLAYER_EVENT"
    OBJECTIVE_EVENT = "OBJECTIVE_EVENT"
    MAP_ENDED = "MAP_ENDED"
    MATCH_PAUSED = "MATCH_PAUSED"
    MATCH_RESUMED = "MATCH_RESUMED"
    MATCH_ENDED = "MATCH_ENDED"


class ProviderHealth(str, Enum):
    """Provider health status."""
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class EsportsProviderError(Exception):
    """Error raised when an esports provider cannot fulfill a request."""
    def __init__(self, provider: str, message: str):
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


def per_game_records(meta_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    The provider's per-map / per-game records, whichever key it publishes them under.

    Adapters differ here because their upstreams do: CS2 (csapi.de) publishes a
    ``maps`` list of ``{map_number, name, team_a_score, team_b_score}``, while
    Dota 2 and LoL publish a ``games`` list of ``{duration, radiant_score,
    dire_score, radiant_win, ...}``. Every consumer that needs the per-map
    breakdown (feed serialization, map analytics, duration stats, anomaly
    features) must read whichever list the source actually provided — assuming
    a single key silently drops a source's real data.

    Returns ``[]`` when neither key carries a usable list; it never fabricates
    a record.
    """
    if not meta_data:
        return []
    for key in ("games", "maps"):
        records = meta_data.get(key)
        if isinstance(records, list) and records:
            return [record for record in records if isinstance(record, dict)]
    return []


@dataclass
class Game:
    """Normalized game model."""
    id: str
    external_id: str
    name: str
    short_name: str
    source: str
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "name": self.name,
            "short_name": self.short_name,
            "source": self.source,
            "meta_data": self.meta_data,
        }


@dataclass
class Team:
    """Normalized team model."""
    id: str
    external_id: str
    name: str
    short_name: str
    game_id: str
    logo_url: Optional[str] = None
    region: Optional[str] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "name": self.name,
            "short_name": self.short_name,
            "game_id": self.game_id,
            "logo_url": self.logo_url,
            "region": self.region,
            "meta_data": self.meta_data,
        }


@dataclass
class Player:
    """Normalized player model."""
    id: str
    external_id: str
    name: str
    handle: str
    team_id: str
    game_id: str
    role: Optional[str] = None
    country: Optional[str] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "name": self.name,
            "handle": self.handle,
            "team_id": self.team_id,
            "game_id": self.game_id,
            "role": self.role,
            "country": self.country,
            "meta_data": self.meta_data,
        }


@dataclass
class Tournament:
    """Normalized tournament model."""
    id: str
    external_id: str
    name: str
    game_id: str
    start_date: datetime
    end_date: Optional[datetime] = None
    prize_pool: Optional[float] = None
    region: Optional[str] = None
    status: str = "upcoming"
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "name": self.name,
            "game_id": self.game_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "prize_pool": self.prize_pool,
            "region": self.region,
            "status": self.status,
            "meta_data": self.meta_data,
        }


@dataclass
class Series:
    """Normalized series model."""
    id: str
    external_id: str
    tournament_id: str
    name: str
    best_of: int
    team_a_id: str
    team_b_id: str
    winner_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "tournament_id": self.tournament_id,
            "name": self.name,
            "best_of": self.best_of,
            "team_a_id": self.team_a_id,
            "team_b_id": self.team_b_id,
            "winner_id": self.winner_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "meta_data": self.meta_data,
        }


@dataclass
class Map:
    """Normalized map model."""
    id: str
    external_id: str
    match_id: str
    game_id: str
    map_number: int
    name: str
    team_a_score: int = 0
    team_b_score: int = 0
    winner_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: str = "upcoming"
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "match_id": self.match_id,
            "game_id": self.game_id,
            "map_number": self.map_number,
            "name": self.name,
            "team_a_score": self.team_a_score,
            "team_b_score": self.team_b_score,
            "winner_id": self.winner_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "meta_data": self.meta_data,
        }


@dataclass
class Match:
    """Normalized match model."""
    id: str
    external_id: str
    game_id: str
    tournament_id: str
    series_id: str
    status: MatchStatus
    scheduled_at: datetime
    team_a_id: str
    team_b_id: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    best_of: int = 1
    current_map: Optional[str] = None
    map_number: int = 0
    score_a: int = 0
    score_b: int = 0
    winner_id: Optional[str] = None
    source: str = "unknown"
    source_timestamp: Optional[datetime] = None
    received_at: datetime = field(default_factory=datetime.utcnow)
    meta_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "external_id": self.external_id,
            "game_id": self.game_id,
            "tournament_id": self.tournament_id,
            "series_id": self.series_id,
            "status": self.status.value,
            "scheduled_at": self.scheduled_at.isoformat(),
            "team_a_id": self.team_a_id,
            "team_b_id": self.team_b_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "best_of": self.best_of,
            "current_map": self.current_map,
            "map_number": self.map_number,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "winner_id": self.winner_id,
            "source": self.source,
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "received_at": self.received_at.isoformat(),
            "meta_data": self.meta_data,
        }


@dataclass
class GameEvent:
    """Normalized game event model."""
    id: str
    match_id: str
    game_id: str
    type: EventType
    timestamp: datetime
    sequence: int
    team_id: Optional[str] = None
    player_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    source_timestamp: Optional[datetime] = None
    received_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "match_id": self.match_id,
            "game_id": self.game_id,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence,
            "team_id": self.team_id,
            "player_id": self.player_id,
            "payload": self.payload,
            "source": self.source,
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "received_at": self.received_at.isoformat(),
        }


@dataclass
class LiveSnapshot:
    """Live match snapshot for client connections."""
    match_id: str
    game_id: str
    status: MatchStatus
    current_map: Optional[str]
    map_number: int
    score_a: int
    score_b: int
    team_a_id: str
    team_b_id: str
    current_map_scores: Dict[str, Dict[str, int]] = field(default_factory=dict)
    game_state: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data_age_seconds: Optional[float] = None
    data_status: EsportsDataStatus = EsportsDataStatus.LIVE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "game_id": self.game_id,
            "status": self.status.value,
            "current_map": self.current_map,
            "map_number": self.map_number,
            "score_a": self.score_a,
            "score_b": self.score_b,
            "team_a_id": self.team_a_id,
            "team_b_id": self.team_b_id,
            "current_map_scores": self.current_map_scores,
            "game_state": self.game_state,
            "timestamp": self.timestamp.isoformat(),
            "data_age_seconds": self.data_age_seconds,
            "data_status": self.data_status.value,
        }


class EsportsDataProvider(ABC):
    """
    Base interface for esports data providers.
    
    All provider-specific implementations must implement these methods.
    Do not expose provider-specific response formats to the frontend.
    """
    
    @abstractmethod
    async def get_games(self) -> List[Game]:
        """Get all supported games."""
        pass
    
    @abstractmethod
    async def get_tournaments(self, game_id: str) -> List[Tournament]:
        """Get tournaments for a specific game."""
        pass
    
    @abstractmethod
    async def get_matches(self, game_id: str, tournament_id: Optional[str] = None) -> List[Match]:
        """Get matches for a game, optionally filtered by tournament."""
        pass
    
    @abstractmethod
    async def get_match(self, match_id: str) -> Optional[Match]:
        """Get a specific match by ID."""
        pass
    
    @abstractmethod
    async def get_teams(self, game_id: str) -> List[Team]:
        """Get teams for a specific game."""
        pass
    
    @abstractmethod
    async def get_players(self, team_id: str) -> List[Player]:
        """Get players for a specific team."""
        pass
    
    @abstractmethod
    async def get_live_events(self, game_id: str) -> List[GameEvent]:
        """Get live game events for a game."""
        pass
    
    @abstractmethod
    async def get_match_events(self, match_id: str) -> List[GameEvent]:
        """Get events for a specific match."""
        pass
    
    @abstractmethod
    async def subscribe_to_match(self, match_id: str, callback) -> None:
        """Subscribe to real-time updates for a match."""
        pass
    
    @abstractmethod
    async def unsubscribe_from_match(self, match_id: str) -> None:
        """Unsubscribe from match updates."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider name."""
        pass
    
    @abstractmethod
    async def get_provider_health(self) -> ProviderHealth:
        """Get current provider health status."""
        pass
    
    @abstractmethod
    async def get_provider_metrics(self) -> Dict[str, Any]:
        """Get provider performance metrics."""
        pass
