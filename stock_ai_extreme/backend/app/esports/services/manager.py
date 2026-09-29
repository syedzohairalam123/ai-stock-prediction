"""
Esports data manager for Phase 21A

This module provides the main data manager that coordinates all esports data operations.
It implements the 10,000-user architecture with event bus pattern.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import asyncio
import logging
import time
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.db import session_scope
from app.providers.cache import TTLCache

from app.esports.providers.base import (
    EsportsDataProvider,
    EsportsDataStatus,
    EsportsProviderError,
    Game,
    Tournament,
    Match,
    Team,
    Player,
    GameEvent,
    LiveSnapshot,
    ProviderHealth,
)
from app.esports.normalization.pipeline import NormalizationPipeline
from app.esports.state.event_engine import MatchStateEngine
from app.esports.services.event_deduplication import EventDeduplicationService
from app.esports.services.event_ordering import EventOrderingService
from app.esports.websocket.manager import esports_ws_manager
from app.esports.database.models import (
    EsportsGame,
    EsportsTournament,
    EsportsMatch,
    EsportsTeam,
    EsportsPlayer,
    EsportsGameEvent,
    EsportsMatchSnapshot,
    EsportsDataSource,
    EsportsProviderHealth,
)

logger = logging.getLogger("neural_market.esports.services.manager")


class EsportsDataManager:
    """
    Main data manager for esports data.
    
    This manager coordinates:
    - Provider adapters
    - Normalization pipeline
    - Event deduplication and ordering
    - State reconstruction
    - Database persistence
    - Redis caching
    - WebSocket streaming
    - Provider health monitoring
    
    Architecture for 10,000 concurrent users:
    External Provider → Small number of provider connections → Ingestion Service → 
    Event Bus / Redis → WebSocket Gateway Cluster → 10,000 clients
    """
    
    def __init__(self, providers: List[EsportsDataProvider]):
        """
        Initialize the esports data manager.
        
        Args:
            providers: List of provider adapters
        """
        self.providers = providers
        self.provider_map = {p.get_provider_name(): p for p in providers}
        
        # Initialize services
        self.deduplication_service = EventDeduplicationService()
        self.ordering_service = EventOrderingService()
        self.normalization_pipeline = NormalizationPipeline(
            deduplication_service=self.deduplication_service,
            ordering_service=self.ordering_service
        )
        
        # State engines for live matches
        self.state_engines: Dict[str, MatchStateEngine] = {}
        
        # Cache for live match state (Redis in production, TTLCache for now)
        self.live_match_cache = TTLCache(default_ttl_seconds=60)
        
        # Background tasks
        self._background_tasks: List[asyncio.Task] = []
        self._running = False
        
        # Statistics
        self._stats = {
            "total_events_processed": 0,
            "total_matches_tracked": 0,
            "active_subscriptions": 0,
            "provider_errors": 0,
        }
    
    async def start(self):
        """Start the data manager and background tasks."""
        if self._running:
            return
        
        self._running = True
        logger.info("Starting EsportsDataManager")
        
        # Start background tasks
        self._background_tasks = [
            asyncio.create_task(self._provider_health_monitor()),
            asyncio.create_task(self._cleanup_loop()),
            asyncio.create_task(self._event_ingestion_loop()),
        ]
    
    async def stop(self):
        """Stop the data manager and cleanup."""
        if not self._running:
            return
        
        self._running = False
        logger.info("Stopping EsportsDataManager")
        
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        # Close providers
        for provider in self.providers:
            if hasattr(provider, 'close'):
                await provider.close()
    
    async def get_games(self) -> List[Game]:
        """Get all supported games from all providers."""
        all_games = []
        for provider in self.providers:
            try:
                games = await provider.get_games()
                all_games.extend(games)
            except Exception as e:
                logger.error(f"Failed to get games from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
        
        return all_games
    
    async def get_tournaments(self, game_id: str) -> List[Tournament]:
        """Get tournaments for a specific game."""
        all_tournaments = []
        for provider in self.providers:
            try:
                tournaments = await provider.get_tournaments(game_id)
                all_tournaments.extend(tournaments)
            except Exception as e:
                logger.error(f"Failed to get tournaments from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
        
        return all_tournaments
    
    async def get_matches(self, game_id: str, tournament_id: Optional[str] = None) -> List[Match]:
        """Get matches for a game, optionally filtered by tournament."""
        all_matches = []
        for provider in self.providers:
            try:
                matches = await provider.get_matches(game_id, tournament_id)
                all_matches.extend(matches)
            except Exception as e:
                logger.error(f"Failed to get matches from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
        
        return all_matches
    
    async def get_match(self, match_id: str) -> Optional[Match]:
        """Get a specific match by ID."""
        for provider in self.providers:
            try:
                match = await provider.get_match(match_id)
                if match:
                    return match
            except Exception as e:
                logger.error(f"Failed to get match from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
        
        return None
    
    async def get_teams(self, game_id: str) -> List[Team]:
        """Get teams for a specific game."""
        all_teams = []
        for provider in self.providers:
            try:
                teams = await provider.get_teams(game_id)
                all_teams.extend(teams)
            except Exception as e:
                logger.error(f"Failed to get teams from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
        
        return all_teams
    
    async def get_players(self, team_id: str) -> List[Player]:
        """Get players for a specific team."""
        all_players = []
        for provider in self.providers:
            try:
                players = await provider.get_players(team_id)
                all_players.extend(players)
            except Exception as e:
                logger.error(f"Failed to get players from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
        
        return all_players
    
    async def get_live_snapshot(self, match_id: str) -> Optional[LiveSnapshot]:
        """
        Get current live snapshot for a match.
        
        Args:
            match_id: Match identifier
            
        Returns:
            LiveSnapshot or None if match not found
        """
        # Phase 21C §19: the cache is an optimisation, never the source of
        # truth. If the cache backend is down we fall through to the live state
        # engine (or the database) instead of failing the caller, and the
        # snapshot still carries its own data_status/data_age for the UI.
        try:
            cached = await self.live_match_cache.get(f"snapshot:{match_id}")
        except Exception as cache_error:
            logger.warning(f"Live snapshot cache unavailable for {match_id}: {cache_error}")
            cached = None
        if cached:
            return cached
        
        # Check if we have a state engine for this match
        if match_id in self.state_engines:
            snapshot = self.state_engines[match_id].get_current_snapshot()
            try:
                await self.live_match_cache.set(f"snapshot:{match_id}", snapshot, ttl_seconds=30)
            except Exception as cache_error:
                logger.warning(f"Could not cache snapshot for {match_id}: {cache_error}")
            return snapshot
        
        # Try to load from database. A database outage must not turn "no live
        # state available" into an unhandled error — it returns None so the UI
        # can show UNAVAILABLE rather than a fabricated snapshot (§25).
        try:
            return self._load_snapshot_from_db(match_id)
        except Exception as db_error:
            logger.error(f"Snapshot lookup failed for {match_id}: {db_error}")
            try:
                from app.esports.analytics.observability import esports_metrics

                esports_metrics.record_error()
            except Exception:
                pass
            return None

    def _load_snapshot_from_db(self, match_id: str) -> Optional[LiveSnapshot]:
        """Read the newest persisted snapshot for a match, if the DB has one."""
        with session_scope() as db:
            snapshot = db.query(EsportsMatchSnapshot).filter(
                EsportsMatchSnapshot.match_id == match_id
            ).order_by(desc(EsportsMatchSnapshot.timestamp)).first()
            
            if snapshot:
                return LiveSnapshot(
                    match_id=snapshot.match_id,
                    game_id=snapshot.game_id,
                    status=snapshot.status,
                    current_map=snapshot.current_map,
                    map_number=snapshot.map_number,
                    score_a=snapshot.score_a,
                    score_b=snapshot.score_b,
                    team_a_id=snapshot.team_a_id,
                    team_b_id=snapshot.team_b_id,
                    current_map_scores=snapshot.current_map_scores,
                    game_state=snapshot.game_state,
                    timestamp=snapshot.timestamp,
                    data_age_seconds=snapshot.data_age_seconds,
                    data_status=EsportsDataStatus(snapshot.data_status)
                )
        
        return None
    
    async def subscribe_to_match(self, match_id: str, client_id: str):
        """
        Subscribe a client to match updates.
        
        Args:
            match_id: Match identifier
            client_id: Client identifier
        """
        channel = f"esports:match:{match_id}"
        await esports_ws_manager.subscribe_to_channel(client_id, channel)
        self._stats["active_subscriptions"] += 1
        
        # Send current snapshot
        snapshot = await self.get_live_snapshot(match_id)
        if snapshot:
            await esports_ws_manager.send_snapshot_and_events(
                client_id, channel, snapshot.to_dict(), []
            )
    
    async def unsubscribe_from_match(self, match_id: str, client_id: str):
        """
        Unsubscribe a client from match updates.
        
        Args:
            match_id: Match identifier
            client_id: Client identifier
        """
        channel = f"esports:match:{match_id}"
        await esports_ws_manager.unsubscribe_from_channel(client_id, channel)
        self._stats["active_subscriptions"] -= 1

    async def subscribe_to_game(self, game_id: str, client_id: str):
        """Phase 21B: subscribe a client to every event for one game."""
        await esports_ws_manager.subscribe_to_channel(client_id, f"esports:game:{game_id}")

    async def subscribe_to_all(self, client_id: str):
        """Phase 21B: subscribe a client to the cross-game event firehose."""
        await esports_ws_manager.subscribe_to_channel(client_id, "esports:all")

    def _event_channels(self, event: GameEvent) -> List[str]:
        """The channels one normalized event is published to, in fan-out order."""
        channels = [f"esports:match:{event.match_id}"]
        if event.game_id:
            channels.append(f"esports:game:{event.game_id}")
        channels.append("esports:all")
        return channels

    async def get_match_events(self, match_id: str) -> List[GameEvent]:
        """
        Phase 21B: events for one match, merged across providers.

        De-duplicated by event id and sorted by sequence then timestamp so a
        single provider returning the same series twice cannot duplicate the
        timeline.
        """
        collected: Dict[str, GameEvent] = {}
        for provider in self.providers:
            try:
                events = await provider.get_match_events(match_id)
            except Exception as e:
                logger.error(f"Failed to get match events from {provider.get_provider_name()}: {e}")
                self._stats["provider_errors"] += 1
                continue
            for event in events:
                collected.setdefault(event.id, event)
        return sorted(collected.values(), key=lambda e: (e.sequence, e.timestamp))

    async def get_team(self, team_id: str) -> Optional[Team]:
        """Phase 21B: resolve a team across providers that support it."""
        for provider in self.providers:
            resolver = getattr(provider, "get_team", None)
            if resolver is None:
                continue
            try:
                team = await resolver(team_id)
            except Exception as e:
                logger.debug(f"get_team failed on {provider.get_provider_name()}: {e}")
                continue
            if team:
                return team
        return None

    async def provider_health_report(self) -> List[Dict[str, Any]]:
        """Phase 21B: per-source status for the data-source panel (§15)."""
        report: List[Dict[str, Any]] = []
        for provider in self.providers:
            try:
                health = await provider.get_provider_health()
                metrics = await provider.get_provider_metrics()
            except Exception as e:
                report.append({"name": provider.get_provider_name(), "status": "DOWN", "error": str(e)})
                continue
            report.append(
                {
                    "name": provider.get_provider_name(),
                    "status": health.value if hasattr(health, "value") else str(health),
                    "last_success": metrics.get("last_success"),
                    "request_count": metrics.get("request_count", 0),
                    "error_count": metrics.get("error_count", 0),
                    "avg_latency_ms": metrics.get("avg_latency_ms", 0),
                    "data_mode": metrics.get("data_mode"),
                    "refresh": metrics.get("refresh"),
                }
            )
        return report
    
    async def process_live_event(self, event: GameEvent):
        """
        Process a live game event through the complete pipeline.
        
        Args:
            event: Raw game event from provider
        """
        _event_started = time.perf_counter()
        try:
            # Normalize event
            normalized_event = await self.normalization_pipeline.process_event(
                event.to_dict(), event.source
            )
            
            if not normalized_event:
                return  # Event was duplicate or invalid
            
            self._stats["total_events_processed"] += 1

            # Phase 21C: record the measured signal for the analytics/trending
            # engine. This is a lock-only, in-memory counter update — it never
            # awaits a network/db call, so it cannot slow live delivery.
            try:
                from app.esports.analytics.observability import esports_metrics
                from app.esports.analytics.service import analytics_service

                event_type = normalized_event.type.value if hasattr(normalized_event.type, "value") else str(normalized_event.type)
                analytics_service.mark_event(normalized_event.match_id, normalized_event.game_id, event_type)
                esports_metrics.record_event_processing((time.perf_counter() - _event_started) * 1000)
            except Exception as _analytics_exc:  # analytics is never on the critical path
                logger.debug(f"analytics signal skipped: {_analytics_exc}")
            
            # Get or create state engine for this match
            if event.match_id not in self.state_engines:
                match = await self.get_match(event.match_id)
                if match:
                    self.state_engines[event.match_id] = MatchStateEngine(match)
                    self._stats["total_matches_tracked"] += 1
            
            # Phase 21B: the event is broadcast to every relevant channel as
            # soon as it is normalized, whether or not a state engine exists
            # yet. That is what lets the hub's activity ticker (subscribed to
            # ``esports:all``) see an event for a match it has not opened.
            event_channels = self._event_channels(normalized_event)
            payload = {
                "type": "event",
                "channel": event_channels[0],
                "data": normalized_event.to_dict(),
                "timestamp": datetime.utcnow().isoformat(),
            }
            _broadcast_started = time.perf_counter()
            for channel in event_channels:
                await esports_ws_manager.broadcast_to_channel(channel, {**payload, "channel": channel})
            try:
                from app.esports.analytics.observability import esports_metrics

                esports_metrics.record_ws_broadcast((time.perf_counter() - _broadcast_started) * 1000)
            except Exception:
                pass

            # Process event through state engine when one exists for this match.
            if event.match_id in self.state_engines:
                self.state_engines[event.match_id].process_event(normalized_event)

                # Get updated snapshot
                snapshot = self.state_engines[event.match_id].get_current_snapshot()

                # Update cache
                await self.live_match_cache.set(
                    f"snapshot:{event.match_id}", snapshot, ttl_seconds=30
                )

                # Broadcast updated snapshot to the same channels.
                for channel in event_channels:
                    await esports_ws_manager.broadcast_to_channel(channel, {
                        "type": "snapshot",
                        "channel": channel,
                        "data": snapshot.to_dict(),
                        "timestamp": datetime.utcnow().isoformat()
                    })
            
            # Persist to database
            await self._persist_event(normalized_event)
            
        except Exception as e:
            logger.error(f"Failed to process live event: {e}")
            self._stats["provider_errors"] += 1
    
    async def _persist_event(self, event: GameEvent):
        """Persist event to database."""
        _db_started = time.perf_counter()
        try:
            with session_scope() as db:
                db_event = EsportsGameEvent(
                    id=event.id,
                    match_id=event.match_id,
                    game_id=event.game_id,
                    type=event.type.value,
                    timestamp=event.timestamp,
                    sequence=event.sequence,
                    team_id=event.team_id,
                    player_id=event.player_id,
                    payload=event.payload,
                    source=event.source,
                    source_timestamp=event.source_timestamp,
                    received_at=event.received_at
                )
                db.merge(db_event)
            try:
                from app.esports.analytics.observability import esports_metrics

                esports_metrics.record_db_write((time.perf_counter() - _db_started) * 1000)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to persist event: {e}")
            try:
                from app.esports.analytics.observability import esports_metrics

                esports_metrics.record_error()
            except Exception:
                pass
    
    async def _provider_health_monitor(self):
        """Background task to monitor provider health."""
        while self._running:
            try:
                for provider in self.providers:
                    try:
                        health = await provider.get_provider_health()
                        metrics = await provider.get_provider_metrics()
                        
                        # Update health in database
                        with session_scope() as db:
                            db_health = EsportsProviderHealth(
                                id=f"{provider.get_provider_name()}_health",
                                provider=provider.get_provider_name(),
                                game_id="all",  # Multi-game provider
                                status=health.value,
                                request_count=metrics.get("request_count", 0),
                                error_count=metrics.get("error_count", 0),
                                last_success=datetime.fromisoformat(metrics["last_success"]) if metrics.get("last_success") else None,
                                last_error=datetime.utcnow() if metrics.get("last_error") else None,
                                last_error_message=metrics.get("last_error"),
                                avg_latency_ms=metrics.get("avg_latency_ms", 0),
                                event_rate=0,  # Calculated from event rate
                                connection_status="connected" if health == ProviderHealth.AVAILABLE else "disconnected"
                            )
                            db.merge(db_health)
                    
                    except Exception as e:
                        logger.error(f"Failed to monitor provider {provider.get_provider_name()}: {e}")
                
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Provider health monitor error: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_loop(self):
        """Background task to cleanup old data."""
        while self._running:
            try:
                # Cleanup deduplication service
                await self.deduplication_service.cleanup_expired()
                
                # Cleanup ordering service
                await self.ordering_service.cleanup_old_buffers()
                
                # Cleanup stale WebSocket connections
                await esports_ws_manager.cleanup_stale_connections()
                
                await asyncio.sleep(300)  # Run every 5 minutes
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(300)
    
    async def _event_ingestion_loop(self):
        """Background task to ingest events from providers."""
        while self._running:
            try:
                for provider in self.providers:
                    try:
                        # Get live events from provider
                        for game in await provider.get_games():
                            events = await provider.get_live_events(game.id)
                            for event in events:
                                await self.process_live_event(event)
                    
                    except Exception as e:
                        logger.error(f"Failed to ingest events from {provider.get_provider_name()}: {e}")
                
                await asyncio.sleep(20)  # Phase 21B: 20s poll keeps free-tier sources within quota
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Event ingestion loop error: {e}")
                await asyncio.sleep(20)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            **self._stats,
            "deduplication_stats": self.deduplication_service.get_stats(),
            "ordering_stats": self.ordering_service.get_stats(),
            "pipeline_stats": self.normalization_pipeline.get_stats(),
            "websocket_stats": esports_ws_manager.get_connection_stats(),
        }
