"""
Match state engine for Phase 21A

This module implements live state reconstruction from normalized events.
The engine must be independently unit-testable.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import logging
from app.esports.state.match_state_machine import MatchStateMachine, MatchState
from app.esports.providers.base import GameEvent, EventType, Match, LiveSnapshot, EsportsDataStatus

logger = logging.getLogger("neural_market.esports.state.event_engine")


class MatchStateEngine:
    """
    Live state reconstruction engine.
    
    This engine processes normalized events and reconstructs the current match state.
    Input: normalized events
    Output: current match snapshot
    
    Example flow:
    MATCH_STARTED → MAP_STARTED → GAME EVENTS → SCORE_CHANGED → MAP_ENDED → NEXT MAP → MATCH_COMPLETED
    """
    
    def __init__(self, match: Match):
        """
        Initialize the state engine for a match.
        
        Args:
            match: The match to track state for
        """
        self.match = match
        self.state_machine = MatchStateMachine(MatchState.SCHEDULED)
        self.current_map: Optional[str] = None
        self.map_number = 0
        self.current_map_scores: Dict[str, Dict[str, int]] = {}
        self.game_state: Dict[str, Any] = {}
        self.processed_events: List[GameEvent] = []
        self.last_event_timestamp: Optional[datetime] = None
        self.last_processed_sequence = -1

    # Phase 21B fix: the state machine only allows SCHEDULED→UPCOMING→LIVE, but
    # a live provider frequently reports MATCH_STARTED/MAP_STARTED before the
    # intermediate UPCOMING transition was ever observed. Walking the canonical
    # forward path keeps the engine's deterministic transitions intact while
    # letting real live events actually apply (instead of raising
    # InvalidStateTransitionError and silently dropping every event).
    _CANONICAL_PATH = {
        MatchState.SCHEDULED: [MatchState.UPCOMING, MatchState.LIVE],
        MatchState.UPCOMING: [MatchState.LIVE],
        MatchState.POSTPONED: [MatchState.SCHEDULED, MatchState.UPCOMING, MatchState.LIVE],
        MatchState.MAP_BREAK: [MatchState.LIVE],
        MatchState.PAUSED: [MatchState.LIVE],
    }

    def _advance_to(self, target: MatchState, metadata: Optional[dict] = None) -> bool:
        """Move the state machine towards ``target`` via allowed transitions."""
        machine = self.state_machine
        if machine.get_current_state() == target:
            return True
        if machine.can_transition_to(target):
            return machine.transition_to(target, metadata)
        for intermediate in self._CANONICAL_PATH.get(machine.get_current_state(), []):
            if machine.get_current_state() == target:
                return True
            if machine.can_transition_to(intermediate):
                machine.transition_to(intermediate, metadata)
                if machine.get_current_state() == target:
                    return True
        if machine.can_transition_to(target):
            return machine.transition_to(target, metadata)
        # A corrected/out-of-order event that cannot be reached through the
        # forward path is forced (recovery), never silently dropped.
        return machine.force_transition_to(target, "event reconstruction")
    
    def process_event(self, event: GameEvent) -> bool:
        """
        Process a single event and update match state.
        
        Args:
            event: The event to process
            
        Returns:
            True if event was processed successfully, False otherwise
        """
        try:
            # Validate event sequence
            if event.sequence <= self.last_processed_sequence:
                logger.warning(
                    f"Event sequence out of order: {event.sequence} (last: {self.last_processed_sequence})"
                )
                return False
            
            # Update last processed sequence
            self.last_processed_sequence = event.sequence
            self.last_event_timestamp = event.timestamp
            
            # Process event based on type
            if event.type == EventType.MATCH_STARTED:
                self._handle_match_started(event)
            elif event.type == EventType.MAP_STARTED:
                self._handle_map_started(event)
            elif event.type == EventType.ROUND_STARTED:
                self._handle_round_started(event)
            elif event.type == EventType.ROUND_ENDED:
                self._handle_round_ended(event)
            elif event.type == EventType.SCORE_CHANGED:
                self._handle_score_changed(event)
            elif event.type == EventType.PLAYER_EVENT:
                self._handle_player_event(event)
            elif event.type == EventType.OBJECTIVE_EVENT:
                self._handle_objective_event(event)
            elif event.type == EventType.MAP_ENDED:
                self._handle_map_ended(event)
            elif event.type == EventType.MATCH_PAUSED:
                self._handle_match_paused(event)
            elif event.type == EventType.MATCH_RESUMED:
                self._handle_match_resumed(event)
            elif event.type == EventType.MATCH_ENDED:
                self._handle_match_ended(event)
            else:
                logger.warning(f"Unknown event type: {event.type}")
                return False
            
            # Add to processed events
            self.processed_events.append(event)
            
            logger.debug(f"Processed event: {event.type.value} for match {self.match.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to process event: {str(e)}")
            return False
    
    def _handle_match_started(self, event: GameEvent):
        """Handle MATCH_STARTED event."""
        self._advance_to(MatchState.LIVE, {"event_id": event.id})
        self.match.started_at = event.timestamp
        self.game_state["match_started"] = True
    
    def _handle_map_started(self, event: GameEvent):
        """Handle MAP_STARTED event."""
        self._advance_to(MatchState.LIVE, {"event_id": event.id})
        self.map_number += 1
        self.current_map = event.payload.get("map_name", f"Map {self.map_number}")
        self.current_map_scores[self.current_map] = {
            "team_a": 0,
            "team_b": 0
        }
        self.match.current_map = self.current_map
        self.match.map_number = self.map_number
        self.game_state["current_map"] = self.current_map
    
    def _handle_round_started(self, event: GameEvent):
        """Handle ROUND_STARTED event."""
        self.game_state["round_number"] = event.payload.get("round_number", 0)
        self.game_state["round_started"] = True
    
    def _handle_round_ended(self, event: GameEvent):
        """Handle ROUND_ENDED event."""
        self.game_state["round_ended"] = True
        winner = event.payload.get("winner")
        if winner:
            self.game_state["round_winner"] = winner
    
    def _handle_score_changed(self, event: GameEvent):
        """
        Handle SCORE_CHANGED event.

        Phase 21C §20/§25: only a real numeric score is published. A provider
        that sends a missing/null/non-numeric score leaves the last known good
        value in place rather than pushing a fabricated or invalid score into
        the snapshot the UI renders.
        """
        raw_a = event.payload.get("team_a_score")
        raw_b = event.payload.get("team_b_score")
        if isinstance(raw_a, bool) or isinstance(raw_b, bool):
            logger.warning(f"Ignoring non-numeric score in event {event.id}")
            return
        if not isinstance(raw_a, (int, float)) or not isinstance(raw_b, (int, float)):
            logger.warning(
                f"Ignoring incomplete score payload in event {event.id}: "
                f"team_a_score={raw_a!r}, team_b_score={raw_b!r}"
            )
            return

        team_a_score = int(raw_a)
        team_b_score = int(raw_b)
        
        self.match.score_a = team_a_score
        self.match.score_b = team_b_score
        
        # Update current map scores if we're in a map
        if self.current_map and self.current_map in self.current_map_scores:
            self.current_map_scores[self.current_map]["team_a"] = team_a_score
            self.current_map_scores[self.current_map]["team_b"] = team_b_score
        
        self.game_state["score"] = {
            "team_a": team_a_score,
            "team_b": team_b_score
        }
    
    def _handle_player_event(self, event: GameEvent):
        """Handle PLAYER_EVENT event."""
        player_id = event.player_id
        event_type = event.payload.get("player_event_type")
        
        if player_id and event_type:
            if "player_events" not in self.game_state:
                self.game_state["player_events"] = []
            
            self.game_state["player_events"].append({
                "player_id": player_id,
                "event_type": event_type,
                "timestamp": event.timestamp.isoformat(),
                "details": event.payload
            })
    
    def _handle_objective_event(self, event: GameEvent):
        """Handle OBJECTIVE_EVENT event."""
        objective_type = event.payload.get("objective_type")
        team_id = event.team_id
        
        if objective_type:
            if "objectives" not in self.game_state:
                self.game_state["objectives"] = []
            
            self.game_state["objectives"].append({
                "objective_type": objective_type,
                "team_id": team_id,
                "timestamp": event.timestamp.isoformat(),
                "details": event.payload
            })
    
    def _handle_map_ended(self, event: GameEvent):
        """Handle MAP_ENDED event."""
        self._advance_to(MatchState.MAP_BREAK, {"event_id": event.id})
        winner_id = event.payload.get("winner_id")
        
        if self.current_map and self.current_map in self.current_map_scores:
            self.current_map_scores[self.current_map]["winner_id"] = winner_id
        
        self.game_state["map_ended"] = True
        self.game_state["map_winner"] = winner_id
    
    def _handle_match_paused(self, event: GameEvent):
        """Handle MATCH_PAUSED event."""
        self._advance_to(MatchState.PAUSED, {"event_id": event.id})
        self.game_state["paused"] = True
    
    def _handle_match_resumed(self, event: GameEvent):
        """Handle MATCH_RESUMED event."""
        self._advance_to(MatchState.LIVE, {"event_id": event.id})
        self.game_state["paused"] = False
    
    def _handle_match_ended(self, event: GameEvent):
        """Handle MATCH_ENDED event."""
        self._advance_to(MatchState.COMPLETED, {"event_id": event.id})
        self.match.ended_at = event.timestamp
        winner_id = event.payload.get("winner_id")
        self.match.winner_id = winner_id
        self.game_state["match_ended"] = True
        self.game_state["winner"] = winner_id
    
    def get_current_snapshot(self) -> LiveSnapshot:
        """
        Get the current match snapshot.
        
        Returns:
            LiveSnapshot representing current match state
        """
        # Calculate data age
        data_age_seconds = None
        if self.last_event_timestamp:
            # Tolerate a naive provider timestamp instead of raising a
            # TypeError that would blank the whole snapshot.
            reference = self.last_event_timestamp
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=timezone.utc)
            # Phase 21C §25: clamp at zero. A provider whose clock runs ahead
            # (or a skewed source timestamp) would otherwise publish a negative
            # age, which is meaningless to a reader and must never be shown.
            data_age_seconds = max(0.0, (datetime.now(timezone.utc) - reference).total_seconds())
        
        # Determine data status
        data_status = EsportsDataStatus.LIVE
        if data_age_seconds is not None:
            if data_age_seconds < 30:
                data_status = EsportsDataStatus.LIVE
            elif data_age_seconds < 300:
                data_status = EsportsDataStatus.RECENT
            elif data_age_seconds < 1800:
                data_status = EsportsDataStatus.DELAYED
            else:
                data_status = EsportsDataStatus.STALE
        
        return LiveSnapshot(
            match_id=self.match.id,
            game_id=self.match.game_id,
            status=self.state_machine.get_current_state(),
            current_map=self.current_map,
            map_number=self.map_number,
            score_a=self.match.score_a,
            score_b=self.match.score_b,
            team_a_id=self.match.team_a_id,
            team_b_id=self.match.team_b_id,
            current_map_scores=self.current_map_scores,
            game_state=self.game_state,
            timestamp=datetime.now(timezone.utc),
            data_age_seconds=data_age_seconds,
            data_status=data_status
        )
    
    def get_processed_events(self) -> List[GameEvent]:
        """Get all processed events."""
        return self.processed_events.copy()
    
    def get_state_machine(self) -> MatchStateMachine:
        """Get the underlying state machine."""
        return self.state_machine
    
    def reset(self):
        """Reset the engine to initial state."""
        self.state_machine = MatchStateMachine(MatchState.SCHEDULED)
        self.current_map = None
        self.map_number = 0
        self.current_map_scores = {}
        self.game_state = {}
        self.processed_events = []
        self.last_event_timestamp = None
        self.last_processed_sequence = -1
        logger.info(f"Reset state engine for match {self.match.id}")
