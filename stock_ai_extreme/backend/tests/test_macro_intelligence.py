"""
Phase 23A — Tests for Central Bank and Macroeconomic Intelligence Engine.

Tests:
- bps calculation
- direction determination
- countdown calculation
- data freshness determination
- policy rate analytics
- macro trend analytics
- API endpoints
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

from app.macro_intelligence.models import (
    calculate_bps_change,
    determine_direction,
    calculate_countdown,
    determine_data_freshness,
    DecisionDirection,
    DataFreshness,
)
from app.macro_intelligence.analytics import (
    analyze_policy_rates,
    analyze_macro_trend,
)


class TestBpsCalculation:
    """Test basis point change calculation."""

    def test_hike(self):
        """Test rate hike calculation."""
        assert calculate_bps_change(5.25, 5.50) == 25
        assert calculate_bps_change(4.75, 5.00) == 25
        assert calculate_bps_change(0.00, 0.25) == 25

    def test_cut(self):
        """Test rate cut calculation."""
        assert calculate_bps_change(5.50, 5.25) == -25
        assert calculate_bps_change(5.00, 4.75) == -25
        assert calculate_bps_change(0.25, 0.00) == -25

    def test_unchanged(self):
        """Test unchanged rate calculation."""
        assert calculate_bps_change(5.25, 5.25) == 0
        assert calculate_bps_change(0.00, 0.00) == 0

    def test_large_change(self):
        """Test large rate change calculation."""
        assert calculate_bps_change(0.00, 1.00) == 100
        assert calculate_bps_change(5.00, 3.00) == -200


class TestDirectionDetermination:
    """Test decision direction determination."""

    def test_hike_direction(self):
        """Test hike direction."""
        assert determine_direction(25) == DecisionDirection.HIKE
        assert determine_direction(1) == DecisionDirection.HIKE

    def test_cut_direction(self):
        """Test cut direction."""
        assert determine_direction(-25) == DecisionDirection.CUT
        assert determine_direction(-1) == DecisionDirection.CUT

    def test_unchanged_direction(self):
        """Test unchanged direction."""
        assert determine_direction(0) == DecisionDirection.UNCHANGED


class TestCountdownCalculation:
    """Test meeting countdown calculation."""

    def test_future_meeting(self):
        """Test countdown to future meeting."""
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        meeting_time = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

        countdown = calculate_countdown(meeting_time, now)

        assert countdown.days == 1
        assert countdown.hours == 0
        assert countdown.minutes == 0
        assert countdown.is_past is False

    def test_past_meeting(self):
        """Test countdown for past meeting."""
        now = datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        meeting_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        countdown = calculate_countdown(meeting_time, now)

        assert countdown.is_past is True
        assert countdown.total_seconds <= 0

    def test_hours_minutes_seconds(self):
        """Test detailed countdown breakdown."""
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        meeting_time = datetime(2024, 1, 1, 14, 30, 45, tzinfo=timezone.utc)

        countdown = calculate_countdown(meeting_time, now)

        assert countdown.days == 0
        assert countdown.hours == 2
        assert countdown.minutes == 30
        assert countdown.seconds == 45
        assert countdown.is_past is False


class TestDataFreshness:
    """Test data freshness determination."""

    def test_live_data(self):
        """Test live data (within 6 hours)."""
        release_date = datetime.now(timezone.utc) - timedelta(hours=3)
        freshness = determine_data_freshness(release_date)
        assert freshness == DataFreshness.LIVE

    def test_recent_data(self):
        """Test recent data (within 72 hours)."""
        release_date = datetime.now(timezone.utc) - timedelta(hours=24)
        freshness = determine_data_freshness(release_date)
        assert freshness == DataFreshness.RECENT

    def test_delayed_data(self):
        """Test delayed data (within 7 days)."""
        release_date = datetime.now(timezone.utc) - timedelta(days=5)
        freshness = determine_data_freshness(release_date)
        assert freshness == DataFreshness.DELAYED

    def test_historical_data(self):
        """Test historical data (within 14 days)."""
        release_date = datetime.now(timezone.utc) - timedelta(days=10)
        freshness = determine_data_freshness(release_date)
        assert freshness == DataFreshness.HISTORICAL

    def test_stale_data(self):
        """Test stale data (older than 14 days)."""
        release_date = datetime.now(timezone.utc) - timedelta(days=20)
        freshness = determine_data_freshness(release_date)
        assert freshness == DataFreshness.STALE

    def test_missing_release_date(self):
        """Test missing release date."""
        freshness = determine_data_freshness(None)
        assert freshness == DataFreshness.UNAVAILABLE


class TestPolicyRateAnalytics:
    """Test policy rate analytics."""

    def test_empty_decisions(self):
        """Test analytics with no decisions."""
        analytics = analyze_policy_rates([])
        assert analytics.total_decisions == 0
        assert analytics.hikes == 0
        assert analytics.cuts == 0

    def test_mixed_decisions(self):
        """Test analytics with mixed hike/cut/unchanged."""
        decisions = [
            {
                "previous_rate": 5.00,
                "new_rate": 5.25,
                "change_bps": 25,
                "direction": "HIKE",
                "decision_timestamp": "2024-01-01T00:00:00Z",
            },
            {
                "previous_rate": 5.25,
                "new_rate": 5.25,
                "change_bps": 0,
                "direction": "UNCHANGED",
                "decision_timestamp": "2024-02-01T00:00:00Z",
            },
            {
                "previous_rate": 5.25,
                "new_rate": 5.00,
                "change_bps": -25,
                "direction": "CUT",
                "decision_timestamp": "2024-03-01T00:00:00Z",
            },
        ]

        analytics = analyze_policy_rates(decisions)

        assert analytics.total_decisions == 3
        assert analytics.hikes == 1
        assert analytics.cuts == 1
        assert analytics.unchanged == 1
        assert analytics.avg_hike_bps == 25.0
        assert analytics.avg_cut_bps == -25.0
        assert analytics.max_hike_bps == 25
        assert analytics.max_cut_bps == -25
        assert analytics.current_rate == 5.00

    def test_volatility_calculation(self):
        """Test volatility calculation."""
        decisions = [
            {
                "previous_rate": 5.00,
                "new_rate": 5.50,
                "change_bps": 50,
                "direction": "HIKE",
                "decision_timestamp": "2024-01-01T00:00:00Z",
            },
            {
                "previous_rate": 5.50,
                "new_rate": 4.50,
                "change_bps": -100,
                "direction": "CUT",
                "decision_timestamp": "2024-02-01T00:00:00Z",
            },
        ]

        analytics = analyze_policy_rates(decisions)
        assert analytics.volatility_bps > 0


class TestMacroTrendAnalytics:
    """Test macro trend analytics."""

    def test_empty_observations(self):
        """Test analytics with no observations."""
        analytics = analyze_macro_trend([], series_id="TEST")
        assert analytics.series_id == "TEST"
        assert analytics.trend == "unknown"

    def test_increasing_trend(self):
        """Test increasing trend."""
        now = datetime.now(timezone.utc)
        observations = [
            {
                "observation_date": (now - timedelta(days=10)).isoformat(),
                "value": 100.0,
            },
            {
                "observation_date": (now - timedelta(days=5)).isoformat(),
                "value": 105.0,
            },
            {
                "observation_date": now.isoformat(),
                "value": 110.0,
            },
        ]

        analytics = analyze_macro_trend(observations, series_id="TEST")
        assert analytics.trend == "increasing"
        assert analytics.change_pct > 0

    def test_decreasing_trend(self):
        """Test decreasing trend."""
        now = datetime.now(timezone.utc)
        observations = [
            {
                "observation_date": (now - timedelta(days=10)).isoformat(),
                "value": 110.0,
            },
            {
                "observation_date": (now - timedelta(days=5)).isoformat(),
                "value": 105.0,
            },
            {
                "observation_date": now.isoformat(),
                "value": 100.0,
            },
        ]

        analytics = analyze_macro_trend(observations, series_id="TEST")
        assert analytics.trend == "decreasing"
        assert analytics.change_pct < 0

    def test_stable_trend(self):
        """Test stable trend."""
        now = datetime.now(timezone.utc)
        observations = [
            {
                "observation_date": (now - timedelta(days=10)).isoformat(),
                "value": 100.0,
            },
            {
                "observation_date": (now - timedelta(days=5)).isoformat(),
                "value": 100.1,
            },
            {
                "observation_date": now.isoformat(),
                "value": 100.0,
            },
        ]

        analytics = analyze_macro_trend(observations, series_id="TEST")
        assert analytics.trend == "stable"


@pytest_asyncio.fixture
async def client():
    """Async ASGI client — these tests await requests, so a sync TestClient
    cannot serve them. ``init_db()`` is called explicitly: the ASGI transport
    does not run the app's lifespan, so relying on startup would leave the
    schema missing (a real hidden test-order bug this fixture fixes)."""
    from httpx import ASGITransport, AsyncClient

    from app.db import init_db
    from app.main import app

    init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.asyncio
class TestMacroAPIEndpoints:
    """Test macro intelligence API endpoints."""

    async def test_list_central_banks(self, client):
        """Test listing central banks."""
        response = await client.get("/api/v1/macro/central-banks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_get_meetings(self, client):
        """Test getting upcoming meetings."""
        response = await client.get("/api/v1/macro/meetings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_get_available_series(self, client):
        """Test getting available macro series."""
        response = await client.get("/api/v1/macro/series")
        assert response.status_code == 200
        data = response.json()
        assert "series" in data
        assert isinstance(data["series"], list)

    async def test_macro_health(self, client):
        """Test macro health endpoint."""
        response = await client.get("/api/v1/macro/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
