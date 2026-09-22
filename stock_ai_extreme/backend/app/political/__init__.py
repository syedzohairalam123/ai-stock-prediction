"""
Phase 18 — Political & Geopolitical Data Mapping / Forecast Visualization.

A neutral, source-driven module: every political number shown anywhere in the
application is quoted from an external source (FEC election calendar, public
prediction markets, the MIT Election Data and Science Lab historical dataset,
GDELT coverage) with its measurement type, source, measurement date and
retrieval date. The module computes no probabilities of its own.
"""
from __future__ import annotations

from .engine import PoliticalEngine, engine
from .routes import router as political_router
from .schemas import (
    ForecastMeasurementSchema,
    MeasurementType,
    PoliticalEventSchema,
    PoliticalRegionSchema,
    RegionDataState,
    TimelineEventSchema,
)

__all__ = [
    "PoliticalEngine",
    "engine",
    "political_router",
    "ForecastMeasurementSchema",
    "MeasurementType",
    "PoliticalEventSchema",
    "PoliticalRegionSchema",
    "RegionDataState",
    "TimelineEventSchema",
]
