"""
Event ordering service for Phase 21A

This module implements event ordering with sequence validation, timestamp validation,
out-of-order buffering, duplicate rejection, and correction handling.

The state engine must always receive events in deterministic order.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from ..providers.base import GameEvent

logger = logging.getLogger("neural_market.esports.services.event_ordering")


class EventOrderingService:
    """
    Service for ordering game events.
    
    Implements:
    - Sequence validation
    - Timestamp validation
    - Out-of-order buffering
    - Duplicate rejection
    - Correction handling
    
    The state engine must always receive events in deterministic order.
    """
    
    def __init__(self, buffer_size: int = 1000, max_buffer_age_seconds: int = 300):
        """
        Initialize the event ordering service.
        
        Args:
            buffer_size: Maximum number of events to buffer
            max_buffer_age_seconds: Maximum age of buffered events in seconds
        """
        self._last_sequence: Dict[str, int] = {}  # match_id -> last_sequence
        self._event_buffers: Dict[str, List[GameEvent]] = {}  # match_id -> buffered events
        self._buffer_size = buffer_size
        self._max_buffer_age = timedelta(seconds=max_buffer_age_seconds)
        self._stats = {
            "total_processed": 0,
            "out_of_order": 0,
            "buffered": 0,
            "delivered_from_buffer": 0,
            "sequence_errors": 0,
            "timestamp_errors": 0,
        }
    
    async def order_event(self, event: GameEvent) -> Tuple[bool, Optional[GameEvent]]:
        """
        Order an event and return whether it's in correct order.
        
        Args:
            event: The event to order
            
        Returns:
            Tuple of (is_ordered, corrected_event)
            - is_ordered: True if event is in correct order
            - corrected_event: The event to use (may be corrected or buffered)
        """
        self._stats["total_processed"] += 1
        
        match_id = event.match_id
        expected_sequence = self._last_sequence.get(match_id, -1) + 1
        
        # Check sequence
        if event.sequence < expected_sequence:
            # Out of order event - buffer it
            return await self._buffer_event(event)
        
        if event.sequence > expected_sequence:
            # Gap detected - buffer and check if we can deliver from buffer
            await self._buffer_event(event)
            return await self._try_deliver_from_buffer(match_id, expected_sequence)
        
        # Correct sequence - validate timestamp
        if not await self._validate_timestamp(event):
            self._stats["timestamp_errors"] += 1
            logger.warning(f"Timestamp validation failed for event {event.id}")
            return (False, None)
        
        # Event is in correct order
        self._last_sequence[match_id] = event.sequence
        logger.debug(f"Event {event.id} is in correct order (sequence: {event.sequence})")
        return (True, event)
    
    async def _buffer_event(self, event: GameEvent) -> Tuple[bool, Optional[GameEvent]]:
        """
        Buffer an out-of-order event.
        
        Args:
            event: The event to buffer
            
        Returns:
            Tuple of (is_ordered, corrected_event)
        """
        match_id = event.match_id
        
        if match_id not in self._event_buffers:
            self._event_buffers[match_id] = []
        
        # Check buffer size
        if len(self._event_buffers[match_id]) >= self._buffer_size:
            # Buffer full - drop oldest event
            self._event_buffers[match_id].pop(0)
            logger.warning(f"Event buffer full for match {match_id}, dropped oldest event")
        
        self._event_buffers[match_id].append(event)
        self._stats["buffered"] += 1
        self._stats["out_of_order"] += 1
        
        logger.debug(f"Buffered out-of-order event {event.id} (sequence: {event.sequence})")
        return (False, None)
    
    async def _try_deliver_from_buffer(self, match_id: str, expected_sequence: int) -> Tuple[bool, Optional[GameEvent]]:
        """
        Try to deliver events from buffer in correct order.
        
        Args:
            match_id: Match identifier
            expected_sequence: Expected next sequence number
            
        Returns:
            Tuple of (is_ordered, corrected_event)
        """
        if match_id not in self._event_buffers:
            return (False, None)
        
        # Sort buffer by sequence
        self._event_buffers[match_id].sort(key=lambda e: e.sequence)
        
        # Find events that can be delivered
        deliverable = []
        remaining = []
        
        for event in self._event_buffers[match_id]:
            if event.sequence == expected_sequence:
                deliverable.append(event)
                expected_sequence += 1
            else:
                remaining.append(event)
        
        if deliverable:
            # Update buffer
            self._event_buffers[match_id] = remaining
            
            # Update last sequence
            self._last_sequence[match_id] = expected_sequence - 1
            
            # Return first deliverable event
            delivered_event = deliverable[0]
            self._stats["delivered_from_buffer"] += 1
            logger.info(f"Delivered {len(deliverable)} events from buffer for match {match_id}")
            
            # Store remaining events for next delivery
            for event in deliverable[1:]:
                self._event_buffers[match_id].append(event)
            
            return (True, delivered_event)
        
        return (False, None)
    
    async def _validate_timestamp(self, event: GameEvent) -> bool:
        """
        Validate event timestamp.
        
        Args:
            event: The event to validate
            
        Returns:
            True if timestamp is valid, False otherwise
        """
        # Check if timestamp is in the future (allow small clock skew)
        now = datetime.utcnow()
        max_future_seconds = 60  # Allow 1 minute future clock skew
        
        if event.timestamp > now + timedelta(seconds=max_future_seconds):
            logger.warning(
                f"Event timestamp is too far in the future: {event.timestamp} > {now}"
            )
            return False
        
        # Check if timestamp is too old (more than 24 hours)
        max_past_seconds = 86400  # 24 hours
        
        if event.timestamp < now - timedelta(seconds=max_past_seconds):
            logger.warning(
                f"Event timestamp is too old: {event.timestamp} < {now - timedelta(seconds=max_past_seconds)}"
            )
            return False
        
        return True
    
    async def cleanup_old_buffers(self) -> int:
        """
        Clean up old buffered events.
        
        Returns:
            Number of events cleaned up
        """
        cleaned = 0
        cutoff = datetime.utcnow() - self._max_buffer_age
        
        for match_id in list(self._event_buffers.keys()):
            # Filter out old events
            old_buffer = self._event_buffers[match_id]
            new_buffer = [
                event for event in old_buffer
                if event.timestamp > cutoff
            ]
            
            cleaned += len(old_buffer) - len(new_buffer)
            
            if new_buffer:
                self._event_buffers[match_id] = new_buffer
            else:
                del self._event_buffers[match_id]
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} old buffered events")
        
        return cleaned
    
    def get_stats(self) -> Dict[str, int]:
        """Get ordering statistics."""
        return self._stats.copy()
    
    def get_buffer_size(self, match_id: str) -> int:
        """Get the current buffer size for a match."""
        return len(self._event_buffers.get(match_id, []))
    
    def get_last_sequence(self, match_id: str) -> int:
        """Get the last processed sequence for a match."""
        return self._last_sequence.get(match_id, -1)
    
    def reset_match(self, match_id: str):
        """Reset ordering state for a specific match."""
        if match_id in self._last_sequence:
            del self._last_sequence[match_id]
        if match_id in self._event_buffers:
            del self._event_buffers[match_id]
        logger.info(f"Reset ordering state for match {match_id}")
    
    def reset_stats(self):
        """Reset ordering statistics."""
        self._stats = {
            "total_processed": 0,
            "out_of_order": 0,
            "buffered": 0,
            "delivered_from_buffer": 0,
            "sequence_errors": 0,
            "timestamp_errors": 0,
        }
