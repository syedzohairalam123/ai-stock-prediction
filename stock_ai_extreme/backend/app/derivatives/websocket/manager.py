"""
WebSocket manager for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides WebSocket infrastructure for real-time derivatives data streaming.
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("neural_market.derivatives.websocket.manager")


class DerivativesWebSocketManager:
    """
    Manager for WebSocket connections for real-time derivatives data.
    
    Features:
    - Connection management
    - Subscription management
    - Broadcast to subscribers
    - Reconnection strategy
    - Backoff handling
    """
    
    def __init__(self):
        """Initialize WebSocket manager."""
        # Active connections by user/client
        self.active_connections: Dict[str, WebSocket] = {}
        
        # Subscriptions by instrument
        self.instrument_subscribers: Dict[str, Set[str]] = {}
        
        # Connection metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Reconnection tracking
        self.reconnection_attempts: Dict[str, int] = {}
        self.max_reconnection_attempts = 5
        self.reconnection_backoff_base = 2  # seconds
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """
        Accept a new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
            client_id: Unique client identifier
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.connection_metadata[client_id] = {
            "connected_at": datetime.utcnow(),
            "subscriptions": set(),
            "last_heartbeat": datetime.utcnow()
        }
        self.reconnection_attempts[client_id] = 0
        
        logger.info(f"WebSocket client connected: {client_id}")
        
        # Send welcome message
        await self.send_personal_message(client_id, {
            "type": "connected",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Connected to derivatives data stream"
        })
    
    async def disconnect(self, client_id: str):
        """
        Handle client disconnection.
        
        Args:
            client_id: Client identifier
        """
        if client_id in self.active_connections:
            # Remove from all instrument subscriptions
            subscriptions = self.connection_metadata[client_id]["subscriptions"]
            for instrument_id in subscriptions:
                if instrument_id in self.instrument_subscribers:
                    self.instrument_subscribers[instrument_id].discard(client_id)
                    if not self.instrument_subscribers[instrument_id]:
                        del self.instrument_subscribers[instrument_id]
            
            # Remove connection
            del self.active_connections[client_id]
            del self.connection_metadata[client_id]
            del self.reconnection_attempts[client_id]
            
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
    
    async def broadcast_to_instrument(self, instrument_id: str, message: Dict[str, Any]):
        """
        Broadcast a message to all subscribers of an instrument.
        
        Args:
            instrument_id: Instrument identifier
            message: Message to broadcast
        """
        if instrument_id in self.instrument_subscribers:
            subscribers = self.instrument_subscribers[instrument_id].copy()
            for client_id in subscribers:
                await self.send_personal_message(client_id, message)
    
    async def subscribe_to_instrument(self, client_id: str, instrument_id: str):
        """
        Subscribe a client to an instrument's data stream.
        
        Args:
            client_id: Client identifier
            instrument_id: Instrument identifier
        """
        # Add to instrument subscribers
        if instrument_id not in self.instrument_subscribers:
            self.instrument_subscribers[instrument_id] = set()
        self.instrument_subscribers[instrument_id].add(client_id)
        
        # Add to client subscriptions
        if client_id in self.connection_metadata:
            self.connection_metadata[client_id]["subscriptions"].add(instrument_id)
        
        logger.info(f"Client {client_id} subscribed to {instrument_id}")
        
        # Send confirmation
        await self.send_personal_message(client_id, {
            "type": "subscription_confirmed",
            "instrument_id": instrument_id,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def unsubscribe_from_instrument(self, client_id: str, instrument_id: str):
        """
        Unsubscribe a client from an instrument's data stream.
        
        Args:
            client_id: Client identifier
            instrument_id: Instrument identifier
        """
        # Remove from instrument subscribers
        if instrument_id in self.instrument_subscribers:
            self.instrument_subscribers[instrument_id].discard(client_id)
            if not self.instrument_subscribers[instrument_id]:
                del self.instrument_subscribers[instrument_id]
        
        # Remove from client subscriptions
        if client_id in self.connection_metadata:
            self.connection_metadata[client_id]["subscriptions"].discard(instrument_id)
        
        logger.info(f"Client {client_id} unsubscribed from {instrument_id}")
        
        # Send confirmation
        await self.send_personal_message(client_id, {
            "type": "unsubscription_confirmed",
            "instrument_id": instrument_id,
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
                len(subs) for subs in self.instrument_subscribers.values()
            ),
            "instruments_with_subscribers": len(self.instrument_subscribers),
            "connection_details": {
                client_id: {
                    "connected_at": metadata["connected_at"].isoformat(),
                    "subscriptions": list(metadata["subscriptions"]),
                    "last_heartbeat": metadata["last_heartbeat"].isoformat()
                }
                for client_id, metadata in self.connection_metadata.items()
            }
        }
    
    def get_instrument_subscribers(self, instrument_id: str) -> Set[str]:
        """
        Get all subscribers for an instrument.
        
        Args:
            instrument_id: Instrument identifier
            
        Returns:
            Set of client IDs
        """
        return self.instrument_subscribers.get(instrument_id, set()).copy()
    
    def get_client_subscriptions(self, client_id: str) -> Set[str]:
        """
        Get all instrument subscriptions for a client.
        
        Args:
            client_id: Client identifier
            
        Returns:
            Set of instrument IDs
        """
        if client_id in self.connection_metadata:
            return self.connection_metadata[client_id]["subscriptions"].copy()
        return set()


# Global WebSocket manager instance
derivatives_ws_manager = DerivativesWebSocketManager()
