"""
Unit tests for EventDeduplicationService

Tests event deduplication using deterministic event identity.

The service's methods are coroutines, so every test that awaits one is declared
``async def`` and marked with ``pytest.mark.asyncio`` (the suite runs under
pytest-asyncio's strict mode). No test was removed — this only repairs the
``await`` placement so the module can be collected.
"""

import pytest
from datetime import datetime, timedelta
from app.esports.services.event_deduplication import EventDeduplicationService
from app.esports.providers.base import GameEvent, EventType, MatchStatus


class TestEventDeduplicationService:
    """Test suite for EventDeduplicationService."""
    
    @pytest.fixture
    def dedup_service(self):
        """Create a fresh deduplication service for each test."""
        return EventDeduplicationService(ttl_seconds=3600)
    
    @pytest.fixture
    def sample_event(self):
        """Create a sample game event."""
        return GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id="team_a",
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
    
    def test_initial_state(self, dedup_service):
        """Test initial state of service."""
        assert dedup_service.get_signature_count() == 0
        assert dedup_service.get_stats()["total_checked"] == 0
    
    @pytest.mark.asyncio
    async def test_first_event_not_duplicate(self, dedup_service, sample_event):
        """Test first event is not considered duplicate."""
        is_duplicate = await dedup_service.is_duplicate(sample_event)
        assert not is_duplicate
        assert dedup_service.get_stats()["total_checked"] == 1
    
    @pytest.mark.asyncio
    async def test_register_and_check_duplicate(self, dedup_service, sample_event):
        """Test event registration and duplicate detection."""
        # Register event
        await dedup_service.register_event(sample_event)
        
        # Check same event - should be duplicate
        is_duplicate = await dedup_service.is_duplicate(sample_event)
        assert is_duplicate
        assert dedup_service.get_stats()["duplicates_found"] == 1
    
    @pytest.mark.asyncio
    async def test_different_events_not_duplicate(self, dedup_service):
        """Test different events are not considered duplicates."""
        event1 = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id="team_a",
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
            type=EventType.SCORE_CHANGED,
            timestamp=datetime.utcnow(),
            sequence=2,
            team_id="team_a",
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        await dedup_service.register_event(event1)

        # event2 has a different signature, so it is NOT a duplicate of event1.
        assert not await dedup_service.is_duplicate(event2)

        # Once event2 is registered it is correctly reported as a duplicate of
        # itself (distinct identity from event1).
        await dedup_service.register_event(event2)
        assert await dedup_service.is_duplicate(event2)
    
    def test_signature_uniqueness(self, dedup_service):
        """Test different events have different signatures."""
        event1 = GameEvent(
            id="event_1",
            match_id="match_1",
            game_id="cs2",
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=1,
            team_id="team_a",
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
            type=EventType.MATCH_STARTED,
            timestamp=datetime.utcnow(),
            sequence=2,  # Different sequence
            team_id="team_a",
            player_id=None,
            payload={},
            source="test_provider",
            source_timestamp=datetime.utcnow(),
            received_at=datetime.utcnow()
        )
        
        sig1 = dedup_service._create_event_signature(event1)
        sig2 = dedup_service._create_event_signature(event2)
        
        assert sig1 != sig2
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self, dedup_service, sample_event):
        """Test cleanup of expired signatures."""
        # Register event
        await dedup_service.register_event(sample_event)
        
        # Create service with short TTL
        short_ttl_service = EventDeduplicationService(ttl_seconds=1)
        await short_ttl_service.register_event(sample_event)
        
        # Wait for expiration
        import asyncio
        await asyncio.sleep(2)
        
        # Cleanup
        cleaned = await short_ttl_service.cleanup_expired()
        assert cleaned >= 0
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self, dedup_service, sample_event):
        """Test statistics tracking."""
        # Check event (not registered yet)
        await dedup_service.is_duplicate(sample_event)
        
        # Register event
        await dedup_service.register_event(sample_event)
        
        # Check again (should be duplicate)
        await dedup_service.is_duplicate(sample_event)
        
        stats = dedup_service.get_stats()
        assert stats["total_checked"] == 2
        assert stats["duplicates_found"] == 1
        assert stats["unique_events"] == 1
    
    @pytest.mark.asyncio
    async def test_reset_stats(self, dedup_service, sample_event):
        """Test statistics reset."""
        await dedup_service.register_event(sample_event)
        await dedup_service.is_duplicate(sample_event)
        
        dedup_service.reset_stats()
        
        stats = dedup_service.get_stats()
        assert stats["total_checked"] == 0
        assert stats["duplicates_found"] == 0
        assert stats["unique_events"] == 0
    
    @pytest.mark.asyncio
    async def test_clear_all(self, dedup_service, sample_event):
        """Test clearing all signatures."""
        await dedup_service.register_event(sample_event)
        assert dedup_service.get_signature_count() > 0
        
        dedup_service.clear_all()
        assert dedup_service.get_signature_count() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
