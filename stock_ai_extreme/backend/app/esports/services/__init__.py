"""
Services for Phase 21A

This package contains core services for event deduplication, ordering, and data management.
"""

from .event_deduplication import EventDeduplicationService
from .event_ordering import EventOrderingService
from .manager import EsportsDataManager

__all__ = [
    "EventDeduplicationService",
    "EventOrderingService",
    "EsportsDataManager",
]
