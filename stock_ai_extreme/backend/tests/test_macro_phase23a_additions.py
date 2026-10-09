"""Phase 23A additions — expectation snapshots + event-window analytics.

The DB-backed tests run against the isolated test database created by
``conftest.py``. The market-data leg is a stub at the same seam the app binds
(``MacroIntelligenceService.configure_market_data``) so the calculation logic is
tested deterministically and offline; the live path is exercised against the
running server separately.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.db import init_db, session_scope
from app.macro_intelligence.service import macro_service
from app.models import (
    CentralBank as CentralBankModel,
    PolicyDecision as PolicyDecisionModel,
    PolicyExpectation as PolicyExpectationModel,
    PolicyMeeting as PolicyMeetingModel,
)


def _frame(n_days: int = 120, base: float = 100.0) -> pd.DataFrame:
    """Deterministic business-day OHLC frame — a test fixture, not market data."""
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    closes = [base + (i % 9) for i in range(n_days)]
    return pd.DataFrame(
        {"Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
         "Close": closes, "Volume": [1_000_000] * n_days},
        index=idx,
    )


async def _stub_history(ticker, start, end, interval="1d"):
    return _frame(), "test-provider", "LIVE"


@pytest.fixture()
def seeded_bank():
    """One central bank + one completed meeting + one decision, in the test DB.

    The decision is dated ~60 calendar days back so it sits inside the
    deterministic 120-business-day frame the stub market-data fetcher returns
    (mirrors what the real provider returns around a real decision).
    """
    init_db()
    decision_at = datetime.combine(
        date.today() - timedelta(days=60), datetime.min.time(), tzinfo=timezone.utc
    )
    with session_scope() as db:
        if not db.query(CentralBankModel).filter(CentralBankModel.id == "FED").first():
            db.add(CentralBankModel(
                id="FED", name="Federal Reserve", country="United States",
                currency="USD", timezone="America/New_York", source="federal_reserve",
            ))
        meeting = PolicyMeetingModel(
            central_bank_id="FED",
            scheduled_at=decision_at,
            timezone="UTC", status="COMPLETED", meeting_type="REGULAR",
        )
        db.add(meeting)
        db.flush()
        if not db.query(PolicyDecisionModel).filter(
            PolicyDecisionModel.meeting_id == meeting.id
        ).first():
            db.add(PolicyDecisionModel(
                meeting_id=meeting.id,
                previous_rate=4.0, new_rate=3.75, change_bps=-25,
                direction="CUT",
                decision_timestamp=decision_at,
                source="Federal Reserve",
                source_document="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            ))
    yield


@pytest.fixture()
def client():
    init_db()
    from app.main import app

    return TestClient(app)


class TestExpectationHistory:
    def test_empty_history_states_unavailable_without_fabricating(self):
        init_db()  # do not depend on another test file having created the schema first
        payload = macro_service.get_expectation_history("FED")
        assert payload["status"] == "UNAVAILABLE"
        assert payload["count"] == 0
        assert payload["snapshots"] == []
        assert payload["statement"] == "Market-implied expectations unavailable."

    def test_snapshot_is_attributed_and_probability_total_is_validated(self, seeded_bank):
        init_db()
        with session_scope() as db:
            meeting = db.query(PolicyMeetingModel).filter(
                PolicyMeetingModel.central_bank_id == "FED"
            ).first()
            db.add(PolicyExpectationModel(
                meeting_id=meeting.id, source="TestDesk",
                observed_at=datetime.now(timezone.utc),
                expected_outcome="CUT",
                probability_hike=0.0, probability_cut=60.0, probability_unchanged=40.0,
                methodology="stub methodology (test fixture)",
            ))
        payload = macro_service.get_expectation_history("FED")
        assert payload["status"] == "LIVE"
        assert payload["count"] == 1
        snap = payload["snapshots"][0]
        assert snap["source"] == "TestDesk"
        assert snap["probability_total"] == 100.0
        assert snap["data_quality"] == "SOURCE-REPORTED"
        assert "rounding tolerance" in snap["probability_note"]

    def test_partial_distribution_is_labelled_not_completed(self, seeded_bank):
        init_db()
        with session_scope() as db:
            meeting = db.query(PolicyMeetingModel).filter(
                PolicyMeetingModel.central_bank_id == "FED"
            ).first()
            db.add(PolicyExpectationModel(
                meeting_id=meeting.id, source="PartialDesk",
                observed_at=datetime.now(timezone.utc),
                probability_unchanged=55.0,
                methodology="reports a single outcome only",
            ))
        payload = macro_service.get_expectation_history("FED")
        snap = payload["snapshots"][0]
        assert snap["probability_total"] == 55.0
        assert "partial distribution" in snap["probability_note"]


class TestEventWindow:
    @pytest.mark.asyncio
    async def test_unavailable_without_market_fetcher(self, seeded_bank):
        macro_service.configure_market_data(None)
        payload = await macro_service.event_window_analysis("FED")
        assert payload["status"] == "UNAVAILABLE"
        assert "Market-data source not configured" in payload["reason"]

    @pytest.mark.asyncio
    async def test_computes_windows_from_real_market_frame(self, seeded_bank):
        macro_service.configure_market_data(_stub_history)
        payload = await macro_service.event_window_analysis(
            "FED", ticker="^GSPC", lookback_decisions=2,
        )
        assert payload["status"] == "LIVE"
        # Other tests in this file seed the same bank too, so assert on the
        # newest analysed decision rather than an absolute row count.
        assert payload["count"] >= 1
        assert payload["market_source"] == "test-provider"
        row = payload["results"][-1]
        assert row["change_bps"] == -25
        assert row["direction"] == "CUT"
        assert row["change_1d"] is not None
        assert row["change_20d"] is not None
        assert "not evidence" in payload["note"]

    @pytest.mark.asyncio
    async def test_unavailable_when_fetcher_raises(self, seeded_bank):
        async def broken(ticker, start, end, interval="1d"):
            raise RuntimeError("provider down")

        macro_service.configure_market_data(broken)
        payload = await macro_service.event_window_analysis("FED")
        assert payload["status"] == "UNAVAILABLE"
        assert "provider down" in payload["reason"]


class TestRoutes:
    def test_expectations_route_reports_honest_state(self, client):
        res = client.get("/api/v1/macro/expectations/FED")
        assert res.status_code == 200
        body = res.json()
        assert "statement" in body

    def test_event_window_rejects_non_integer_window(self, client):
        res = client.get("/api/v1/macro/event-window/FED?windows=1,x")
        assert res.status_code == 400

    def test_event_window_rejects_out_of_range_window(self, client):
        res = client.get("/api/v1/macro/event-window/FED?windows=0")
        assert res.status_code == 400

    def test_event_window_route_is_served(self, client):
        res = client.get("/api/v1/macro/event-window/FED?windows=1,3")
        assert res.status_code == 200
        body = res.json()
        assert "status" in body and "count" in body
