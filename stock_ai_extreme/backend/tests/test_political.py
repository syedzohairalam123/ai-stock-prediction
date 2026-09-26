"""
Phase 18 — Political & Geopolitical Data Mapping / Forecast Visualization.

These tests pin the two things this phase can get wrong more easily than it can
get anything else wrong:

1. **Neutrality in code.** No measurement may ever be born without a source,
   a measurement date and a measurement type; no probability may be derived,
   averaged or imputed; a region with no sourced data must classify as
   ``NO_DATA`` and never receive an implied outcome.
2. **Honest failure.** One dead provider must degrade to ``UNAVAILABLE`` for
   that provider only, and the map must still answer.

Network access is mocked at the provider seam (the same discipline the rest of
this suite uses); the engine/route tests use a fake provider so they exercise
the aggregation and classification logic, not the internet.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.political.config import political_settings
from app.political.engine import PoliticalEngine
from app.political import regions as region_registry
from app.political.providers.base import PoliticalDataProvider, ProviderResult
from app.political.providers.openfec_provider import OpenFECProvider, normalize_election_date_row
from app.political.providers.polymarket_provider import (
    derive_election_id,
    detect_us_state,
    normalize_market,
)
from app.political.providers.gdelt_provider import (
    classify_category,
    normalize_article,
    parse_seen_date,
)
from app.political.schemas import (
    ForecastMeasurementSchema,
    GeometryRefSchema,
    MeasurementType,
    PoliticalCategory,
    PoliticalEventSchema,
    PoliticalRegionSchema,
    RegionDataState,
    SourceStatus,
    TimelineEventSchema,
)

UTC = timezone.utc
NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# fixtures / fakes
# ---------------------------------------------------------------------------

class FakeProvider(PoliticalDataProvider):
    """A provider with fixed, clearly-sourced content and no network."""

    provider_id = "fake"
    name = "Fake sourced provider"
    kind = "test"
    capabilities = frozenset({
        PoliticalDataProvider.CAP_EVENTS,
        PoliticalDataProvider.CAP_REGIONAL_MEASUREMENTS,
        PoliticalDataProvider.CAP_HISTORICAL_MEASUREMENTS,
        PoliticalDataProvider.CAP_TIMELINE,
    })

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.fail = fail

    async def get_events(self):
        if self.fail:
            return ProviderResult(status=SourceStatus.UNAVAILABLE, error="boom")
        return ProviderResult(items=[PoliticalEventSchema(
            id="fake:event:OH-2026",
            name="2026 US Senate election — Ohio",
            jurisdiction="OH",
            jurisdiction_type="STATE",
            election_date=datetime(2026, 11, 3, tzinfo=UTC),
            category=PoliticalCategory.ELECTION,
            source="Fake source",
            source_id="fake",
            election_id="US-SENATE-OH-2026",
            region_ids=["us-state:OH"],
        )])

    async def get_regional_measurements(self):
        if self.fail:
            return ProviderResult(status=SourceStatus.UNAVAILABLE, error="boom")
        return ProviderResult(items=[
            _measurement("A", 62.0, source_id="fake", source="Fake source"),
            # A second, disagreeing source for the same outcome.
            _measurement("A", 40.0, source_id="fake2", source="Fake source 2"),
        ])

    async def get_historical_measurements(self):
        return ProviderResult(items=[])

    async def get_timeline(self):
        if self.fail:
            return ProviderResult(status=SourceStatus.UNAVAILABLE, error="boom")
        return ProviderResult(items=[TimelineEventSchema(
            id="fake:news:1",
            timestamp=NOW,
            title="Sourced coverage item",
            source="example.com",
            source_url="https://example.com/a",
            category=PoliticalCategory.GOVERNMENT,
            location="US",
            affected_regions=["us-state:OH"],
        )])


def _measurement(
    outcome: str,
    probability: float,
    *,
    source_id: str = "fake",
    source: str = "Fake source",
    measurement_type: MeasurementType = MeasurementType.FORECAST,
    measured_at: datetime | None = None,
    region_id: str = "us-state:OH",
    election_id: str = "US-SENATE-OH-2026",
    is_current: bool = True,
) -> ForecastMeasurementSchema:
    return ForecastMeasurementSchema(
        id=f"{source_id}:{outcome}:{probability}",
        region_id=region_id,
        election_id=election_id,
        candidate_or_outcome=outcome,
        probability=probability,
        measurement_type=measurement_type,
        source=source,
        source_id=source_id,
        measured_at=measured_at or NOW,
        updated_at=measured_at or NOW,
        retrieved_at=NOW,
        methodology="Test methodology",
        is_current=is_current,
    )


class StubPopulation:
    """Population context that returns a clearly-unavailable placeholder."""

    async def state_population(self, fips):  # noqa: ANN001
        return None

    async def country_population(self, iso3):  # noqa: ANN001
        return None


@pytest.fixture()
def fake_engine():
    engine = PoliticalEngine(providers=[FakeProvider()])
    engine.population = StubPopulation()
    return engine


@pytest.fixture()
def client(monkeypatch):
    """A TestClient whose political singleton uses only fake providers."""
    from app.main import app
    from app.political.engine import engine as real
    from app.db import init_db

    init_db()
    monkeypatch.setattr(real, "providers", [FakeProvider()])
    monkeypatch.setattr(real, "population", StubPopulation())
    real._provider_by_id = {"fake": real.providers[0]}
    for cache in (real._events_cache, real._measurements_cache, real._history_cache,
                  real._timeline_cache, real._regions_cache):
        cache.invalidate()
    yield TestClient(app)
    for cache in (real._events_cache, real._measurements_cache, real._history_cache,
                  real._timeline_cache, real._regions_cache):
        cache.invalidate()


# ---------------------------------------------------------------------------
# schema invariants
# ---------------------------------------------------------------------------

def test_measurement_families_are_distinct():
    assert {t.value for t in MeasurementType} == {
        "POLL", "FORECAST", "MODEL", "HISTORICAL_RESULT",
    }


def test_probability_must_be_a_real_percentage():
    with pytest.raises(Exception):
        _measurement("A", 140.0)
    with pytest.raises(Exception):
        _measurement("A", -1.0)


def test_uncertainty_is_absent_unless_the_source_gave_one():
    measurement = _measurement("A", 62.0)
    assert measurement.uncertainty is None


def test_forecast_measurement_requires_a_source_and_a_type():
    fields = ForecastMeasurementSchema.model_fields
    for required in ("source", "source_id", "measurement_type", "candidate_or_outcome"):
        assert required in fields
    # There is deliberately no field through which the app could express an opinion.
    for forbidden in ("recommendation", "winner", "rank", "preferred", "app_estimate"):
        assert forbidden not in fields


# ---------------------------------------------------------------------------
# identity registry (no political content)
# ---------------------------------------------------------------------------

def test_general_election_day_follows_statute():
    assert region_registry.general_election_day(2026) == date(2026, 11, 3)
    assert region_registry.general_election_day(2024) == date(2024, 11, 5)


def test_is_midterm_and_senate_class():
    assert region_registry.is_midterm(2026) is True
    assert region_registry.is_midterm(2024) is False
    assert region_registry.senate_class_up_for_election(2026) == 2


def test_state_registry_contains_no_leanings_or_scores():
    identity_fields = set(region_registry.StateIdentity.__dataclass_fields__)
    for forbidden in ("lean", "rating", "score", "probability", "forecast", "party"):
        assert forbidden not in identity_fields


# ---------------------------------------------------------------------------
# region classification (spec §7)
# ---------------------------------------------------------------------------

def test_region_without_sourced_data_is_no_data(fake_engine):
    status = fake_engine.classify_region("us-state:XX", [])
    assert status.state == RegionDataState.NO_DATA
    assert status.measurement_count == 0


def test_fresh_sourced_measurement_is_available(fake_engine):
    status = fake_engine.classify_region("us-state:OH", [_measurement("A", 62.0)])
    assert status.state == RegionDataState.AVAILABLE


def test_old_measurement_is_outdated(fake_engine):
    old = _measurement(
        "A", 62.0,
        measured_at=NOW - timedelta(days=political_settings.stale_after_days + 5),
    )
    status = fake_engine.classify_region("us-state:OH", [old])
    assert status.state == RegionDataState.OUTDATED


def test_disagreeing_sources_make_a_region_contested(fake_engine):
    measurements = [
        _measurement("A", 62.0, source_id="fake"),
        _measurement("A", 40.0, source_id="fake2", source="Fake source 2"),
    ]
    status = fake_engine.classify_region("us-state:OH", measurements)
    assert status.state == RegionDataState.CONTESTED
    assert len(status.source_ids) == 2


def test_only_historical_data_is_resolved(fake_engine):
    historical = _measurement(
        "A", 62.0,
        measurement_type=MeasurementType.HISTORICAL_RESULT,
        is_current=False,
    )
    status = fake_engine.classify_region("us-state:OH", [historical])
    assert status.state == RegionDataState.RESOLVED


def test_sources_do_not_conflict_within_threshold():
    # 0.5 percentage points apart, well under the default 5-point threshold.
    close = [
        _measurement("A", 51.0, source_id="fake"),
        _measurement("A", 50.5, source_id="fake2", source="Fake source 2"),
    ]
    assert PoliticalEngine._sources_conflict(close) is False


# ---------------------------------------------------------------------------
# provider normalizers (pure, network-free)
# ---------------------------------------------------------------------------

def test_openfec_row_becomes_a_sourced_calendar_event():
    event = normalize_election_date_row({
        "trc_election_id": "12345",
        "office_sought": "S",
        "election_state": "OH",
        "election_year": 2026,
        "election_type": "G",
        "election_date": "2026-11-03",
    }, NOW)
    assert event is not None
    assert event.source_id == "fec"
    assert event.category == PoliticalCategory.ELECTION
    assert event.election_date == datetime(2026, 11, 3, tzinfo=UTC)
    assert event.jurisdiction == "OH"


def test_openfec_live_row_shape_without_trc_id_is_not_dropped():
    # Regression: the live /election-dates/ API returns no `trc_election_id`,
    # so an earlier revision dropped every row and the calendar stayed empty.
    event = normalize_election_date_row({
        "create_date": "2026-01-21T14:48:27",
        "election_date": "2026-12-12",
        "election_district": " ",
        "election_state": "LA",
        "election_type_full": "General runoff",
        "election_type_id": "GR",
        "election_year": 2026,
        "office_sought": "S",
        "update_date": "2026-01-22T16:31:35",
    }, NOW)
    assert event is not None
    assert event.source_id == "fec"
    assert event.jurisdiction == "LA"
    assert event.election_date == datetime(2026, 12, 12, tzinfo=UTC)
    assert event.id.startswith("fec:")


def test_openfec_keeps_page_one_rows_when_a_later_page_is_rate_limited(monkeypatch):
    """A 429 on page 2 must not discard page 1's real calendar rows."""
    import httpx

    live_row = {
        "create_date": "2026-01-21T14:48:27",
        "election_date": "2026-12-12",
        "election_district": " ",
        "election_state": "LA",
        "election_type_full": "General runoff",
        "election_type_id": "GR",
        "election_year": 2026,
        "office_sought": "S",
        "update_date": "2026-01-22T16:31:35",
    }

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.request = httpx.Request("GET", "https://api.open.fec.gov/v1/election-dates/")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("rate limited", request=self.request, response=self)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            page = (params or {}).get("page", 1)
            if page == 1:
                return FakeResponse(200, {"results": [live_row], "pagination": {"pages": 3}})
            return FakeResponse(429)

    import app.political.providers.openfec_provider as module
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(OpenFECProvider().get_events())
    assert len(result.items) == 1
    assert result.items[0].jurisdiction == "LA"


def test_openfec_row_without_a_date_is_still_honest():
    event = normalize_election_date_row({
        "trc_election_id": "9", "office_sought": "H",
        "election_state": "CA", "election_year": 2026, "election_type": "G",
    }, NOW)
    assert event is not None
    assert event.election_date is None


def test_polymarket_state_detection_is_word_bounded():
    assert detect_us_state("Will the Ohio Senate race flip?") == "OH"
    # "OH" embedded in another word must not match.
    assert detect_us_state("Who wins the Ohio primary") == "OH"


def test_polymarket_does_not_match_bare_state_codes_inside_sentences():
    # Regression: matching the *uppercased* text turned the ordinary words
    # "in"/"or"/"me" into Indiana/Oregon/Maine and misattributed a foreign
    # market to a US state. Codes now require genuine uppercase in the source.
    assert detect_us_state("Will Adanech Abiebie be the next prime minister of Ethiopia") is None
    assert detect_us_state("Either this or that will happen") is None
    assert detect_us_state("Tell me the outcome") is None
    # A genuinely uppercase code is still honoured.
    assert detect_us_state("Who wins the OH Senate race?") == "OH"


def test_polymarket_foreign_market_maps_to_country_not_state():
    measurement = normalize_market({
        "id": "99",
        "question": "Will Adanech Abiebie be the next prime minister of Ethiopia?",
        "description": "A market about government formation in Ethiopia.",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.25", "0.75"]',
        "slug": "ethiopia-prime-minister",
        "updatedAt": "2026-09-20T10:00:00Z",
    }, NOW)
    assert measurement is not None
    assert measurement.region_id == "country:ETH"


def test_polymarket_election_id_uses_only_stated_facts():
    assert derive_election_id("2026 Ohio Senate election", "OH", None) == "US-SENATE-OH-2026"
    assert derive_election_id("Should the UK hold a referendum", None, "GBR") == "REFERENDUM-GBR-NA"


def test_polymarket_market_normalizes_to_a_model_measurement():
    raw = {
        "id": "42",
        "question": "2026 Ohio Senate election winner?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.62", "0.38"]',
        "volumeNum": 1000.0,
        "slug": "ohio-senate-2026",
        "updatedAt": "2026-09-20T10:00:00Z",
    }
    measurement = normalize_market(raw, NOW)
    assert measurement is not None
    assert measurement.measurement_type == MeasurementType.MODEL
    assert measurement.probability == 62.0
    assert measurement.uncertainty is None
    assert measurement.activity["volume_usd"] == 1000.0
    assert measurement.region_id == "us-state:OH"


def test_polymarket_ignores_non_political_markets():
    assert normalize_market({
        "id": "1", "question": "Will it rain tomorrow?",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["0.5", "0.5"]',
    }, NOW) is None


def test_gdelt_seendate_parsing_and_category_rules():
    assert parse_seen_date("20260920T114500Z") == datetime(2026, 9, 20, 11, 45, tzinfo=UTC)
    assert parse_seen_date("not-a-date") is None
    assert classify_category("New tariff policy regulation passes") == PoliticalCategory.POLICY
    assert classify_category("Local weather update") == PoliticalCategory.OTHER


def test_gdelt_article_keeps_publisher_attribution_and_discloses_rules():
    event = normalize_article({
        "title": "Ohio election board certifies results",
        "url": "https://example.com/ohio",
        "seendate": "20260920T114500Z",
        "domain": "example.com",
        "sourcecountry": "United States",
    }, NOW)
    assert event is not None
    assert event.classification_basis == "RULE_BASED"
    assert event.location_basis == "SOURCE_FIELD"
    assert "us-state:OH" in event.affected_regions


# ---------------------------------------------------------------------------
# engine views
# ---------------------------------------------------------------------------

def test_engine_overview_never_merges_sources(fake_engine):
    overview = asyncio.run(fake_engine.overview())
    assert overview.neutrality
    assert overview.regions
    # The two conflicting measurements both survive into the payload.
    probabilities = sorted(
        m.probability for m in overview.measurements if m.candidate_or_outcome == "A"
    )
    assert probabilities == [40.0, 62.0]


def test_engine_head_to_head_has_no_winner_field(fake_engine):
    result = asyncio.run(fake_engine.head_to_head(election_id="US-SENATE-OH-2026"))
    assert result is not None
    dumped = result.model_dump()
    for forbidden in ("winner", "ranking", "recommendation", "best"):
        assert forbidden not in dumped


def test_engine_timeline_returns_sourced_coverage(fake_engine):
    timeline = asyncio.run(fake_engine.timeline_view(hours=72))
    assert len(timeline.events) == 1
    assert timeline.events[0].source == "example.com"


def test_engine_degrades_when_a_provider_dies():
    engine = PoliticalEngine(providers=[FakeProvider(fail=True)])
    engine.population = StubPopulation()
    overview = asyncio.run(engine.overview())
    # The map still answers; the dead provider is reported, not hidden.
    assert overview.region_states
    statuses = {report.status for report in overview.retrieval.providers}
    assert SourceStatus.UNAVAILABLE in statuses


def test_engine_meta_documents_neutrality(fake_engine):
    meta = fake_engine.meta()
    assert set(meta.measurement_types) == {
        "POLL", "FORECAST", "MODEL", "HISTORICAL_RESULT",
    }
    assert "no_invented_probabilities" in meta.neutrality


# ---------------------------------------------------------------------------
# routes (FastAPI)
# ---------------------------------------------------------------------------

def test_route_meta_lists_the_four_measurement_families(client):
    body = client.get("/api/political/meta").json()
    assert set(body["measurement_types"]) == {
        "POLL", "FORECAST", "MODEL", "HISTORICAL_RESULT",
    }
    assert body["region_states"]


def test_route_sources_reports_health(client):
    body = client.get("/api/political/sources").json()
    assert body["summary"]["count"] >= 1
    assert body["sources"][0]["capabilities"]


def test_route_regions_builds_state_detail(client):
    response = client.get("/api/political/regions")
    assert response.status_code == 200
    body = response.json()
    assert len(body["regions"]) >= 51  # 50 states + DC
    assert len(body["region_states"]) == len(body["regions"])


def test_route_overview_answers_with_region_states(client):
    response = client.get("/api/political/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["region_states"]
    assert body["neutrality"]["statement"]


def test_route_region_detail_404s_for_unknown_region(client):
    assert client.get("/api/political/regions/us-state:ZZ").status_code == 404


def test_route_region_detail_returns_bundle_for_a_known_state(client):
    response = client.get("/api/political/regions/us-state:OH")
    assert response.status_code == 200
    body = response.json()
    assert body["region"]["state_code"] == "OH"
    assert body["state"]["state"] == RegionDataState.CONTESTED.value
    assert body["measurements"]["sources_disagree"] is True


def test_route_head_to_head_404s_without_measurements(client):
    assert client.get("/api/political/head-to-head?region_id=us-state:ZZ").status_code == 404


def test_route_events_filters_by_category(client):
    body = client.get("/api/political/events?category=ELECTION").json()
    assert all(e["category"] == "ELECTION" for e in body["events"])


def test_route_timeline_returns_coverage(client):
    body = client.get("/api/political/timeline").json()
    assert body["events"]
    assert body["meta"]["count"] >= 1


def test_route_rejects_invalid_date_parameter(client):
    assert client.get("/api/political/events?date_from=not-a-date").status_code == 400
