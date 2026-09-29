"""
Unit tests for MatchStateMachine

Tests deterministic match state transitions.
"""

import pytest
from datetime import datetime
from app.esports.state.match_state_machine import (
    MatchStateMachine,
    MatchState,
    TRANSITIONS,
    InvalidStateTransitionError
)


class TestMatchStateMachine:
    """Test suite for MatchStateMachine."""
    
    def test_initial_state(self):
        """Test initial state is set correctly."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        assert machine.get_current_state() == MatchState.SCHEDULED
    
    def test_valid_transition(self):
        """Test valid state transition."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        assert machine.can_transition_to(MatchState.UPCOMING)
        machine.transition_to(MatchState.UPCOMING)
        assert machine.get_current_state() == MatchState.UPCOMING
    
    def test_invalid_transition(self):
        """Test invalid state transition raises error."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        assert not machine.can_transition_to(MatchState.COMPLETED)
        with pytest.raises(InvalidStateTransitionError):
            machine.transition_to(MatchState.COMPLETED)
    
    def test_complete_match_flow(self):
        """Test complete match flow: SCHEDULED -> UPCOMING -> LIVE -> COMPLETED."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        
        # SCHEDULED -> UPCOMING
        machine.transition_to(MatchState.UPCOMING)
        assert machine.get_current_state() == MatchState.UPCOMING
        
        # UPCOMING -> LIVE
        machine.transition_to(MatchState.LIVE)
        assert machine.get_current_state() == MatchState.LIVE
        
        # LIVE -> COMPLETED
        machine.transition_to(MatchState.COMPLETED)
        assert machine.get_current_state() == MatchState.COMPLETED
    
    def test_terminal_states(self):
        """Test terminal states have no outgoing transitions."""
        assert TRANSITIONS[MatchState.COMPLETED] == set()
        assert TRANSITIONS[MatchState.CANCELLED] == set()
    
    def test_state_history(self):
        """Test state history is tracked."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        machine.transition_to(MatchState.UPCOMING)
        machine.transition_to(MatchState.LIVE)
        
        history = machine.get_state_history()
        assert len(history) == 3
        assert history[0][0] == MatchState.SCHEDULED
        assert history[1][0] == MatchState.UPCOMING
        assert history[2][0] == MatchState.LIVE
    
    def test_force_transition(self):
        """Test force transition for admin purposes."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        machine.force_transition_to(MatchState.COMPLETED, "Admin override")
        assert machine.get_current_state() == MatchState.COMPLETED
    
    def test_reset_to_state(self):
        """Test reset to specific state."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        machine.transition_to(MatchState.UPCOMING)
        machine.transition_to(MatchState.LIVE)
        
        machine.reset_to_state(MatchState.SCHEDULED, "Recovery")
        assert machine.get_current_state() == MatchState.SCHEDULED
        assert len(machine.get_state_history()) == 1
    
    def test_get_allowed_transitions(self):
        """Test getting allowed transitions."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        allowed = machine.get_allowed_transitions()
        assert MatchState.UPCOMING in allowed
        assert MatchState.CANCELLED in allowed
        assert MatchState.POSTPONED in allowed
        assert MatchState.LIVE not in allowed
    
    def test_is_terminal_state(self):
        """Test terminal state detection.

        SCHEDULED is not terminal; a match reaches terminal COMPLETED through
        the canonical path (SCHEDULED -> UPCOMING -> LIVE -> COMPLETED).
        """
        machine = MatchStateMachine(MatchState.SCHEDULED)
        assert not machine.is_terminal_state()

        machine.transition_to(MatchState.UPCOMING)
        machine.transition_to(MatchState.LIVE)
        machine.transition_to(MatchState.COMPLETED)
        assert machine.is_terminal_state()
    
    def test_transition_count(self):
        """Test transition count is tracked."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        assert machine.get_transition_count() == 0
        
        machine.transition_to(MatchState.UPCOMING)
        assert machine.get_transition_count() == 1
        
        machine.transition_to(MatchState.LIVE)
        assert machine.get_transition_count() == 2
    
    def test_paused_flow(self):
        """Test match pause and resume flow."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        machine.transition_to(MatchState.UPCOMING)
        machine.transition_to(MatchState.LIVE)
        
        # LIVE -> PAUSED
        machine.transition_to(MatchState.PAUSED)
        assert machine.get_current_state() == MatchState.PAUSED
        
        # PAUSED -> LIVE
        machine.transition_to(MatchState.LIVE)
        assert machine.get_current_state() == MatchState.LIVE
    
    def test_map_break_flow(self):
        """Test map break flow."""
        machine = MatchStateMachine(MatchState.SCHEDULED)
        machine.transition_to(MatchState.UPCOMING)
        machine.transition_to(MatchState.LIVE)
        
        # LIVE -> MAP_BREAK
        machine.transition_to(MatchState.MAP_BREAK)
        assert machine.get_current_state() == MatchState.MAP_BREAK
        
        # MAP_BREAK -> LIVE
        machine.transition_to(MatchState.LIVE)
        assert machine.get_current_state() == MatchState.LIVE


class TestMatchStateTransitions:
    """Test suite for state transition constants."""
    
    def test_transitions_dict_completeness(self):
        """Test all states have transition definitions."""
        all_states = set(MatchState)
        defined_states = set(TRANSITIONS.keys())
        assert all_states == defined_states
    
    def test_transitions_are_sets(self):
        """Test all transition values are sets."""
        for state, transitions in TRANSITIONS.items():
            assert isinstance(transitions, set)
    
    def test_no_self_transitions(self):
        """Test no state transitions to itself."""
        for state, transitions in TRANSITIONS.items():
            assert state not in transitions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
