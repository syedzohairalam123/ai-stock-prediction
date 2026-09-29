"""
Schema validation for esports data normalization.

This module provides validation functions for all esports data models using Pydantic.
Every stage must be independently testable.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, validator
from enum import Enum


class MatchStatusEnum(str, Enum):
    """Match status enum for validation."""
    SCHEDULED = "SCHEDULED"
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    MAP_BREAK = "MAP_BREAK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"
    UNKNOWN = "UNKNOWN"


class EventTypeEnum(str, Enum):
    """Event type enum for validation."""
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


class GameSchema(BaseModel):
    """Schema for validating game data."""
    id: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    short_name: str = Field(..., min_length=1, max_length=20)
    source: str = Field(..., min_length=1, max_length=50)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('id')
    def validate_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Game ID cannot be empty")
        return v.strip()
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Game name cannot be empty")
        return v.strip()


class TournamentSchema(BaseModel):
    """Schema for validating tournament data."""
    id: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    game_id: str = Field(..., min_length=1, max_length=50)
    start_date: datetime
    end_date: Optional[datetime] = None
    prize_pool: Optional[float] = Field(None, ge=0)
    region: Optional[str] = Field(None, max_length=50)
    status: str = Field(default="upcoming", max_length=50)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('end_date')
    def validate_end_date(cls, v, values):
        if v is not None and 'start_date' in values:
            if v < values['start_date']:
                raise ValueError("End date cannot be before start date")
        return v


class MatchSchema(BaseModel):
    """Schema for validating match data."""
    id: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=100)
    game_id: str = Field(..., min_length=1, max_length=50)
    tournament_id: str = Field(..., min_length=1, max_length=50)
    series_id: str = Field(..., min_length=1, max_length=50)
    status: MatchStatusEnum
    scheduled_at: datetime
    team_a_id: str = Field(..., min_length=1, max_length=50)
    team_b_id: str = Field(..., min_length=1, max_length=50)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    best_of: int = Field(default=1, ge=1, le=10)
    current_map: Optional[str] = Field(None, max_length=100)
    map_number: int = Field(default=0, ge=0)
    score_a: int = Field(default=0, ge=0)
    score_b: int = Field(default=0, ge=0)
    winner_id: Optional[str] = Field(None, max_length=50)
    source: str = Field(default="unknown", max_length=50)
    source_timestamp: Optional[datetime] = None
    received_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('ended_at')
    def validate_ended_at(cls, v, values):
        if v is not None and 'started_at' in values and values['started_at'] is not None:
            if v < values['started_at']:
                raise ValueError("End time cannot be before start time")
        return v
    
    @validator('team_a_id', 'team_b_id')
    def validate_team_ids(cls, v):
        if v == values.get('team_a_id') and 'team_b_id' in values:
            # Check if team_a_id equals team_b_id
            pass
        return v


class TeamSchema(BaseModel):
    """Schema for validating team data."""
    id: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    short_name: str = Field(..., min_length=1, max_length=50)
    game_id: str = Field(..., min_length=1, max_length=50)
    logo_url: Optional[str] = Field(None, max_length=500)
    region: Optional[str] = Field(None, max_length=50)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('logo_url')
    def validate_logo_url(cls, v):
        if v is not None and not v.startswith(('http://', 'https://')):
            raise ValueError("Logo URL must be a valid HTTP/HTTPS URL")
        return v


class PlayerSchema(BaseModel):
    """Schema for validating player data."""
    id: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    handle: str = Field(..., min_length=1, max_length=50)
    team_id: str = Field(..., min_length=1, max_length=50)
    game_id: str = Field(..., min_length=1, max_length=50)
    role: Optional[str] = Field(None, max_length=50)
    country: Optional[str] = Field(None, max_length=50)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventSchema(BaseModel):
    """Schema for validating game event data."""
    id: str = Field(..., min_length=1, max_length=50)
    match_id: str = Field(..., min_length=1, max_length=50)
    game_id: str = Field(..., min_length=1, max_length=50)
    type: EventTypeEnum
    timestamp: datetime
    sequence: int = Field(..., ge=0)
    team_id: Optional[str] = Field(None, max_length=50)
    player_id: Optional[str] = Field(None, max_length=50)
    payload: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="unknown", max_length=50)
    source_timestamp: Optional[datetime] = None
    received_at: datetime
    
    @validator('sequence')
    def validate_sequence(cls, v):
        if v < 0:
            raise ValueError("Sequence number must be non-negative")
        return v


def validate_game(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate game data against schema."""
    try:
        validated = GameSchema(**data)
        return validated.dict()
    except Exception as e:
        raise ValueError(f"Game validation failed: {str(e)}")


def validate_tournament(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate tournament data against schema."""
    try:
        validated = TournamentSchema(**data)
        return validated.dict()
    except Exception as e:
        raise ValueError(f"Tournament validation failed: {str(e)}")


def validate_match(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate match data against schema."""
    try:
        validated = MatchSchema(**data)
        return validated.dict()
    except Exception as e:
        raise ValueError(f"Match validation failed: {str(e)}")


def validate_team(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate team data against schema."""
    try:
        validated = TeamSchema(**data)
        return validated.dict()
    except Exception as e:
        raise ValueError(f"Team validation failed: {str(e)}")


def validate_player(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate player data against schema."""
    try:
        validated = PlayerSchema(**data)
        return validated.dict()
    except Exception as e:
        raise ValueError(f"Player validation failed: {str(e)}")


def validate_event(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate event data against schema."""
    try:
        validated = EventSchema(**data)
        return validated.dict()
    except Exception as e:
        raise ValueError(f"Event validation failed: {str(e)}")
