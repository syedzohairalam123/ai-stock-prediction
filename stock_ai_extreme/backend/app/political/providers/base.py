"""
Provider adapter architecture for Phase 18 (spec §13).

Every political data source plugs in through ``PoliticalDataProvider``. The
engine never knows *how* a source works, only what it can provide and the
normalized shapes it returns. A new source = a new subclass registered in
``build_default_providers`` — nowhere else.

Contract every provider must honour:

* Return **only** what the source actually published. Normalizing is allowed;
  deriving, adjusting, averaging or imputing values is not.
* Never raise into the caller: wrap failures in a ``ProviderResult`` with
  ``status=UNAVAILABLE`` so one dead source cannot break the whole map.
* Always stamp ``retrieved_at`` and keep the source's own timestamps untouched.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, Sequence, TypeVar
from ..schemas import (
    ForecastMeasurementSchema,
    PoliticalEventSchema,
    SourceStatus,
    TimelineEventSchema,
)

T = TypeVar("T")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ProviderResult(Generic[T]):
    """What one provider call produced, including honest failure."""

    items: List[T] = field(default_factory=list)
    status: SourceStatus = SourceStatus.OK
    error: Optional[str] = None
    fetched_at: Optional[datetime] = None
    duration_ms: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.status != SourceStatus.UNAVAILABLE


@dataclass
class ProviderFetch:
    """Bookkeeping the engine uses to surface per-source health."""

    provider_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    ok: bool = False
    items: int = 0
    error: Optional[str] = None


async def _measure(coro_factory) -> ProviderResult[T]:
    """Run one provider call, measure it, and never let exceptions escape."""
    started = utcnow()
    t0 = time.perf_counter()
    try:
        result = await coro_factory()
        if result.fetched_at is None:
            result.fetched_at = started
        result.duration_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return result
    except Exception as exc:  # noqa: BLE001 — one bad source must not break the map
        return ProviderResult[T](
            status=SourceStatus.UNAVAILABLE,
            error=f"{type(exc).__name__}: {exc}",
            fetched_at=started,
            duration_ms=round((time.perf_counter() - t0) * 1000.0, 3),
        )


class PoliticalDataProvider(ABC):
    """One external political data source.

    Class attributes describe the source for the ``/sources`` endpoint; the
    capability flags decide which engine queries touch it.
    """

    provider_id: str = "abstract"
    name: str = "Abstract source"
    kind: str = "API"
    source_url: Optional[str] = None
    description: str = ""
    attribution: Optional[str] = None
    requires_key: bool = False
    capabilities: frozenset[str] = frozenset()

    #: capability names used by the engine
    CAP_EVENTS = "events"
    CAP_REGIONAL_MEASUREMENTS = "regional_measurements"
    CAP_HISTORICAL_MEASUREMENTS = "historical_measurements"
    CAP_TIMELINE = "timeline"
    CAP_SOURCES = "sources"

    def __init__(self) -> None:
        self.last_fetch_at: Optional[datetime] = None
        self.last_success_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.consecutive_errors: int = 0
        self.fetch_count: int = 0

    # -- capability queries -------------------------------------------------
    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    @property
    def status(self) -> SourceStatus:
        if self.consecutive_errors >= 3:
            return SourceStatus.DEGRADED
        return SourceStatus.OK

    def key_configured(self) -> bool:
        return True

    # -- record keeping -----------------------------------------------------
    def _record(self, result: ProviderResult) -> ProviderResult:
        self.fetch_count += 1
        self.last_fetch_at = result.fetched_at or utcnow()
        if result.ok:
            self.consecutive_errors = 0
            self.last_success_at = self.last_fetch_at
            self.last_error = None
        else:
            self.consecutive_errors += 1
            self.last_error = result.error
        return result

    # -- the four spec §13 capabilities -------------------------------------
    async def get_events(self) -> ProviderResult[PoliticalEventSchema]:
        return ProviderResult(status=SourceStatus.UNAVAILABLE, error="not implemented")

    async def get_regional_measurements(self) -> ProviderResult[ForecastMeasurementSchema]:
        return ProviderResult(status=SourceStatus.UNAVAILABLE, error="not implemented")

    async def get_historical_measurements(self) -> ProviderResult[ForecastMeasurementSchema]:
        return ProviderResult(status=SourceStatus.UNAVAILABLE, error="not implemented")

    async def get_timeline(self) -> ProviderResult[TimelineEventSchema]:
        return ProviderResult(status=SourceStatus.UNAVAILABLE, error="not implemented")

    async def get_sources(self) -> List[Dict[str, Any]]:
        """Sub-source descriptors (e.g. the publishers inside an events feed)."""
        return []

    # -- convenience ---------------------------------------------------------
    async def fetch(self, coro_factory) -> ProviderResult[T]:
        """Measure + record one capability call."""
        result = await _measure(coro_factory)
        return self._record(result)


def provider_reports(pairs: Sequence[tuple[str, ProviderResult]]) -> List[Dict[str, Any]]:
    """Compact per-provider reports for response metadata."""
    out: List[Dict[str, Any]] = []
    for provider_id, result in pairs:
        out.append({
            "provider_id": provider_id,
            "ok": result.ok,
            "status": result.status.value,
            "items": len(result.items),
            "duration_ms": result.duration_ms,
            "error": result.error,
        })
    return out
