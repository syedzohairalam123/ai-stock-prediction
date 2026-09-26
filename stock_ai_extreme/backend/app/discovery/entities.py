"""
Unified normalized entity model for discovery (spec §10, §11).

``DiscoverableEntity`` is the single shape every collector produces, no matter
whether the underlying data came from a quote provider, a prediction market,
or the news corpus. Scores are *not* stored here — a collector only reports
what it measured (``signals``), and :mod:`app.discovery.trend_engine` turns
those measurements into scores. That separation is what makes
``calculateTrendScore()`` explainable.

Honesty rules encoded by the type system:

    * ``created_at`` / ``updated_at`` are ISO strings or ``None`` — a missing
      timestamp is missing, never "now".
    * ``activity`` is ``None`` when no source measures activity for that
      entity; the UI renders N/A instead of a fabricated count.
    * ``data_mode`` is one of LIVE / DELAYED / DEMO / UNAVAILABLE so a caller
      can never present simulated data as live (nothing in Phase 19 emits
      DEMO — the field exists because the contract requires it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Entity types the discovery engine understands (spec §10).
ENTITY_TYPES: tuple[str, ...] = (
    "stock",
    "index",
    "crypto",
    "commodity",
    "forex",
    "news_topic",
    "forecast_event",
)

#: Feed modes (spec §1, §9).
FEED_MODES: tuple[str, ...] = ("trending", "new", "popular", "recent")

DATA_MODES: tuple[str, ...] = ("LIVE", "DELAYED", "DEMO", "UNAVAILABLE")


@dataclass
class ActivityMetric:
    """One real, measurable activity number for an entity.

    ``value`` may be ``None`` (the source couldn't answer) — callers must
    render that as N/A rather than zero. ``unit`` and ``label`` exist so the
    UI never guesses what a bare number means.
    """

    label: str
    value: Optional[float]
    unit: Optional[str] = None
    as_of: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "as_of": self.as_of,
            "note": self.note,
        }


@dataclass
class DiscoverableEntity:
    """A normalized discoverable thing (spec §11)."""

    id: str
    type: str
    name: str
    category: str
    tags: List[str] = field(default_factory=list)
    symbol: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    activity: Optional[ActivityMetric] = None
    source: str = "unknown"
    data_mode: str = "UNAVAILABLE"
    #: Lifecycle status where one exists (forecast events: OPEN/CLOSED/
    #: RESOLVED; everything else ACTIVE).
    status: str = "ACTIVE"
    #: Where the frontend should send a user who clicks the card. ``None`` =
    #: there is no honest detail page for this entity yet.
    route: Optional[str] = None
    #: Raw *measured* inputs for the trend engine. Only keys with a real
    #: measurement are present; an absent key means "not available" (which the
    #: engine reports as a missing signal, never as 0).
    signals: Dict[str, Any] = field(default_factory=dict)
    #: Per-source provenance for this entity (e.g. quote freshness).
    provenance: Dict[str, Any] = field(default_factory=dict)

    # -- serialization ----------------------------------------------------
    def base_dict(self) -> Dict[str, Any]:
        """The spec §11 fields + provenance, without any scores attached."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "symbol": self.symbol,
            "category": self.category,
            "tags": list(self.tags),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "activity": self.activity.to_dict() if self.activity else None,
            "source": self.source,
            "dataMode": self.data_mode,
            "status": self.status,
            "route": self.route,
            "provenance": self.provenance or None,
        }


__all__ = [
    "ENTITY_TYPES",
    "FEED_MODES",
    "DATA_MODES",
    "ActivityMetric",
    "DiscoverableEntity",
]
