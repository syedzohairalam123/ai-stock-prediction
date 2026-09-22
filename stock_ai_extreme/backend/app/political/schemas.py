"""
Pydantic schemas for Phase 18 — Political & Geopolitical Data Mapping /
Forecast Visualization.

Design rules enforced by these models:

* Every measurement carries its source, measurement date, retrieval date and
  measurement type. There is no field for "the app's own opinion" — it does
  not exist, so it cannot be rendered.
* ``probability`` is the *source's* number, unmodified. There is no averaging,
  no adjustment and no imputation anywhere in the type system.
* ``uncertainty`` is ``None`` unless the source itself published an interval,
  margin or range. It is never derived.
* Optional fields are optional because the source genuinely did not supply
  them — the UI renders "unavailable", never a placeholder.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

class MeasurementType(str, Enum):
    """The four measurement families that must never be merged into one number."""

    POLL = "POLL"
    FORECAST = "FORECAST"
    MODEL = "MODEL"
    HISTORICAL_RESULT = "HISTORICAL_RESULT"


class RegionDataState(str, Enum):
    """Map classifications. A region is never given political colour from
    the app's own inference — the state is derived only from what sources
    actually supplied."""

    AVAILABLE = "AVAILABLE"
    NO_DATA = "NO_DATA"
    OUTDATED = "OUTDATED"
    CONTESTED = "CONTESTED"
    RESOLVED = "RESOLVED"


class SourceStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class PoliticalCategory(str, Enum):
    """Event categories (spec §11). Rule-based classifications are labelled."""

    ELECTION = "ELECTION"
    REFERENDUM = "REFERENDUM"
    GOVERNMENT = "GOVERNMENT"
    INTERNATIONAL = "INTERNATIONAL"
    POLICY = "POLICY"
    CONFLICT = "CONFLICT"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# source / provenance
# ---------------------------------------------------------------------------

class SourceInfoSchema(BaseModel):
    """One external data source, with honest health and attribution."""

    id: str
    name: str
    kind: str = "API"
    source_url: Optional[str] = None
    description: str = ""
    attribution: Optional[str] = None
    status: SourceStatus = SourceStatus.OK
    capabilities: List[str] = Field(default_factory=list)
    last_fetch_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_errors: int = 0
    fetch_count: int = 0
    requires_key: bool = False
    key_configured: bool = True


class ProviderReportSchema(BaseModel):
    """Per-provider outcome of one refresh — never hidden, never merged."""

    provider_id: str
    ok: bool
    status: SourceStatus = SourceStatus.OK
    items: int = 0
    duration_ms: Optional[float] = None
    error: Optional[str] = None


class RetrievalMeta(BaseModel):
    """When this payload was assembled and from which providers."""

    generated_at: datetime
    providers: List[ProviderReportSchema] = Field(default_factory=list)
    cache: str = "MISS"


# ---------------------------------------------------------------------------
# political events (spec §2, §11)
# ---------------------------------------------------------------------------

class PoliticalEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    jurisdiction: Optional[str] = None
    jurisdiction_type: Optional[str] = None  # STATE | DISTRICT | COUNTRY | NATIONAL | UNKNOWN
    election_date: Optional[datetime] = None
    election_date_basis: Optional[str] = None  # how the date is known (source / statute)
    category: PoliticalCategory = PoliticalCategory.OTHER
    source: str
    source_id: str = ""
    source_url: Optional[str] = None
    updated_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None
    status: str = "SCHEDULED"  # SCHEDULED | OPEN | CLOSED | RESOLVED | UNKNOWN
    office: Optional[str] = None
    election_id: Optional[str] = None
    country: str = "US"
    region_ids: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# regions (spec §3)
# ---------------------------------------------------------------------------

class GeometryRefSchema(BaseModel):
    """Where the region's borders actually come from.

    The app never draws borders itself: the frontend renders Plotly's bundled
    authoritative topojson (Natural Earth / US Census derived), addressed by
    ``location_key`` (e.g. a USPS state code or ISO-3 country code).
    """

    format: str = "topojson"
    provider: str = "plotly.js built-in geo data (Natural Earth / US Census derived)"
    location_mode: str = "USA-states"  # USA-states | country names | ISO-3
    location_key: Optional[str] = None
    reference_url: Optional[str] = None


class PopulationContextSchema(BaseModel):
    """Population context, only from a real source (World Bank / Census)."""

    population: Optional[int] = None
    as_of: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    note: Optional[str] = None


class PoliticalRegionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    country: str = "US"
    country_name: str = "United States"
    state_code: Optional[str] = None  # USPS code for sub-national regions
    fips_code: Optional[str] = None
    geometry: GeometryRefSchema
    population_context: Optional[PopulationContextSchema] = None
    source: str
    source_url: Optional[str] = None
    region_type: str = "STATE"  # STATE | DISTRICT | COUNTRY


class RegionStatusSchema(BaseModel):
    """The per-region presentation state shown on the map (spec §7)."""

    region_id: str
    state: RegionDataState
    reason: Optional[str] = None
    election_id: Optional[str] = None
    measurement_count: int = 0
    source_ids: List[str] = Field(default_factory=list)
    last_measurement_at: Optional[datetime] = None
    last_measured_by: Optional[str] = None
    measurement_types: List[MeasurementType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# measurements (spec §4, §8, §9, §14)
# ---------------------------------------------------------------------------

class UncertaintySchema(BaseModel):
    """Only ever populated from a value the source itself published."""

    kind: str  # CI | MOE | RANGE | MODEL_UNCERTAINTY
    low: Optional[float] = None
    high: Optional[float] = None
    margin: Optional[float] = None
    level: Optional[float] = None  # e.g. 0.95 confidence level, if the source says so
    unit: str = "PERCENTAGE_POINT"
    raw: Optional[str] = None


class ForecastMeasurementSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    region_id: Optional[str] = None
    election_id: Optional[str] = None
    candidate_or_outcome: str
    #: The source's own number, untouched (0..100). ``None`` only when the
    #: source published something a percentage cannot represent.
    probability: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    measurement_type: MeasurementType
    source: str
    source_id: str
    source_url: Optional[str] = None
    measured_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None
    methodology: Optional[str] = None
    population: Optional[str] = None
    sample_size: Optional[int] = None
    uncertainty: Optional[UncertaintySchema] = None
    #: Real activity figures (e.g. prediction-market volume, FEC receipts) —
    #: only ever relayed from the source, never estimated.
    activity: Optional[Dict[str, Any]] = None
    is_current: bool = True
    notes: Optional[str] = None


class MeasurementBundleSchema(BaseModel):
    """All sourced measurements for one region/election, grouped by type.

    ``sources_disagree`` is present only when two or more sources published
    numbers for the same outcome — and it keeps both, it never picks one.
    """

    region_id: Optional[str] = None
    election_id: Optional[str] = None
    measurements: List[ForecastMeasurementSchema] = Field(default_factory=list)
    by_type: Dict[str, List[ForecastMeasurementSchema]] = Field(default_factory=dict)
    sources_disagree: bool = False
    conflict_note: Optional[str] = None
    disclaimer: str = (
        "All numbers are quoted from the named external sources. This "
        "application does not generate, adjust or rank political probabilities."
    )


# ---------------------------------------------------------------------------
# timeline (spec §12)
# ---------------------------------------------------------------------------

class TimelineEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    title: str
    url: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    category: PoliticalCategory = PoliticalCategory.OTHER
    classification_basis: str = "SOURCE"  # SOURCE | RULE_BASED (always disclosed)
    location: Optional[str] = None
    location_basis: Optional[str] = None  # SOURCE_FIELD | RULE_BASED
    affected_regions: List[str] = Field(default_factory=list)
    language: Optional[str] = None
    notes: Optional[str] = None


class TimelineResponse(BaseModel):
    events: List[TimelineEventSchema]
    meta: Dict[str, Any] = Field(default_factory=dict)
    retrieval: RetrievalMeta


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------

class OverviewResponse(BaseModel):
    """One payload for the map page: events, region states, sources, meta."""

    generated_at: datetime
    events: List[PoliticalEventSchema] = Field(default_factory=list)
    regions: List[PoliticalRegionSchema] = Field(default_factory=list)
    region_states: List[RegionStatusSchema] = Field(default_factory=list)
    measurements: List[ForecastMeasurementSchema] = Field(default_factory=list)
    sources: List[SourceInfoSchema] = Field(default_factory=list)
    election_ids: List[str] = Field(default_factory=list)
    retrieval: RetrievalMeta
    neutrality: Dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = (
        "Informational visualization of externally published political data. "
        "This application does not predict elections, endorse candidates or "
        "recommend any political outcome."
    )


class RegionsResponse(BaseModel):
    regions: List[PoliticalRegionSchema]
    region_states: List[RegionStateDetail]
    retrieval: RetrievalMeta


class RegionStateDetail(BaseModel):
    region_id: str
    state: RegionDataState
    reason: Optional[str] = None
    election_id: Optional[str] = None
    measurement_count: int = 0
    source_ids: List[str] = Field(default_factory=list)
    last_measurement_at: Optional[datetime] = None


class RegionDetailResponse(BaseModel):
    region: PoliticalRegionSchema
    state: RegionStateDetail
    measurements: MeasurementBundleSchema
    events: List[PoliticalEventSchema] = Field(default_factory=list)
    timeline: List[TimelineEventSchema] = Field(default_factory=list)
    historical: List[ForecastMeasurementSchema] = Field(default_factory=list)
    retrieval: RetrievalMeta


class EventsResponse(BaseModel):
    events: List[PoliticalEventSchema]
    meta: Dict[str, Any] = Field(default_factory=dict)
    retrieval: RetrievalMeta


class MeasurementsResponse(BaseModel):
    measurements: List[ForecastMeasurementSchema]
    by_type: Dict[str, List[ForecastMeasurementSchema]] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    retrieval: RetrievalMeta


class HeadToHeadResponse(BaseModel):
    """Neutral comparison view (spec §10): sourced numbers side by side.

    There is deliberately no ``winner``, no ``ranking`` and no
    ``recommendation`` field anywhere in this model.
    """

    election_id: Optional[str] = None
    region_id: Optional[str] = None
    title: str
    rows: List[ForecastMeasurementSchema] = Field(default_factory=list)
    grouped_by_source: Dict[str, List[ForecastMeasurementSchema]] = Field(default_factory=dict)
    note: str = (
        "Side-by-side sourced measurements only. Ordering is by source and "
        "measurement date, never by an implied preference."
    )
    disclaimer: str = (
        "This view does not declare winners, rank candidates or recommend any "
        "choice. Percentages are quoted verbatim from the named sources."
    )
    retrieval: RetrievalMeta


class SourcesResponse(BaseModel):
    sources: List[SourceInfoSchema]
    summary: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class PoliticalMetaResponse(BaseModel):
    """Self-describing metadata the UI renders its legend/disclaimers from."""

    measurement_types: List[str] = Field(default_factory=list)
    region_states: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    freshness_window_days: int
    stale_after_days: int
    conflict_threshold: float
    geometry_sources: List[Dict[str, Any]] = Field(default_factory=list)
    neutrality: Dict[str, Any] = Field(default_factory=dict)


class PoliticalHealthResponse(BaseModel):
    status: str
    phase: int = 18
    providers: List[ProviderReportSchema] = Field(default_factory=list)
    caches: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


__all__ = [
    "MeasurementType",
    "RegionDataState",
    "SourceStatus",
    "PoliticalCategory",
    "SourceInfoSchema",
    "ProviderReportSchema",
    "RetrievalMeta",
    "PoliticalEventSchema",
    "GeometryRefSchema",
    "PopulationContextSchema",
    "PoliticalRegionSchema",
    "RegionStatusSchema",
    "UncertaintySchema",
    "ForecastMeasurementSchema",
    "MeasurementBundleSchema",
    "TimelineEventSchema",
    "TimelineResponse",
    "OverviewResponse",
    "RegionsResponse",
    "RegionStateDetail",
    "RegionDetailResponse",
    "EventsResponse",
    "MeasurementsResponse",
    "HeadToHeadResponse",
    "SourcesResponse",
    "PoliticalMetaResponse",
    "PoliticalHealthResponse",
]
