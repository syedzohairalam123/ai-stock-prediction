"""Phase 23A — central-bank registry, extensibility and honest-error tests.

These cover the additive architecture work: a bank is served because a source
adapter is registered (spec §3), never because of an engine branch, so adding
ECB/BOE/BOC/RBA/SNB later must be provably a registration + catalogue entry.
Everything is offline.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.macro_intelligence import service as service_module
from app.macro_intelligence.models import (
    CentralBankInfo,
    PolicyDecisionInfo,
    PolicyMeetingInfo,
    DecisionDirection,
    MeetingStatus,
    MeetingType,
)
from app.macro_intelligence.service import (
    CENTRAL_BANK_CATALOGUE,
    available_source_banks,
    macro_service,
    register_central_bank_source,
)


class _StubSource:
    """Minimal source adapter used to prove registration is all that is needed."""

    def __init__(self, api_key=None):
        self.bank_info = CentralBankInfo(
            id="ZZZ",
            name="Test Central Bank",
            country="Testland",
            currency="ZZT",
            timezone="UTC",
            source="test",
        )

    def fetch_meetings(self, limit: int = 20) -> list[PolicyMeetingInfo]:
        return [
            PolicyMeetingInfo(
                central_bank_id="ZZZ",
                scheduled_at=datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc),
                timezone="UTC",
                status=MeetingStatus.UPCOMING,
                meeting_type=MeetingType.REGULAR,
            )
        ][:limit]

    def fetch_decisions(self, limit: int = 50) -> list[PolicyDecisionInfo]:
        return [
            PolicyDecisionInfo(
                previous_rate=1.0,
                new_rate=1.25,
                change_bps=25,
                direction=DecisionDirection.HIKE,
                decision_timestamp=datetime(2029, 6, 1, tzinfo=timezone.utc),
                source="Test Central Bank",
            )
        ][:limit]

    def fetch_expectations(self, meeting_id=None):
        return []


@pytest.fixture()
def registered_zzz():
    """Register a brand-new bank, then remove it (registry + rows) so tests stay isolated."""
    register_central_bank_source("ZZZ", lambda key: _StubSource(key))
    macro_service._sources.pop("ZZZ", None)
    yield
    service_module.CENTRAL_BANK_SOURCE_FACTORIES.pop("ZZZ", None)
    macro_service._sources.pop("ZZZ", None)
    init_db()  # teardown may run for a test that never touched the DB
    from app.db import session_scope
    from app.models import PolicyDecision as PolicyDecisionModel
    from app.models import PolicyMeeting as PolicyMeetingModel

    with session_scope() as db:
        meeting_ids = [
            row.id
            for row in db.query(PolicyMeetingModel)
            .filter(PolicyMeetingModel.central_bank_id == "ZZZ")
            .all()
        ]
        for meeting_id in meeting_ids:
            db.query(PolicyDecisionModel).filter(
                PolicyDecisionModel.meeting_id == meeting_id
            ).delete()
        db.query(PolicyMeetingModel).filter(
            PolicyMeetingModel.central_bank_id == "ZZZ"
        ).delete()


class TestRegistry:
    def test_ships_with_fed_and_boj_registered(self):
        assert available_source_banks() == ["BOJ", "FED"]

    def test_catalogue_matches_registered_banks(self):
        assert set(CENTRAL_BANK_CATALOGUE) == {"FED", "BOJ"}

    def test_unknown_bank_has_no_source(self):
        assert macro_service._get_source("ECB") is None

    def test_new_bank_is_served_by_registration_alone(self, registered_zzz):
        source = macro_service._get_source("ZZZ")
        assert source is not None
        assert source.bank_info.name == "Test Central Bank"

    def test_registered_bank_flows_through_the_shared_engine(self, registered_zzz):
        # The exact same fetch/normalise/store path as FED/BOJ is used — no
        # engine change was required to support ZZZ.
        init_db()
        meetings = macro_service.fetch_and_store_meetings("ZZZ", limit=5)
        decisions = macro_service.fetch_and_store_decisions("ZZZ", limit=5)
        assert len(meetings) == 1
        assert len(decisions) == 1
        assert decisions[0]["change_bps"] == 25
        assert decisions[0]["direction"] == "HIKE"

    def test_catalogue_drives_initialization(self):
        init_db()
        macro_service.initialize_central_banks()
        ids = {bank["id"] for bank in macro_service.list_central_banks()}
        assert {"FED", "BOJ"}.issubset(ids)


class TestRoutes:
    @pytest.fixture()
    def client(self):
        init_db()
        from app.main import app

        return TestClient(app)

    def test_supported_banks_route_lists_registered_banks(self, client):
        res = client.get("/api/v1/macro/central-banks/supported")
        assert res.status_code == 200
        body = res.json()
        assert "FED" in body["supported_banks"]
        assert body["count"] == len(body["supported_banks"])

    def test_supported_route_not_shadowed_by_bank_lookup(self, client):
        # ``/central-banks/{bank_id}`` would otherwise swallow the literal path.
        res = client.get("/api/v1/macro/central-banks/supported")
        assert res.status_code == 200
        assert "supported_banks" in res.json()

    def test_upcoming_alias_is_served(self, client):
        # Spec §15 names GET /api/v1/macro/upcoming; it must resolve to the same
        # data path as /meetings (shared implementation, no duplication).
        res = client.get("/api/v1/macro/upcoming?limit=3")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_meeting_payload_includes_source_timestamp_field(self, client):
        # §8 requires the card to carry "Last Updated"; the field is always
        # present (null when the source never captured one) rather than absent.
        res = client.get("/api/v1/macro/upcoming?limit=1")
        assert res.status_code == 200
        rows = res.json()
        if rows:
            assert "source_timestamp" in rows[0]

    def test_health_reports_registered_banks(self, client):
        res = client.get("/api/v1/macro/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert "registered_source_banks" in body

    def test_unknown_series_is_404_not_empty_200(self, client):
        res = client.get("/api/v1/macro/series/NOT_A_REAL_SERIES")
        assert res.status_code == 404
        assert "Unknown macro series" in res.json()["detail"]

    def test_known_series_is_served_even_when_not_yet_refreshed(self, client):
        res = client.get("/api/v1/macro/series/DGS10")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_unknown_bank_policy_history_is_empty_not_error(self, client):
        # "NOPE" was never stored or registered, so this is the true
        # never-seen-bank path: an empty 200, not a 500 and not invented rows.
        res = client.get("/api/v1/macro/policy/NOPE")
        assert res.status_code == 200
        assert res.json() == []
