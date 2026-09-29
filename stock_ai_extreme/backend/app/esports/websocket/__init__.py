"""
WebSocket infrastructure for Phase 21A

This package provides WebSocket server infrastructure for real-time esports data streaming.
"""

from .manager import EsportsWebSocketManager

__all__ = [
    "EsportsWebSocketManager",
]
