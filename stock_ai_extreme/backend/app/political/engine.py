"""
The Phase 18 aggregation engine.

Responsibilities (and non-responsibilities):

* Fans out to the provider registry, isolating failures per source.
* Classifies each region's *presentation state* (AVAILABLE / NO_DATA /
  OUTDATED / CONTESTED / RESOLVED) purely from what sources supplied and the
  configured freshness windows. It never assigns a political colour.
* Detects source conflicts and keeps **both** numbers side by side — it never
  silently chooses one (spec §19).
* Caches per capability with TTLs from settings; ``force=True`` bypasses.

Hard non-responsibilities: no probability is ever computed, averaged,
weighted or imputed here. If the engine finds no sourced number, the answer
is "no data", never an invented one.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from ...logging_config import get_logger
from .config import political_settings
from .providers import (
    GdeltProvider,
    MedslProvider,
    OpenFECProvider,
    PoliticalDataProvider,
    PolymarketProvider,
    PopulationProvider,
    build_default_providers,
    provider_reports,
)
from .providers.base import ProviderResult
from . import regions as region_registry
from .schemas import (
    EventsResponse,
    ForecastMeasurementSchema,
    GeometryRefSchema,
    HeadToHeadResponse,
    MeasurementBundleSchema,
    MeasurementType,
    MeasurementsResponse,
    OverviewResponse,
    PoliticalCategory,
    PoliticalEventSchema,
    PoliticalHealthResponse,
    PoliticalMetaResponse,
    PoliticalRegionSchema,
    RegionDataState,
    RegionDetailResponse,
    RegionStateDetail,
    RegionStatusSchema,
    RetrievalMeta,
    SourceInfoSchema,
    SourceStatus,
    TimelineEventSchema,
    TimelineResponse,
)

logger = get_logger("neural_market.political.engine")

_HISTORICAL_TYPES = {MeasurementType.HISTORICAL_RESULT}
ProviderPair = Tuple[PoliticalDataProvider, ProviderResult]


class _TTLCache:
    """A tiny async-safe TTL cache (one slot per capability is enough here)."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = asyncio.Lock()
        self._expires_at: float = 0.0
        self._value: Any = None
        self.hits = 0
        self.misses = 0

    async def get_or_build(self, ttl_seconds: int, builder: Callable[[], Awaitable[Any]], force: bool = False) -> Tuple[Any, bool]:
        """Returns (value, cache_hit). On expiry exactly one caller rebuilds."""
        now = time.monotonic()
        if not force and self._value is not None and now < self._expires_at:
            self.hits += 1
            return self._value, True
        async with self._lock:
            now = time.monotonic()
            if not force and self._value is not None and now < self._expires_at:
                self.hits += 1
                return self._value, True
            self.misses += 1
            value = await builder()
            self._value = value
            self._expires_at = time.monotonic() + max(int(ttl_seconds), 1)
            return value, False

    def invalidate(self) -> None:
        self._value = None
        self._expires_at = 0.0

    def stats(self) -> Dict[str, Any]:
        return {"hits": self.hits, "misses": self.misses, "primed": self._value is not None}


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _measurement_time(measurement: ForecastMeasurementSchema) -> Optional[datetime]:
    """The most honest timestamp a measurement has: when the source says it
    was measured; fall back to the source's own update time."""
    return _aware(measurement.measured_at) or _aware(measurement.updated_at)


class PoliticalEngine:
    """Neutral aggregation over the Phase 18 provider registry."""

    def __init__(self, providers: Optional[Sequence[PoliticalDataProvider]] = None) -> None:
        all_providers = list(providers) if providers is not None else build_default_providers()
        self.providers: List[PoliticalDataProvider] = []
        for provider in all_providers:
            enabled = {
                OpenFECProvider: political_settings.enable_fec,
                PolymarketProvider: political_settings.enable_polymarket,
                MedslProvider: political_settings.enable_medsl_history,
                GdeltProvider: political_settings.enable_gdelt,
            }.get(type(provider), True)
            if enabled:
                self.providers.append(provider)
            else:
                logger.info("political provider %s disabled by configuration", provider.provider_id)
        self.population = PopulationProvider()
        self._provider_by_id = {p.provider_id: p for p in self.providers}

        self._events_cache = _TTLCache("events")
        self._measurements_cache = _TTLCache("measurements")
        self._history_cache = _TTLCache("history")
        self._timeline_cache = _TTLCache("timeline")
        self._regions_cache = _TTLCache("regions")

    # ------------------------------------------------------------------
    # provider fan-out (each result keeps its provider for attribution)
    # ------------------------------------------------------------------
    async def _gather(self, capability: str) -> List[ProviderPair]:
        """Run one capability across all providers that have it.

        ``asyncio.gather`` preserves call order and provider exceptions are
        already contained inside ``provider.fetch``, so ordering pairs is safe.
        """
        targets = [p for p in self.providers if p.has(capability)]

        async def one(provider: PoliticalDataProvider) -> Tuple[PoliticalDataProvider, ProviderResult]:
            if capability == PoliticalDataProvider.CAP_EVENTS:
                return provider, await provider.get_events()
            if capability == PoliticalDataProvider.CAP_REGIONAL_MEASUREMENTS:
                return provider, await provider.get_regional_measurements()
            if capability == PoliticalDataProvider.CAP_HISTORICAL_MEASUREMENTS:
                return provider, await provider.get_historical_measurements()
            if capability == PoliticalDataProvider.CAP_TIMELINE:
                return provider, await provider.get_timeline()
            return provider, ProviderResult(status=SourceStatus.UNAVAILABLE, error="unknown capability")

        return list(await asyncio.gather(*(one(p) for p in targets)))

    # ------------------------------------------------------------------
    # cached bundles
    # ------------------------------------------------------------------
    async def events_bundle(self, force: bool = False) -> Tuple[List[PoliticalEventSchema], List[ProviderPair], bool]:
        async def build():
            pairs = await self._gather(PoliticalDataProvider.CAP_EVENTS)
            unique: Dict[str, PoliticalEventSchema] = {}
            for _provider, result in pairs:
                for event in result.items:
                    unique.setdefault(event.id, event)
            ordered = sorted(unique.values(), key=lambda e: (
                e.election_date is None,
                e.election_date or datetime.max.replace(tzinfo=timezone.utc),
                e.name,
            ))
            return ordered, pairs

        value, hit = await self._events_cache.get_or_build(
            political_settings.events_cache_ttl_seconds, build, force=force,
        )
        return value[0], value[1], hit

    async def measurements_bundle(self, force: bool = False) -> Tuple[List[ForecastMeasurementSchema], List[ProviderPair], bool]:
        async def build():
            pairs = await self._gather(PoliticalDataProvider.CAP_REGIONAL_MEASUREMENTS)
            measurements: List[ForecastMeasurementSchema] = []
            for _provider, result in pairs:
                measurements.extend(result.items)
            return measurements, pairs

        value, hit = await self._measurements_cache.get_or_build(
            political_settings.measurements_cache_ttl_seconds, build, force=force,
        )
        return value[0], value[1], hit

    async def history_bundle(self, force: bool = False) -> Tuple[List[ForecastMeasurementSchema], List[ProviderPair], bool]:
        async def build():
            pairs = await self._gather(PoliticalDataProvider.CAP_HISTORICAL_MEASUREMENTS)
            measurements: List[ForecastMeasurementSchema] = []
            for _provider, result in pairs:
                measurements.extend(result.items)
            return measurements, pairs

        value, hit = await self._history_cache.get_or_build(
            political_settings.historical_cache_ttl_seconds, build, force=force,
        )
        return value[0], value[1], hit

    async def timeline_bundle(self, force: bool = False) -> Tuple[List[TimelineEventSchema], List[ProviderPair], bool]:
        async def build():
            pairs = await self._gather(PoliticalDataProvider.CAP_TIMELINE)
            unique: Dict[str, TimelineEventSchema] = {}
            for _provider, result in pairs:
                for event in result.items:
                    unique.setdefault(event.id, event)
            return list(unique.values()), pairs

        value, hit = await self._timeline_cache.get_or_build(
            political_settings.timeline_cache_ttl_seconds, build, force=force,
        )
        return value[0], value[1], hit

    # ------------------------------------------------------------------
    # region registry
    # ------------------------------------------------------------------
    async def regions_bundle(self, force: bool = False) -> List[PoliticalRegionSchema]:
        async def build() -> List[PoliticalRegionSchema]:
            out: List[PoliticalRegionSchema] = []
            geometry_reference = "https://github.com/plotly/plotly.js/tree/master/dist/geo"
            geometry_provider = "plotly.js built-in geo data (Natural Earth / US Census derived)"

            us_geometry = GeometryRefSchema(
                format="topojson",
                provider=geometry_provider,
                location_mode="USA-states",
                reference_url=geometry_reference,
            )
            for identity in region_registry.STATES:
                out.append(PoliticalRegionSchema(
                    id=f"us-state:{identity.code}",
                    name=identity.name,
                    country="US",
                    country_name="United States",
                    state_code=identity.code,
                    fips_code=identity.fips,
                    geometry=GeometryRefSchema(
                        format=us_geometry.format,
                        provider=us_geometry.provider,
                        location_mode=us_geometry.location_mode,
                        location_key=identity.code,
                        reference_url=geometry_reference,
                    ),
                    population_context=await self.population.state_population(identity.fips),
                    source="U.S. Census Bureau state FIPS reference (identity data only)",
                    source_url="https://www.census.gov/library/reference/code-lists/ansi.html",
                    region_type="STATE" if identity.code != "DC" else "DISTRICT",
                ))

            country_geometry = GeometryRefSchema(
                format="topojson",
                provider=geometry_provider,
                location_mode="country names",
                reference_url=geometry_reference,
            )
            for country in region_registry.COUNTRIES:
                out.append(PoliticalRegionSchema(
                    id=f"country:{country.iso3}",
                    name=country.name,
                    country=country.iso3,
                    country_name=country.name,
                    state_code=None,
                    fips_code=None,
                    geometry=GeometryRefSchema(
                        format=country_geometry.format,
                        provider=country_geometry.provider,
                        location_mode=country_geometry.location_mode,
                        location_key=country.name,
                        reference_url=geometry_reference,
                    ),
                    population_context=await self.population.country_population(country.iso3),
                    source="ISO 3166 country codes (identity data only)",
                    source_url="https://www.iso.org/iso-3166-country-codes.html",
                    region_type="COUNTRY",
                ))
            return out

        value, _hit = await self._regions_cache.get_or_build(
            political_settings.regions_cache_ttl_seconds, build, force=force,
        )
        return value

    # ------------------------------------------------------------------
    # region state classification (spec §7)
    # ------------------------------------------------------------------
    def classify_region(
        self,
        region_id: str,
        measurements: Sequence[ForecastMeasurementSchema],
        election_id: Optional[str] = None,
    ) -> RegionStatusSchema:
        relevant = [
            m for m in measurements
            if m.region_id == region_id and (election_id is None or m.election_id == election_id)
        ]
        now = datetime.now(timezone.utc)
        stale_after = timedelta(days=political_settings.stale_after_days)
        fresh_after = timedelta(days=political_settings.freshness_window_days)

        current: List[ForecastMeasurementSchema] = []
        historical: List[ForecastMeasurementSchema] = []
        outdated: List[ForecastMeasurementSchema] = []
        for measurement in relevant:
            moment = _measurement_time(measurement)
            if measurement.measurement_type in _HISTORICAL_TYPES or not measurement.is_current:
                historical.append(measurement)
                continue
            if moment is not None and now - moment > stale_after:
                outdated.append(measurement)
                continue
            current.append(measurement)

        last = max((_measurement_time(m) for m in relevant), default=None)
        last_item = next((m for m in relevant if _measurement_time(m) == last), None)
        types_present = sorted({m.measurement_type for m in relevant}, key=lambda t: t.value)
        active = current or outdated
        source_ids = sorted({m.source_id for m in active}) if active else sorted({m.source_id for m in historical})

        def _status(state: RegionDataState, reason: Optional[str]) -> RegionStatusSchema:
            return RegionStatusSchema(
                region_id=region_id,
                state=state,
                reason=reason,
                election_id=election_id,
                measurement_count=len(relevant),
                source_ids=source_ids,
                last_measurement_at=last,
                last_measured_by=last_item.source if last_item else None,
                measurement_types=types_present,
            )

        if current and self._sources_conflict(current):
            return _status(
                RegionDataState.CONTESTED,
                f"Sources disagree beyond the {political_settings.conflict_threshold * 100:.0f}-point "
                "threshold; every sourced number is still shown.",
            )
        if current:
            fresh_enough = any(
                (moment := _measurement_time(m)) is not None and now - moment <= fresh_after
                for m in current
            )
            if fresh_enough:
                return _status(RegionDataState.AVAILABLE, None)
            return _status(
                RegionDataState.OUTDATED,
                "Sourced data exists but is older than the freshness window "
                f"({political_settings.freshness_window_days} days).",
            )
        if outdated:
            return _status(
                RegionDataState.OUTDATED,
                f"All sourced data is older than {political_settings.stale_after_days} days.",
            )
        if historical:
            return _status(
                RegionDataState.RESOLVED,
                "Only historical or resolved sourced data exists for this view.",
            )
        return _status(
            RegionDataState.NO_DATA,
            "No external source currently provides data for this region.",
        )

    @staticmethod
    def _sources_conflict(measurements: Sequence[ForecastMeasurementSchema]) -> bool:
        """True when ≥2 sources published different numbers for the same
        outcome and the gap exceeds the configured threshold.

        Detection only — the conflicting measurements stay in the payload so
        the UI can show both (spec §19: never silently choose one).
        """
        by_outcome: Dict[Tuple[Optional[str], str], Dict[str, float]] = {}
        for measurement in measurements:
            if measurement.probability is None:
                continue
            key = (measurement.election_id, measurement.candidate_or_outcome)
            by_outcome.setdefault(key, {}).setdefault(measurement.source_id, measurement.probability)
        threshold = political_settings.conflict_threshold
        return any(
            len(per_source) >= 2 and (max(per_source.values()) - min(per_source.values())) > threshold
            for per_source in by_outcome.values()
        )

    # ------------------------------------------------------------------
    # shared helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _retrieval_meta(generated_at: datetime, pairs: Sequence[ProviderPair], cache_hit: bool) -> RetrievalMeta:
        return RetrievalMeta(
            generated_at=generated_at,
            providers=provider_reports([(provider.provider_id, result) for provider, result in pairs]),
            cache="HIT" if cache_hit else "MISS",
        )

    def _state_detail(self, status: RegionStatusSchema) -> RegionStateDetail:
        return RegionStateDetail(**{key: value for key, value in status.model_dump().items() if key in RegionStateDetail.model_fields})

    # ------------------------------------------------------------------
    # public views
    # ------------------------------------------------------------------
    async def overview(self, election_id: Optional[str] = None) -> OverviewResponse:
        generated_at = datetime.now(timezone.utc)
        events, event_pairs, events_hit = await self.events_bundle()
        measurements, measurement_pairs, measurements_hit = await self.measurements_bundle()
        history, _history_pairs, _history_hit = await self.history_bundle()
        regions = await self.regions_bundle()

        # The map's presentation states look at current *and* historical data;
        # the payload itself stays bounded by shipping current measurements
        # only (history is one endpoint away via /measurements).
        relevant = measurements + history
        states = [
            self.classify_region(region.id, relevant, election_id=election_id)
            for region in regions
            if region.region_type in ("STATE", "DISTRICT") and (election_id is None or election_id.startswith("US-"))
        ]
        if election_id is not None and not election_id.startswith("US-"):
            states += [
                self.classify_region(region.id, relevant, election_id=election_id)
                for region in regions
                if region.region_type == "COUNTRY"
            ]

        visible_events = [e for e in events if election_id is None or e.election_id == election_id]
        election_ids = sorted({
            e.election_id for e in events if e.election_id
        } | {m.election_id for m in measurements + history if m.election_id})

        pairs = list(event_pairs) + list(measurement_pairs)
        return OverviewResponse(
            generated_at=generated_at,
            events=visible_events[: political_settings.max_events],
            regions=regions,
            region_states=states,
            measurements=[
                m for m in measurements
                if election_id is None or m.election_id == election_id
            ],
            sources=self.source_infos(),
            election_ids=election_ids,
            retrieval=self._retrieval_meta(generated_at, pairs, events_hit and measurements_hit),
            neutrality={
                "statement": (
                    "This module presents externally published measurements only. It does not "
                    "predict elections, endorse or rank candidates, infer user preferences or "
                    "recommend any political outcome."
                ),
                "no_aggregation": "Measurements from different sources are never merged into one number.",
                "map_colours": "Map shading encodes DATA AVAILABILITY states, never parties or candidates.",
            },
        )

    async def events_view(
        self,
        category: Optional[PoliticalCategory] = None,
        jurisdiction: Optional[str] = None,
        country: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        source_id: Optional[str] = None,
        upcoming_only: bool = False,
    ) -> EventsResponse:
        generated_at = datetime.now(timezone.utc)
        events, pairs, hit = await self.events_bundle()
        now = datetime.now(timezone.utc)
        out: List[PoliticalEventSchema] = []
        for event in events:
            if category and event.category != category:
                continue
            if jurisdiction and (event.jurisdiction or "").upper() != jurisdiction.upper():
                continue
            if country and event.country.upper() != country.upper():
                continue
            if source_id and event.source_id != source_id:
                continue
            if date_from and (event.election_date is None or event.election_date < date_from):
                continue
            if date_to and (event.election_date is None or event.election_date > date_to):
                continue
            if upcoming_only and (event.election_date is None or event.election_date < now):
                continue
            out.append(event)
        return EventsResponse(
            events=out,
            meta={"count": len(out), "filters": {
                "category": category.value if category else None,
                "jurisdiction": jurisdiction,
                "country": country,
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
                "source_id": source_id,
                "upcoming_only": upcoming_only,
            }},
            retrieval=self._retrieval_meta(generated_at, pairs, hit),
        )

    async def measurements_view(
        self,
        region_id: Optional[str] = None,
        election_id: Optional[str] = None,
        measurement_type: Optional[MeasurementType] = None,
        source_id: Optional[str] = None,
        include_historical: bool = True,
    ) -> MeasurementsResponse:
        generated_at = datetime.now(timezone.utc)
        measurements, pairs, hit = await self.measurements_bundle()
        history, history_pairs, history_hit = await self.history_bundle()
        pool: List[ForecastMeasurementSchema] = list(measurements) + (list(history) if include_historical else [])
        out: List[ForecastMeasurementSchema] = []
        for measurement in pool:
            if region_id and measurement.region_id != region_id:
                continue
            if election_id and measurement.election_id != election_id:
                continue
            if measurement_type and measurement.measurement_type != measurement_type:
                continue
            if source_id and measurement.source_id != source_id:
                continue
            out.append(measurement)
        out.sort(key=lambda m: (
            m.measurement_type.value,
            m.candidate_or_outcome,
            _measurement_time(m) or datetime.min.replace(tzinfo=timezone.utc),
        ))
        by_type: Dict[str, List[ForecastMeasurementSchema]] = {}
        for measurement in out:
            by_type.setdefault(measurement.measurement_type.value, []).append(measurement)
        all_pairs = list(pairs) + list(history_pairs)
        return MeasurementsResponse(
            measurements=out,
            by_type=by_type,
            meta={"count": len(out), "types_present": sorted(by_type.keys())},
            retrieval=self._retrieval_meta(generated_at, all_pairs, hit and history_hit),
        )

    def measurement_bundle(
        self,
        measurements: Sequence[ForecastMeasurementSchema],
        region_id: Optional[str] = None,
        election_id: Optional[str] = None,
    ) -> MeasurementBundleSchema:
        by_type: Dict[str, List[ForecastMeasurementSchema]] = {}
        for measurement in measurements:
            by_type.setdefault(measurement.measurement_type.value, []).append(measurement)
        conflicted = self._sources_conflict(measurements)
        return MeasurementBundleSchema(
            region_id=region_id,
            election_id=election_id,
            measurements=list(measurements),
            by_type=by_type,
            sources_disagree=conflicted,
            conflict_note=(
                "Multiple sources published different numbers for the same outcome. "
                "Both are shown with their own dates and methodologies; the application "
                "does not arbitrate between them."
            ) if conflicted else None,
        )

    async def region_detail(self, region_id: str, election_id: Optional[str] = None) -> Optional[RegionDetailResponse]:
        generated_at = datetime.now(timezone.utc)
        regions = await self.regions_bundle()
        region = next((r for r in regions if r.id == region_id), None)
        if region is None:
            return None
        measurements, pairs, hit = await self.measurements_bundle()
        history, history_pairs, history_hit = await self.history_bundle()
        events, event_pairs, events_hit = await self.events_bundle()
        timeline, timeline_pairs, timeline_hit = await self.timeline_bundle()

        region_measurements = [
            m for m in measurements
            if m.region_id == region_id and (election_id is None or m.election_id == election_id)
        ]
        region_history = [
            m for m in history
            if m.region_id == region_id and (election_id is None or m.election_id == election_id)
        ]
        bundle = self.measurement_bundle(region_measurements, region_id, election_id)
        state = self.classify_region(region_id, region_measurements + region_history, election_id=election_id)
        region_events = [
            e for e in events
            if region_id in (e.region_ids or [])
            or (region.state_code is not None and e.jurisdiction == region.state_code)
        ]
        region_timeline = [
            t for t in timeline
            if region_id in (t.affected_regions or [])
        ][: political_settings.max_timeline_events]

        all_pairs = list(pairs) + list(history_pairs) + list(event_pairs) + list(timeline_pairs)
        return RegionDetailResponse(
            region=region,
            state=self._state_detail(state),
            measurements=bundle,
            events=region_events[: political_settings.max_events],
            timeline=region_timeline,
            historical=region_history,
            retrieval=self._retrieval_meta(generated_at, all_pairs, hit and history_hit and events_hit and timeline_hit),
        )

    async def head_to_head(self, election_id: Optional[str] = None, region_id: Optional[str] = None) -> Optional[HeadToHeadResponse]:
        """Neutral side-by-side view (spec §10). Rows are sorted by source and
        date — deliberately NOT by probability, so the view can never read as
        a ranking."""
        generated_at = datetime.now(timezone.utc)
        measurements, pairs, hit = await self.measurements_bundle()
        pool = [
            m for m in measurements
            if (election_id is None or m.election_id == election_id)
            and (region_id is None or m.region_id == region_id)
        ]
        if not pool:
            return None
        rows = sorted(pool, key=lambda m: (
            m.source,
            _measurement_time(m) or datetime.min.replace(tzinfo=timezone.utc),
            m.candidate_or_outcome,
        ))
        grouped: Dict[str, List[ForecastMeasurementSchema]] = {}
        for row in rows:
            grouped.setdefault(row.source, []).append(row)
        title = election_id or region_id or "Selected comparison"
        return HeadToHeadResponse(
            election_id=election_id,
            region_id=region_id,
            title=f"Sourced measurements — {title}",
            rows=rows,
            grouped_by_source=grouped,
            retrieval=self._retrieval_meta(generated_at, pairs, hit),
        )

    async def timeline_view(
        self,
        category: Optional[PoliticalCategory] = None,
        country: Optional[str] = None,
        region_id: Optional[str] = None,
        hours: int = 72,
        limit: int = 60,
    ) -> TimelineResponse:
        generated_at = datetime.now(timezone.utc)
        events, pairs, hit = await self.timeline_bundle()
        cutoff = generated_at - timedelta(hours=max(1, min(hours, 336)))
        out: List[TimelineEventSchema] = []
        for event in events:
            if event.timestamp < cutoff:
                continue
            if category and event.category != category:
                continue
            if country and (event.location or "").upper() != country.upper():
                continue
            if region_id and region_id not in (event.affected_regions or []):
                continue
            out.append(event)
        out.sort(key=lambda e: e.timestamp, reverse=True)
        return TimelineResponse(
            events=out[: max(1, min(limit, political_settings.max_timeline_events))],
            meta={
                "hours": hours,
                "count": len(out),
                "note": (
                    "Timeline entries are external news coverage (GDELT DOC 2.0). Categories are "
                    "rule-based keyword classifications and are labelled as such; locations come "
                    "from GDELT's own source-country field."
                ),
            },
            retrieval=self._retrieval_meta(generated_at, pairs, hit),
        )

    # ------------------------------------------------------------------
    # sources / meta / health
    # ------------------------------------------------------------------
    def source_infos(self) -> List[SourceInfoSchema]:
        infos: List[SourceInfoSchema] = []
        for provider in self.providers:
            infos.append(SourceInfoSchema(
                id=provider.provider_id,
                name=provider.name,
                kind=provider.kind,
                source_url=provider.source_url,
                description=provider.description,
                attribution=provider.attribution,
                status=provider.status if provider.last_fetch_at else SourceStatus.OK,
                capabilities=sorted(provider.capabilities),
                last_fetch_at=_aware(provider.last_fetch_at),
                last_success_at=_aware(provider.last_success_at),
                last_error=provider.last_error,
                consecutive_errors=provider.consecutive_errors,
                fetch_count=provider.fetch_count,
                requires_key=provider.requires_key,
                key_configured=provider.key_configured(),
            ))
        return infos

    def meta(self) -> PoliticalMetaResponse:
        return PoliticalMetaResponse(
            measurement_types=[t.value for t in MeasurementType],
            region_states=[s.value for s in RegionDataState],
            categories=[c.value for c in PoliticalCategory],
            freshness_window_days=political_settings.freshness_window_days,
            stale_after_days=political_settings.stale_after_days,
            conflict_threshold=political_settings.conflict_threshold,
            geometry_sources=[{
                "us_states": "plotly.js built-in topojson (Natural Earth / US Census derived), addressed by USPS code",
                "countries": "plotly.js built-in topojson (Natural Earth), addressed by country name",
            }],
            neutrality={
                "statement": (
                    "This module is informational. It relays externally published measurements "
                    "with their sources, dates and methodologies. It does not generate political "
                    "predictions, endorse or rank candidates, or infer user preferences."
                ),
                "no_invented_probabilities": "Every percentage is quoted from a named source.",
                "no_merged_numbers": "POLL, FORECAST, MODEL and HISTORICAL_RESULT are always kept separate.",
                "no_recommendations": "No field in any response expresses a preferred outcome.",
            },
        )

    def health(self) -> PoliticalHealthResponse:
        return PoliticalHealthResponse(
            status="ok",
            providers=[{
                "provider_id": p.provider_id,
                "ok": p.consecutive_errors == 0,
                "status": (p.status if p.last_fetch_at else SourceStatus.OK).value,
                "items": p.fetch_count,
                "duration_ms": None,
                "error": p.last_error,
            } for p in self.providers],
            caches={
                "events": self._events_cache.stats(),
                "measurements": self._measurements_cache.stats(),
                "history": self._history_cache.stats(),
                "timeline": self._timeline_cache.stats(),
                "regions": self._regions_cache.stats(),
            },
            settings={
                "freshness_window_days": political_settings.freshness_window_days,
                "stale_after_days": political_settings.stale_after_days,
                "conflict_threshold": political_settings.conflict_threshold,
                "providers_enabled": [p.provider_id for p in self.providers],
            },
            generated_at=datetime.now(timezone.utc),
        )

    async def refresh(self) -> Dict[str, Any]:
        self._events_cache.invalidate()
        self._measurements_cache.invalidate()
        self._history_cache.invalidate()
        self._timeline_cache.invalidate()
        started = datetime.now(timezone.utc)
        events, event_pairs, _ = await self.events_bundle(force=True)
        measurements, measurement_pairs, _ = await self.measurements_bundle(force=True)
        history, history_pairs, _ = await self.history_bundle(force=True)
        timeline, timeline_pairs, _ = await self.timeline_bundle(force=True)
        return {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc),
            "counts": {
                "events": len(events),
                "measurements": len(measurements),
                "historical": len(history),
                "timeline": len(timeline),
            },
            "providers": provider_reports([
                *( (p.provider_id, r) for p, r in event_pairs ),
                *( (p.provider_id, r) for p, r in measurement_pairs ),
                *( (p.provider_id, r) for p, r in history_pairs ),
                *( (p.provider_id, r) for p, r in timeline_pairs ),
            ]),
        }


engine = PoliticalEngine()

__all__ = ["PoliticalEngine", "engine", "ProviderPair"]
