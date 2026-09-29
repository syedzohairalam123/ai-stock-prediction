"""
Unit tests for MatchStateEngine

Tests live state reconstruction from normalized events.
"""

import pytest
from datetime import datetime, timezone
from app.esports.state.event_engine import MatchStateEngine
from app.esports.providers.base import GameEvent, EventType, Match, MatchStatus, EsportsDataStatus


class TestMatchStateEngine:
    """Test suite for MatchStateEngine."""
    
    @pytest.fixture
    def sample_match(self):
        """Create a sample match."""
        return Match(
            id="match_1",
            external_id="ext_match_1",
            game_id="cs2",
            tournament_id="tournament_1",
            series_id="series_1",
            status=MatchStatus.SCHEDULED,
            scheduled_at=datetime.utcnow(),
            team_a_id="team_a",
            team_b_id="team_b",
            started_at=None,
            ended_at=None,
            best_of=3,
            current_map=None,
            map_number=0,
            score_a=0,
            score_b=0,
            winner_id=None,
            source="test_provider",
            source_timestamp=None,
            received_at=datetime.utcnow()
        )
    
    @pytest.fixture
    def state_engine(self, sample_match):
        """Create a state engine for testing."""
        return MatchStateEngine(sample_match)
    
    def test_initial_state(self, state_engine):
        """Test initial state of engine."""
        snapshot = state_engine.get_current_snapshot()
        assert snapshot.match_id == "match_1"
        assert snapshot.status == MatchStatus.SCHEDULED
        assert snapshot.score_a == 0
        assert snapshot.score_b == 0
    
    def test_match_started_event(self, state_engine):
        """Test MATCH_STARTED event processing."""
        event = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        result = state_engine.process_event(event)
        assert result is True
        
        snapshot = state_engine.get_current_snapshot()
        assert snapshot.status == MatchStatus.LIVE
        assert state_engine.match.started_at is not None
    
    def test_map_started_event(self, state_engine):
        """Test MAP_STARTED event processing."""
        # First start match
        match_started = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        state_engine.process_event(match_started)
        
        # Start map
        map_started = GameEvent(
            id="event_2",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MAP_STARTED,
            timestamp=datetime.utcnow(),
            sequence=2,
            team_id=None,
            player_id=None,
            payload={"map_name": "Dust2"},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        result = state_engine.process_event(map_started)
        assert result is True
        
        snapshot = state_engine.get_current_snapshot()
        assert snapshot.current_map == "Dust2"
        assert snapshot.map_number == 1
        assert "Dust2" in snapshot.current_map_scores
    
    def test_score_changed_event(self, state_engine):
        """Test SCORE_CHANGED event processing."""
        # Start match and map
        match_started = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        state_engine.process_event(match_started)
        
        map_started = GameEvent(
            id="event_2",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MAP_STARTED,
            timestamp=datetime.utcnow(),
            sequence=2,
            team_id=None,
            player_id=None,
            payload={"map_name": "Dust2"},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        state_engine.process_event(map_started)
        
        # Change score
        score_changed = GameEvent(
            id="event_3",
            match_id="match_1",
            game_id="cs2",
            type=EventType.SCORE_CHANGED,
            timestamp=datetime.utcnow(),
            sequence=3,
            team_id="team_a",
            player_id=None,
            payload={"team_a_score": 1, "team_b_score": 0},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        result = state_engine.process_event(score_changed)
        assert result is True
        
        snapshot = state_engine.get_current_snapshot()
        assert snapshot.score_a == 1
        assert snapshot.score_b == 0
    
    def test_match_ended_event(self, state_engine):
        """Test MATCH_ENDED event processing."""
        # Start match
        match_started = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        state_engine.process_event(match_started)
        
        # End match
        match_ended = GameEvent(
            id="event_2",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_ENDED,
            timestamp=datetime.utcnow(),
            sequence=2,
            team_id=None,
            player_id=None,
            payload={"winner_id": "team_a"},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        result = state_engine.process_event(match_ended)
        assert result is True
        
        snapshot = state_engine.get_current_snapshot()
        assert snapshot.status == MatchStatus.COMPLETED
        assert state_engine.match.winner_id == "team_a"
    
    def test_out_of_order_sequence(self, state_engine):
        """Test out-of-order event sequence."""
        # Process sequence 2 first
        event2 = GameEvent(
            id="event_2",
            match_id="match_1",
            game_id="cs2",
            type=EventType.SCORE_CHANGED,
            timestamp=datetime.utcnow(),
            sequence=2,
            team_id="team_a",
            player_id=None,
            payload={"team_a_score": 1, "team_b_score": 0},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        result = state_engine.process_event(event2)
        # The first observed event (sequence 2) is accepted — "out of order" is
        # only defined relative to an already-seen sequence.
        assert result is True

        # A follow-up event carrying an earlier sequence is the out-of-order
        # case and must be rejected.
        stale = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.SCORE_CHANGED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id="team_a",
            player_id=None,
            payload={"team_a_score": 0, "team_b_score": 0},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        assert state_engine.process_event(stale) is False
    
    def test_event_sequence_tracking(self, state_engine):
        """Test event sequence tracking."""
        event1 = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        event2 = GameEvent(
            id="event_2",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MAP_STARTED,
            timestamp=datetime.utcnow(),
            sequence=2,
            team_id=None,
            player_id=None,
            payload={"map_name": "Dust2"},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        state_engine.process_event(event1)
        state_engine.process_event(event2)
        
        assert state_engine.last_processed_sequence == 2
        assert len(state_engine.get_processed_events()) == 2
    
    def test_reset_engine(self, state_engine):
        """Test engine reset."""
        event = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        state_engine.process_event(event)
        assert state_engine.last_processed_sequence == 1
        
        state_engine.reset()
        assert state_engine.last_processed_sequence == -1
        assert len(state_engine.get_processed_events()) == 0
    
    def test_data_freshness_calculation(self, state_engine):
        """Test data freshness calculation."""
        event = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id=None,
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        state_engine.process_event(event)
        snapshot = state_engine.get_current_snapshot()
        
        # Should be LIVE since event just happened
        assert snapshot.data_status == EsportsDataStatus.LIVE
        assert snapshot.data_age_seconds is not None
        assert snapshot.data_age_seconds < 5  # Less than 5 seconds
    
    def test_get_state_machine(self, state_engine):
        """Test getting the underlying state machine."""
        state_machine = state_engine.get_state_machine()
        assert state_machine is not None
        assert state_machine.get_current_state() == MatchStatus.SCHEDULED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
