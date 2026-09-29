"""
Match state machine for Phase 21A

This module implements deterministic match state transitions.
Never let the frontend directly change authoritative match state.
"""

from enum import Enum
from typing import Dict, Set, Optional
from datetime import datetime
import logging

logger = logging.getLogger("neural_market.esports.state.match_state_machine")


class MatchState(str, Enum):
    """Deterministic match states."""
    SCHEDULED = "SCHEDULED"
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    MAP_BREAK = "MAP_BREAK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"
    UNKNOWN = "UNKNOWN"


# Explicit allowed transitions
TRANSITIONS: Dict[MatchState, Set[MatchState]] = {
    MatchState.SCHEDULED: {MatchState.UPCOMING, MatchState.CANCELLED, MatchState.POSTPONED},
    MatchState.UPCOMING: {MatchState.LIVE, MatchState.CANCELLED, MatchState.POSTPONED},
    MatchState.LIVE: {MatchState.PAUSED, MatchState.MAP_BREAK, MatchState.COMPLETED, MatchState.CANCELLED},
    MatchState.PAUSED: {MatchState.LIVE, MatchState.CANCELLED},
    MatchState.MAP_BREAK: {MatchState.LIVE, MatchState.COMPLETED, MatchState.CANCELLED},
    MatchState.COMPLETED: set(),  # Terminal state
    MatchState.CANCELLED: set(),  # Terminal state
    MatchState.POSTPONED: {MatchState.SCHEDULED, MatchState.UPCOMING, MatchState.CANCELLED},
    MatchState.UNKNOWN: {MatchState.SCHEDULED, MatchState.UPCOMING, MatchState.LIVE, MatchState.CANCELLED},
}


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, current_state: MatchState, target_state: MatchState):
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            f"Invalid state transition from {current_state.value} to {target_state.value}. "
            f"Allowed transitions: {[s.value for s in TRANSITIONS.get(current_state, set())]}"
        )


class MatchStateMachine:
    """
    Deterministic match state machine.
    
    This class enforces valid state transitions and prevents unauthorized state changes.
    The frontend can never directly change the authoritative match state.
    """
    
    def __init__(self, initial_state: MatchState = MatchState.SCHEDULED):
        """
        Initialize the state machine.
        
        Args:
            initial_state: Initial match state
        """
        self.current_state = initial_state
        self.state_history: list[tuple[MatchState, datetime]] = [(initial_state, datetime.utcnow())]
        self._transition_count = 0
    
    def get_current_state(self) -> MatchState:
        """Get the current match state."""
        return self.current_state
    
    def get_state_history(self) -> list[tuple[MatchState, datetime]]:
        """Get the complete state transition history."""
        return self.state_history.copy()
    
    def can_transition_to(self, target_state: MatchState) -> bool:
        """
        Check if a transition to the target state is allowed.
        
        Args:
            target_state: Target state to check
            
        Returns:
            True if transition is allowed, False otherwise
        """
        allowed_transitions = TRANSITIONS.get(self.current_state, set())
        return target_state in allowed_transitions
    
    def transition_to(self, target_state: MatchState, metadata: Optional[dict] = None) -> bool:
        """
        Attempt to transition to the target state.
        
        Args:
            target_state: Target state to transition to
            metadata: Optional metadata about the transition
            
        Returns:
            True if transition was successful, False otherwise
            
        Raises:
            InvalidStateTransitionError: If the transition is not allowed
        """
        if not self.can_transition_to(target_state):
            raise InvalidStateTransitionError(self.current_state, target_state)
        
        # Perform the transition
        previous_state = self.current_state
        self.current_state = target_state
        self.state_history.append((target_state, datetime.utcnow()))
        self._transition_count += 1
        
        logger.info(
            f"State transition: {previous_state.value} -> {target_state.value} "
            f"(Transition #{self._transition_count})"
        )
        
        if metadata:
            logger.debug(f"Transition metadata: {metadata}")
        
        return True
    
    def force_transition_to(self, target_state: MatchState, reason: str) -> bool:
        """
        Force a transition (for admin/recovery purposes only).
        
        This should only be used in exceptional circumstances and requires
        explicit justification.
        
        Args:
            target_state: Target state to transition to
            reason: Reason for the forced transition
            
        Returns:
            True if transition was successful
        """
        previous_state = self.current_state
        self.current_state = target_state
        self.state_history.append((target_state, datetime.utcnow()))
        self._transition_count += 1
        
        logger.warning(
            f"FORCED state transition: {previous_state.value} -> {target_state.value}. "
            f"Reason: {reason}"
        )
        
        return True
    
    def reset_to_state(self, target_state: MatchState, reason: str) -> bool:
        """
        Reset the state machine to a specific state (for recovery purposes).
        
        This clears the state history and starts fresh from the target state.
        
        Args:
            target_state: Target state to reset to
            reason: Reason for the reset
            
        Returns:
            True if reset was successful
        """
        previous_state = self.current_state
        self.current_state = target_state
        self.state_history = [(target_state, datetime.utcnow())]
        self._transition_count = 0
        
        logger.warning(
            f"State machine reset: {previous_state.value} -> {target_state.value}. "
            f"Reason: {reason}"
        )
        
        return True
    
    def get_transition_count(self) -> int:
        """Get the total number of state transitions."""
        return self._transition_count
    
    def is_terminal_state(self) -> bool:
        """Check if the current state is a terminal state."""
        return not TRANSITIONS.get(self.current_state, set())
    
    def get_allowed_transitions(self) -> Set[MatchState]:
        """Get the set of allowed transitions from the current state."""
        return TRANSITIONS.get(self.current_state, set()).copy()
    
    @classmethod
    def get_all_states(cls) -> Set[MatchState]:
        """Get all possible match states."""
        return set(MatchState)
    
    @classmethod
    def get_transitions_for_state(cls, state: MatchState) -> Set[MatchState]:
        """Get allowed transitions for a specific state."""
        return TRANSITIONS.get(state, set()).copy()
