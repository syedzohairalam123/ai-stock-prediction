"""
Normalization pipeline for Phase 21A

This module implements the complete data normalization pipeline:
External Provider → Provider Adapter → Schema Validation → Normalization → 
Deduplication → Event Ordering → State Reconstruction → Database → Redis/Event Bus → WebSocket

Every stage must be independently testable.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
import asyncio
import logging
from app.esports.normalization.schemas import (
    validate_game, validate_tournament, validate_match, 
    validate_team, validate_player, validate_event
)
from app.esports.providers.base import (
    Game, Tournament, Match, Team, Player, GameEvent,
    EsportsProviderError, EsportsDataStatus
)

logger = logging.getLogger("neural_market.esports.normalization.pipeline")


class NormalizationPipeline:
    """
    Complete normalization pipeline for esports data.
    
    This pipeline handles:
    - Schema validation
    - Data normalization
    - Deduplication
    - Event ordering
    - State reconstruction
    """
    
    def __init__(self, deduplication_service=None, ordering_service=None):
        """
        Initialize the normalization pipeline.
        
        Args:
            deduplication_service: Service for event deduplication
            ordering_service: Service for event ordering
        """
        self.deduplication_service = deduplication_service
        self.ordering_service = ordering_service
        self._stats = {
            "total_processed": 0,
            "validation_errors": 0,
            "deduplication_skipped": 0,
            "ordering_corrected": 0,
        }
    
    async def process_game(self, raw_data: Dict[str, Any], source: str) -> Optional[Game]:
        """
        Process game data through the normalization pipeline.
        
        Args:
            raw_data: Raw game data from provider
            source: Provider source name
            
        Returns:
            Normalized Game object or None if validation fails
        """
        try:
            # Add source and received timestamp
            raw_data["source"] = source
            raw_data["received_at"] = datetime.now(timezone.utc)
            
            # Schema validation
            validated_data = validate_game(raw_data)
            
            # Create normalized Game object
            game = Game(**validated_data)
            
            self._stats["total_processed"] += 1
            logger.debug(f"Successfully processed game: {game.id}")
            return game
            
        except Exception as e:
            self._stats["validation_errors"] += 1
            logger.error(f"Game normalization failed: {str(e)}")
            return None
    
    async def process_tournament(self, raw_data: Dict[str, Any], source: str) -> Optional[Tournament]:
        """
        Process tournament data through the normalization pipeline.
        
        Args:
            raw_data: Raw tournament data from provider
            source: Provider source name
            
        Returns:
            Normalized Tournament object or None if validation fails
        """
        try:
            # Add source and received timestamp
            raw_data["source"] = source
            raw_data["received_at"] = datetime.now(timezone.utc)
            
            # Schema validation
            validated_data = validate_tournament(raw_data)
            
            # Create normalized Tournament object
            tournament = Tournament(**validated_data)
            
            self._stats["total_processed"] += 1
            logger.debug(f"Successfully processed tournament: {tournament.id}")
            return tournament
            
        except Exception as e:
            self._stats["validation_errors"] += 1
            logger.error(f"Tournament normalization failed: {str(e)}")
            return None
    
    async def process_match(self, raw_data: Dict[str, Any], source: str) -> Optional[Match]:
        """
        Process match data through the normalization pipeline.
        
        Args:
            raw_data: Raw match data from provider
            source: Provider source name
            
        Returns:
            Normalized Match object or None if validation fails
        """
        try:
            # Add source and received timestamp
            raw_data["source"] = source
            raw_data["received_at"] = datetime.now(timezone.utc)
            
            # Schema validation
            validated_data = validate_match(raw_data)
            
            # Create normalized Match object
            match = Match(**validated_data)
            
            self._stats["total_processed"] += 1
            logger.debug(f"Successfully processed match: {match.id}")
            return match
            
        except Exception as e:
            self._stats["validation_errors"] += 1
            logger.error(f"Match normalization failed: {str(e)}")
            return None
    
    async def process_team(self, raw_data: Dict[str, Any], source: str) -> Optional[Team]:
        """
        Process team data through the normalization pipeline.
        
        Args:
            raw_data: Raw team data from provider
            source: Provider source name
            
        Returns:
            Normalized Team object or None if validation fails
        """
        try:
            # Add source and received timestamp
            raw_data["source"] = source
            raw_data["received_at"] = datetime.now(timezone.utc)
            
            # Schema validation
            validated_data = validate_team(raw_data)
            
            # Create normalized Team object
            team = Team(**validated_data)
            
            self._stats["total_processed"] += 1
            logger.debug(f"Successfully processed team: {team.id}")
            return team
            
        except Exception as e:
            self._stats["validation_errors"] += 1
            logger.error(f"Team normalization failed: {str(e)}")
            return None
    
    async def process_player(self, raw_data: Dict[str, Any], source: str) -> Optional[Player]:
        """
        Process player data through the normalization pipeline.
        
        Args:
            raw_data: Raw player data from provider
            source: Provider source name
            
        Returns:
            Normalized Player object or None if validation fails
        """
        try:
            # Add source and received timestamp
            raw_data["source"] = source
            raw_data["received_at"] = datetime.now(timezone.utc)
            
            # Schema validation
            validated_data = validate_player(raw_data)
            
            # Create normalized Player object
            player = Player(**validated_data)
            
            self._stats["total_processed"] += 1
            logger.debug(f"Successfully processed player: {player.id}")
            return player
            
        except Exception as e:
            self._stats["validation_errors"] += 1
            logger.error(f"Player normalization failed: {str(e)}")
            return None
    
    async def process_event(self, raw_data: Dict[str, Any], source: str) -> Optional[GameEvent]:
        """
        Process game event data through the normalization pipeline.
        
        This includes:
        - Schema validation
        - Deduplication
        - Event ordering
        
        Args:
            raw_data: Raw event data from provider
            source: Provider source name
            
        Returns:
            Normalized GameEvent object or None if validation fails or duplicate
        """
        try:
            # Add source and received timestamp
            raw_data["source"] = source
            raw_data["received_at"] = datetime.now(timezone.utc)
            
            # Schema validation
            validated_data = validate_event(raw_data)
            
            # Create normalized GameEvent object
            event = GameEvent(**validated_data)
            
            # Deduplication check
            if self.deduplication_service:
                is_duplicate = await self.deduplication_service.is_duplicate(event)
                if is_duplicate:
                    self._stats["deduplication_skipped"] += 1
                    logger.debug(f"Duplicate event skipped: {event.id}")
                    return None
                
                # Register event for deduplication
                await self.deduplication_service.register_event(event)
            
            # Event ordering
            if self.ordering_service:
                is_ordered, corrected_event = await self.ordering_service.order_event(event)
                if not is_ordered:
                    self._stats["ordering_corrected"] += 1
                    logger.debug(f"Event ordering corrected: {event.id}")
                    event = corrected_event if corrected_event else event
            
            self._stats["total_processed"] += 1
            logger.debug(f"Successfully processed event: {event.id}")
            return event
            
        except Exception as e:
            self._stats["validation_errors"] += 1
            logger.error(f"Event normalization failed: {str(e)}")
            return None
    
    async def process_batch(self, items: List[Dict[str, Any]], item_type: str, source: str, 
                           processor: Callable) -> List[Any]:
        """
        Process a batch of items through the normalization pipeline.
        
        Args:
            items: List of raw data items
            item_type: Type of items being processed
            source: Provider source name
            processor: Processing function to use
            
        Returns:
            List of successfully processed items
        """
        processed_items = []
        
        for item in items:
            try:
                processed = await processor(item, source)
                if processed:
                    processed_items.append(processed)
            except Exception as e:
                logger.error(f"Failed to process {item_type}: {str(e)}")
                continue
        
        logger.info(f"Processed {len(processed_items)}/{len(items)} {item_type} items")
        return processed_items
    
    def get_stats(self) -> Dict[str, int]:
        """Get pipeline statistics."""
        return self._stats.copy()
    
    def reset_stats(self):
        """Reset pipeline statistics."""
        self._stats = {
            "total_processed": 0,
            "validation_errors": 0,
            "deduplication_skipped": 0,
            "ordering_corrected": 0,
        }
