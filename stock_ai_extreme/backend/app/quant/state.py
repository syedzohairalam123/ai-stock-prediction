"""
Phase 21 — one shared provider manager for the quant package.

Same pattern as `paper.state` / `discovery.configure` / `political.configure`:
`main.py` builds the single `MarketDataManager` (Phase 2) and hands it to this
module once. The analytics layer therefore reads the same cached, fallback-
chained bars every other page reads — one upstream stack, one cache, one quota.
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
