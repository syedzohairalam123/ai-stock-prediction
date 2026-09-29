"""
Event deduplication service for Phase 21A

Real-time feeds can duplicate events. This service creates deterministic event identity
and prevents duplicate records from being created.
"""

from datetime import datetime, timedelta
from typing import Dict, Set, Optional
import hashlib
import logging
from ..providers.base import GameEvent

logger = logging.getLogger("neural_market.esports.services.event_deduplication")


class EventDeduplicationService:
    """
    Service for deduplicating game events.
    
    Real-time feeds can duplicate events. This service creates deterministic event identity
    using available fields such as provider, matchId, sequence, eventType.
    
    Duplicate events must not create duplicate records.
    """
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        Initialize the deduplication service.
        
        Args:
            ttl_seconds: Time-to-live for deduplication records (default: 1 hour)
        """
        self._event_signatures: Dict[str, datetime] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = None  # In production, use asyncio.Lock
        self._stats = {
            "total_checked": 0,
            "duplicates_found": 0,
            "unique_events": 0,
        }
    
    def _create_event_signature(self, event: GameEvent) -> str:
        """
        Create a deterministic signature for an event.
        
        Uses provider, matchId, sequence, eventType to create a unique identifier.
        
        Args:
            event: The event to create a signature for
            
        Returns:
            SHA256 hash signature
        """
        # Create a deterministic string from event fields
        signature_string = f"{event.source}:{event.match_id}:{event.sequence}:{event.type.value}"
        
        # Add optional fields if present
        if event.team_id:
            signature_string += f":{event.team_id}"
        if event.player_id:
            signature_string += f":{event.player_id}"
        
        # Create hash
        return hashlib.sha256(signature_string.encode()).hexdigest()
    
    async def is_duplicate(self, event: GameEvent) -> bool:
        """
        Check if an event is a duplicate.
        
        Args:
            event: The event to check
            
        Returns:
            True if the event is a duplicate, False otherwise
        """
        self._stats["total_checked"] += 1
        
        signature = self._create_event_signature(event)
        
        # Check if signature exists and is within TTL
        if signature in self._event_signatures:
            timestamp = self._event_signatures[signature]
            if datetime.utcnow() - timestamp < timedelta(seconds=self._ttl_seconds):
                self._stats["duplicates_found"] += 1
                logger.debug(f"Duplicate event detected: {event.id} (signature: {signature[:16]}...)")
                return True
        
        return False
    
    async def register_event(self, event: GameEvent) -> None:
        """
        Register an event as seen to prevent future duplicates.
        
        Args:
            event: The event to register
        """
        signature = self._create_event_signature(event)
        self._event_signatures[signature] = datetime.utcnow()
        self._stats["unique_events"] += 1
        logger.debug(f"Registered event: {event.id} (signature: {signature[:16]}...)")
    
    async def cleanup_expired(self) -> int:
        """
        Clean up expired deduplication records.
        
        Returns:
            Number of records cleaned up
        """
        cutoff = datetime.utcnow() - timedelta(seconds=self._ttl_seconds)
        expired_signatures = [
            sig for sig, timestamp in self._event_signatures.items()
            if timestamp < cutoff
        ]
        
        for sig in expired_signatures:
            del self._event_signatures[sig]
        
        if expired_signatures:
            logger.info(f"Cleaned up {len(expired_signatures)} expired deduplication records")
        
        return len(expired_signatures)
    
    def get_stats(self) -> Dict[str, int]:
        """Get deduplication statistics."""
        return self._stats.copy()
    
    def get_signature_count(self) -> int:
        """Get the current number of stored signatures."""
        return len(self._event_signatures)
    
    def reset_stats(self):
        """Reset deduplication statistics."""
        self._stats = {
            "total_checked": 0,
            "duplicates_found": 0,
            "unique_events": 0,
        }
    
    def clear_all(self):
        """Clear all stored signatures (use with caution)."""
        self._event_signatures.clear()
        logger.warning("Cleared all deduplication signatures")
