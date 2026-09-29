"""
WebSocket manager for Phase 21A - Real-Time Esports Data Ingestion

This module provides WebSocket infrastructure for real-time esports data streaming.
Following the existing WebSocket patterns in the project.
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("neural_market.esports.websocket.manager")


class EsportsWebSocketManager:
    """
    Manager for WebSocket connections for real-time esports data.
    
    Features:
    - Connection management
    - Channel-based subscriptions
    - Broadcast to subscribers
    - Reconnection strategy
    - Heartbeat/ping-pong
    - Backoff handling
    - Snapshot + event model for client connections
    """
    
    def __init__(self):
        """Initialize WebSocket manager."""
        # Active connections by client
        self.active_connections: Dict[str, WebSocket] = {}
        
        # Channel subscriptions (esports:match:{matchId}, esports:game:{gameId}, esports:tournament:{tournamentId})
        self.channel_subscribers: Dict[str, Set[str]] = {}
        
        # Connection metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Reconnection tracking
        self.reconnection_attempts: Dict[str, int] = {}
        self.max_reconnection_attempts = 5
        self.reconnection_backoff_base = 2  # seconds
        
        # Heartbeat settings
        self.heartbeat_interval = 30  # seconds
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """
        Accept a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            client_id: Unique client identifier
        """
        await websocket.accept()
        # Phase 21C §19: under a reconnect storm the same client id can arrive
        # again before the previous socket is torn down. Release the old
        # registration first so its channel subscriptions and heartbeat task are
        # not orphaned (which would leak a task per reconnect).
        if client_id in self.active_connections or client_id in self.heartbeat_tasks:
            await self._release(client_id)
        self.active_connections[client_id] = websocket
        self.connection_metadata[client_id] = {
            "connected_at": datetime.utcnow(),
            "subscriptions": set(),
            "last_heartbeat": datetime.utcnow(),
            "channels": set()
        }
        self.reconnection_attempts[client_id] = 0
        
        logger.info(f"WebSocket client connected: {client_id}")
        
        # Start heartbeat for this connection
        self.heartbeat_tasks[client_id] = asyncio.create_task(
            self._heartbeat_loop(client_id)
        )
        
        # Send welcome message
        await self.send_personal_message(client_id, {
            "type": "connected",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Connected to esports data stream"
        })
    
    async def _release(self, client_id: str) -> None:
        """
        Drop every trace of a client id without logging.

        Shared by :meth:`connect` (reconnect storm) and :meth:`disconnect`, and
        written to be safe to call when some of the registries are already gone.
        """
        task = self.heartbeat_tasks.pop(client_id, None)
        if task is not None:
            task.cancel()
        metadata = self.connection_metadata.pop(client_id, None)
        if metadata is not None:
            for channel in list(metadata.get("channels") or []):
                subscribers = self.channel_subscribers.get(channel)
                if subscribers is None:
                    continue
                subscribers.discard(client_id)
                if not subscribers:
                    del self.channel_subscribers[channel]
        self.active_connections.pop(client_id, None)
        self.reconnection_attempts.pop(client_id, None)

    async def disconnect(self, client_id: str):
        """
        Handle client disconnection.
        
        Args:
            client_id: Client identifier
        """
        had_connection = client_id in self.active_connections
        await self._release(client_id)
        if had_connection:
            logger.info(f"WebSocket client disconnected: {client_id}")
    
    async def send_personal_message(self, client_id: str, message: Dict[str, Any]):
        """
        Send a message to a specific client.
        
        Args:
            client_id: Client identifier
            message: Message to send
        """
        if client_id in self.active_connections:
            try:
                websocket = self.active_connections[client_id]
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")
                await self.disconnect(client_id)
    
    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        """
        Broadcast a message to all subscribers of a channel.
        
        Args:
            channel: Channel name (e.g., "esports:match:{matchId}")
            message: Message to broadcast
        """
        if channel in self.channel_subscribers:
            subscribers = self.channel_subscribers[channel].copy()
            for client_id in subscribers:
                await self.send_personal_message(client_id, message)
    
    async def subscribe_to_channel(self, client_id: str, channel: str):
        """
        Subscribe a client to a channel.
        
        Args:
            client_id: Client identifier
            channel: Channel name
        """
        # Add to channel subscribers
        if channel not in self.channel_subscribers:
            self.channel_subscribers[channel] = set()
        self.channel_subscribers[channel].add(client_id)
        
        # Add to client channels
        if client_id in self.connection_metadata:
            self.connection_metadata[client_id]["channels"].add(channel)
        
        logger.info(f"Client {client_id} subscribed to channel {channel}")
        
        # Send confirmation
        await self.send_personal_message(client_id, {
            "type": "subscription_confirmed",
            "channel": channel,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def unsubscribe_from_channel(self, client_id: str, channel: str):
        """
        Unsubscribe a client from a channel.
        
        Args:
            client_id: Client identifier
            channel: Channel name
        """
        # Remove from channel subscribers
        if channel in self.channel_subscribers:
            self.channel_subscribers[channel].discard(client_id)
            if not self.channel_subscribers[channel]:
                del self.channel_subscribers[channel]
        
        # Remove from client channels
        if client_id in self.connection_metadata:
            self.connection_metadata[client_id]["channels"].discard(channel)
        
        logger.info(f"Client {client_id} unsubscribed from channel {channel}")
        
        # Send confirmation
        await self.send_personal_message(client_id, {
            "type": "unsubscription_confirmed",
            "channel": channel,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def send_snapshot_and_events(self, client_id: str, channel: str, 
                                      snapshot: Dict[str, Any], events: list):
        """
        Send snapshot followed by incremental events to a client.
        
        This implements the snapshot + event model for client connections.
        
        Args:
            client_id: Client identifier
            channel: Channel name
            snapshot: Current match snapshot
            events: List of incremental events
        """
        # First send the snapshot
        await self.send_personal_message(client_id, {
            "type": "snapshot",
            "channel": channel,
            "data": snapshot,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Then send incremental events
        for event in events:
            await self.send_personal_message(client_id, {
                "type": "event",
                "channel": channel,
                "data": event,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    async def handle_reconnection(self, client_id: str) -> bool:
        """
        Handle client reconnection with exponential backoff.
        
        Args:
            client_id: Client identifier
            
        Returns:
            True if reconnection should be allowed, False otherwise
        """
        if client_id in self.reconnection_attempts:
            attempts = self.reconnection_attempts[client_id]
            
            if attempts >= self.max_reconnection_attempts:
                logger.warning(f"Client {client_id} exceeded max reconnection attempts")
                return False
            
            # Calculate backoff delay
            backoff_delay = self.reconnection_backoff_base ** attempts
            logger.info(f"Client {client_id} reconnection attempt {attempts + 1}, backoff: {backoff_delay}s")
            
            self.reconnection_attempts[client_id] = attempts + 1
            await asyncio.sleep(backoff_delay)
        else:
            self.reconnection_attempts[client_id] = 1
        
        return True
    
    async def _heartbeat_loop(self, client_id: str):
        """
        Send periodic heartbeats to keep connection alive.
        
        Args:
            client_id: Client identifier
        """
        try:
            while client_id in self.active_connections:
                await asyncio.sleep(self.heartbeat_interval)
                await self.send_heartbeat(client_id)
        except asyncio.CancelledError:
            # Task was cancelled, this is normal
            pass
        except Exception as e:
            logger.error(f"Heartbeat error for {client_id}: {e}")
            await self.disconnect(client_id)
    
    async def send_heartbeat(self, client_id: str):
        """
        Send heartbeat to client to keep connection alive.
        
        Args:
            client_id: Client identifier
        """
        await self.send_personal_message(client_id, {
            "type": "heartbeat",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        if client_id in self.connection_metadata:
            self.connection_metadata[client_id]["last_heartbeat"] = datetime.utcnow()
    
    async def handle_pong(self, client_id: str):
        """
        Handle pong response from client.
        
        Args:
            client_id: Client identifier
        """
        if client_id in self.connection_metadata:
            self.connection_metadata[client_id]["last_heartbeat"] = datetime.utcnow()
    
    async def cleanup_stale_connections(self, timeout_seconds: int = 300):
        """
        Clean up stale connections.
        
        Args:
            timeout_seconds: Timeout in seconds before considering connection stale
        """
        from datetime import timedelta
        
        stale_clients = []
        now = datetime.utcnow()
        
        for client_id, metadata in self.connection_metadata.items():
            last_heartbeat = metadata.get("last_heartbeat", now)
            if (now - last_heartbeat) > timedelta(seconds=timeout_seconds):
                stale_clients.append(client_id)
        
        for client_id in stale_clients:
            logger.info(f"Cleaning up stale connection: {client_id}")
            await self.disconnect(client_id)
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get connection statistics.
        
        Returns:
            Dictionary with connection stats
        """
        return {
            "active_connections": len(self.active_connections),
            "total_subscriptions": sum(
                len(subs) for subs in self.channel_subscribers.values()
            ),
            "channels_with_subscribers": len(self.channel_subscribers),
            "connection_details": {
                client_id: {
                    "connected_at": metadata["connected_at"].isoformat(),
                    "channels": list(metadata["channels"]),
                    "last_heartbeat": metadata["last_heartbeat"].isoformat()
                }
                for client_id, metadata in self.connection_metadata.items()
            }
        }
    
    def get_channel_subscribers(self, channel: str) -> Set[str]:
        """
        Get all subscribers for a channel.
        
        Args:
            channel: Channel name
            
        Returns:
            Set of client IDs
        """
        return self.channel_subscribers.get(channel, set()).copy()
    
    def get_client_channels(self, client_id: str) -> Set[str]:
        """
        Get all channel subscriptions for a client.
        
        Args:
            client_id: Client identifier
            
        Returns:
            Set of channel names
        """
        if client_id in self.connection_metadata:
            return self.connection_metadata[client_id]["channels"].copy()
        return set()


# Global WebSocket manager instance
esports_ws_manager = EsportsWebSocketManager()
