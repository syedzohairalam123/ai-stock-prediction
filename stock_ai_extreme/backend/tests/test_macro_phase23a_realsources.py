"""Phase 23A — tests for the real-source adapters added in this pass.

Everything here is offline and deterministic: the official-calendar parsers
run against saved markup, the FRED CSV parser runs against a saved body, and
the expectation aggregation runs against a saved Gamma payload. The live
network paths are verified separately against the running server.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.macro_intelligence.expectations import (
    aggregate_event,
    fetch_policy_expectations,
    select_nearest_event,
    _classify,
    _yes_price,
)
from app.macro_intelligence.models import DataFreshness
from app.macro_intelligence.sources import (
    BankOfJapanSource,
    FederalReserveSource,
    FREDSource,
    FOMC_KNOWN_MEETINGS,
    _estimated_freshness,
    _infer_frequency,
)
from app.db import init_db, session_scope
from app.macro_intelligence.service import macro_service
from app.models import MacroSeries as MacroSeriesModel


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:  # noqa: D401 - test stub
        return None


class _FakeClient:
    """Minimal httpx.Client stand-in returning a fixed body."""

    def __init__(self, text: str):
        self._text = text

    def get(self, url, **kwargs):  # noqa: ANN001 - test stub
        return _FakeResponse(self._text)


# ---------------------------------------------------------------------------
# Official calendar parsers
# ---------------------------------------------------------------------------

FOMC_HTML = """
<h4>2026 FOMC Meetings</h4>
<div class="row fomc-meeting ">
  <div class="fomc-meeting__month col-xs-5 col-sm-3 col-md-2"><strong>January</strong></div>
  <div class="fomc-meeting__date col-xs-4 col-sm-9 col-md-10 col-lg-1">27-28</div>
</div>
<div class="row fomc-meeting ">
  <div class="fomc-meeting--shaded fomc-meeting__month"><strong>January/February</strong></div>
  <div class="fomc-meeting__date">31-1</div>
</div>
<div class="row fomc-meeting ">
  <div class="fomc-meeting__month"><strong>October</strong></div>
  <div class="fomc-meeting__date">27-28</div>
</div>
<div>Minutes: (Released February 18, 2026)</div>
"""

BOJ_HTML = """
<h3>Table : 2026</h3>
<table>
  <tr><td>Date of MPM</td><td>Release Schedule</td></tr>
  <tr><td>Jan. 22 (Thurs.), 23 (Fri.) [PDF]</td><td>Jan. 23 (Fri.) [PDF]</td></tr>
  <tr><td>Mar. 18 (Wed.), 19 (Thurs.) [PDF]</td><td>-</td></tr>
</table>
"""


class TestFOMCCalendarParser:
    def test_parses_meeting_cells_not_minutes_release_dates(self):
        src = FederalReserveSource()
        src.client = _FakeClient(FOMC_HTML)
        meetings = src._scrape_fomc_calendar()

        days = {m.scheduled_at.date().isoformat() for m in meetings}
        assert days == {"2026-01-28", "2026-02-01", "2026-10-28"}
        # "Released February 18, 2026" is a minutes release, not a meeting.
        assert "2026-02-18" not in days
        # A month-crossing meeting resolves to its decision month.
        jan_feb = [m for m in meetings if m.scheduled_at.date().isoformat() == "2026-02-01"]
        assert jan_feb and jan_feb[0].timezone == "America/New_York"

    def test_fallback_schedule_has_no_bogus_2026_entries(self):
        dates = {date for date, _ in FOMC_KNOWN_MEETINGS}
        # The prior table wrongly listed a November 2026 meeting and a
        # 2026-06-09 / 2026-12-15 date; the real calendar has October and 12-09.
        assert "2026-10-28" in dates
        assert "2026-11-03" not in dates
        assert "2026-06-09" not in dates
        assert "2026-12-09" in dates


class TestBOJCalendarParser:
    def test_parses_two_day_meeting_rows_only(self):
        src = BankOfJapanSource()
        src.client = _FakeClient(BOJ_HTML)
        meetings = src._scrape_boj_calendar()

        days = {m.scheduled_at.date().isoformat() for m in meetings}
        # Only the two-day meeting rows are taken; the single-day release
        # cells ("Jan. 23 (Fri.)") must not become meetings.
        assert days == {"2026-01-23", "2026-03-19"}
        assert all(m.timezone == "Asia/Tokyo" for m in meetings)


# ---------------------------------------------------------------------------
# Keyless FRED CSV
# ---------------------------------------------------------------------------

CSV_BODY = (
    "observation_date,DGS10\n"
    "2026-10-01,5.24\n"
    "2026-10-02,.\n"
    "2026-10-05,5.31\n"
)


class TestKeylessFRED:
    def test_parse_csv_skips_missing_values(self):
        rows = FREDSource._parse_csv(CSV_BODY)
        assert len(rows) == 2
        assert rows[0][1] == 5.24
        assert rows[-1][0].date().isoformat() == "2026-10-05"

    def test_fetch_series_uses_csv_when_no_api_key(self):
        src = FREDSource(api_key="")
        src.client = _FakeClient(CSV_BODY)
        observations = src.fetch_series("DGS10", limit=10)
        assert len(observations) == 2
        assert observations[0].source == "FRED CSV"
        assert observations[0].unit == "%"
        assert observations[0].frequency == "Daily"

    def test_infer_frequency_from_spacing(self):
        daily = [datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(5)]
        monthly = [datetime(2026, m, 1, tzinfo=timezone.utc) for m in range(1, 6)]
        assert _infer_frequency(daily) == "Daily"
        assert _infer_frequency(monthly) == "Monthly"

    def test_estimated_freshness_scales_to_cadence(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        # Current monthly reading (30 days old) is RECENT, not STALE.
        recent = _estimated_freshness(datetime(2026, 9, 7, tzinfo=timezone.utc), "Monthly", now)
        assert recent == DataFreshness.RECENT
        # One reference period back is DELAYED.
        delayed = _estimated_freshness(datetime(2026, 8, 1, tzinfo=timezone.utc), "Monthly", now)
        assert delayed == DataFreshness.DELAYED
        # Daily series use plain wall-clock freshness.
        stale_daily = _estimated_freshness(datetime(2026, 9, 7, tzinfo=timezone.utc), "Daily", now)
        assert stale_daily == DataFreshness.STALE


# ---------------------------------------------------------------------------
# Polymarket expectation aggregation
# ---------------------------------------------------------------------------

FED_EVENT = {
    "title": "Fed Decision in October?",
    "slug": "fed-decision-in-october",
    "closed": False,
    "endDate": "2026-10-29T03:59:00Z",
    "updatedAt": "2026-10-07T10:53:27Z",
    "markets": [
        {"question": "Will the Fed decrease interest rates by 50+ bps after the October 2026 meeting?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.0015\", \"0.9985\"]"},
        {"question": "Will the Fed decrease interest rates by 25 bps after the October 2026 meeting?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.0055\", \"0.9945\"]"},
        {"question": "Will there be no change in Fed interest rates after the October 2026 meeting?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.825\", \"0.175\"]"},
        {"question": "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.165\", \"0.835\"]"},
        {"question": "Will the Fed increase interest rates by 50+ bps after the October 2026 meeting?",
         "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.0035\", \"0.9965\"]"},
    ],
}


class TestExpectationAdapter:
    def test_classify_directions(self):
        assert _classify("Will there be no change in Fed rates?") == "UNCHANGED"
        assert _classify("decrease interest rates by 25 bps") == "CUT"
        assert _classify("increase interest rates by 50+ bps") == "HIKE"
        # Third-person wording, as the Bank of Japan's contracts use.
        assert _classify("Bank of Japan increases interest rates by 25 bps?") == "HIKE"
        assert _classify("Bank of Japan decreases interest rates by 25 bps?") == "CUT"
        assert _classify("who will win the election") is None

    def test_yes_price_reads_labelled_outcome(self):
        assert _yes_price({"outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.825\", \"0.175\"]"}) == 0.825

    def test_aggregate_third_person_contracts(self):
        event = {
            "title": "Bank of Japan Decision in October?",
            "slug": "boj",
            "closed": False,
            "endDate": "2026-10-30T00:00:00Z",
            "markets": [
                {"question": "Bank of Japan increases interest rates by 25 bps after the October 2026 meeting?",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.03\", \"0.97\"]"},
                {"question": "No change in Bank of Japan's interest rates after the October 2026 meeting?",
                 "outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.966\", \"0.034\"]"},
            ],
        }
        expectation = aggregate_event(event, "BOJ")
        assert expectation.probability_hike == pytest.approx(3.0, abs=0.01)
        assert expectation.probability_unchanged == pytest.approx(96.6, abs=0.01)
        assert expectation.expected_outcome == "UNCHANGED"

    def test_aggregate_event_derives_probabilities(self):
        expectation = aggregate_event(FED_EVENT, "FED")
        assert expectation is not None
        assert expectation.expected_outcome == "UNCHANGED"
        assert expectation.probability_hike == pytest.approx(16.85, abs=0.01)
        assert expectation.probability_cut == pytest.approx(0.70, abs=0.01)
        assert expectation.probability_unchanged == pytest.approx(82.5, abs=0.01)
        assert expectation.meeting_scheduled_at.date().isoformat() == "2026-10-29"
        assert expectation.source == "Polymarket"
        assert expectation.source_url.endswith("fed-decision-in-october")

    def test_total_is_within_rounding_tolerance(self):
        expectation = aggregate_event(FED_EVENT, "FED")
        total = (
            expectation.probability_hike
            + expectation.probability_cut
            + expectation.probability_unchanged
        )
        assert 99.0 <= total <= 101.0

    def test_select_nearest_event_skips_closed_and_stale(self):
        now = datetime(2026, 10, 7, tzinfo=timezone.utc)
        events = [
            {**FED_EVENT, "slug": "closed", "closed": True},
            {**FED_EVENT, "slug": "dec", "endDate": "2026-12-10T05:00:00Z"},
            FED_EVENT,
            {**FED_EVENT, "slug": "old", "endDate": "2025-01-01T00:00:00Z"},
        ]
        chosen = select_nearest_event(events, r"fed\s+decision\s+in\s+\w+", now=now)
        assert chosen is not None
        assert chosen["slug"] == "fed-decision-in-october"

    @pytest.mark.asyncio
    async def test_unknown_bank_returns_empty_not_fabricated(self):
        assert await fetch_policy_expectations("ECB") == []


# ---------------------------------------------------------------------------
# Service: indicators + policy range (offline)
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_series():
    init_db()
    with session_scope() as db:
        db.query(MacroSeriesModel).filter(MacroSeriesModel.series_id == "UNRATE").delete()
        for day, value in ((datetime(2026, 8, 1, tzinfo=timezone.utc), 4.1),
                           (datetime(2026, 9, 1, tzinfo=timezone.utc), 4.2)):
            db.add(MacroSeriesModel(
                series_id="UNRATE", observation_date=day, release_date=day,
                value=value, unit="%", frequency="Monthly", source="FRED CSV",
                source_url="https://fred.stlouisfed.org/series/UNRATE",
                data_freshness="RECENT",
            ))
    yield


class TestServiceIndicators:
    def test_indicators_include_latest_and_change(self, seeded_series):
        indicators = macro_service.get_macro_indicators(keys=["unemployment"])
        assert len(indicators) == 1
        indicator = indicators[0]
        assert indicator["label"] == "Unemployment Rate"
        assert indicator["value"] == pytest.approx(4.2)
        assert indicator["change"] == pytest.approx(0.1, abs=0.001)
        assert indicator["release_date_estimated"] is True

    def test_unknown_bank_policy_range_is_unavailable(self):
        payload = macro_service.get_policy_rate_range("ZZZ")
        assert payload["status"] == "UNAVAILABLE"
        assert payload["lower"] is None and payload["upper"] is None
