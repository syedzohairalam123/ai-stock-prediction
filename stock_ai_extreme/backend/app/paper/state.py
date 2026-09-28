"""
Phase 20 — one shared provider manager for the paper package.

Exactly the pattern `breaking_news.configure()` and `discovery_service.configure()`
already use: `main.py` builds the single `MarketDataManager` (Phase 2) and hands
it to this module once, so the ticket reads the same cached, fallback-chained
data every other page reads. No second provider stack, no second cache, and
therefore no second WebSocket connection or duplicated upstream quota.
"""
from __future__ import annotations

from typing import Any, Optional

_manager: Optional[Any] = None


def configure(manager: Any) -> None:
    """Bind the application's market-data manager (idempotent)."""
    global _manager
    _manager = manager


def get_manager() -> Optional[Any]:
    """The bound provider manager, or None when the app has not configured one."""
    return _manager


def reset() -> None:
    """Test helper: drop the binding so a test can install a fake."""
    global _manager
    _manager = None
