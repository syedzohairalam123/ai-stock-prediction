"""Phase 23B — service and route tests (spec §16, §18).

Network is never touched: the service is configured with fake history/profile
fetchers, exactly the shape the real provider manager exposes. That keeps the
contract (frame + source + status) under test without depending on Yahoo.
"""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.db import init_db, session_scope
from app.providers.base import DataStatus, ProviderError
from app.market_intel.db_models import (
    CompanyMarketObservation,
    CorporateActionEvent,
    MarketCapRankHistory,
)
from app.market_intel.service import MarketIntelligenceService
from app.market_intel.service import market_intel_service as global_service


def _frame(pairs):
    index = pd.to_datetime([day for day, _ in pairs])
    closes = [close for _, close in pairs]
    frame = pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1_000] * len(closes)},
        index=index,
    )
    frame.index.name = "Date"
    return frame


SPX_ROWS = [("2026-01-02", 5000.0), ("2026-01-05", 5050.0), ("2026-01-06", 5025.0)]
SPY_ROWS = [("2026-01-02", 500.0), ("2026-01-05", 505.0), ("2026-01-06", 501.0)]


class _FakeHistory:
    def __init__(self):
        self.fail = False
        self.calls = []

    async def __call__(self, ticker, start, end, interval="1d"):
        self.calls.append(ticker)
        if self.fail:
            raise ProviderError("fake", "boom")
        rows = SPX_ROWS if ticker.startswith("^") else SPY_ROWS
        return _frame(rows), "fake-provider", DataStatus.LIVE


class _FakeProfile:
    def __init__(self, caps=None):
        self.caps = caps or {
            "AAPL": 3.0e12,
            "NVDA": 4.0e12,
            "MSFT": 3.5e12,
        }

    async def __call__(self, ticker):
        cap = self.caps.get(ticker.upper(), 1.0e11)
        return {
            "ticker": ticker.upper(),
            "source": "fake-provider",
            "marketCap": cap,
            "currentPrice": 100.0,
            "sharesOutstanding": cap / 100.0,
            "currency": "USD",
            "exchange": "NASDAQ",
            "sector": "Information Technology",
            "regularMarketTime": 1_760_000_000,
        }


class _FakeMacro:
    def __init__(self):
        self.tickers = []

    async def event_window_analysis(self, bank_id, ticker="^GSPC", lookback_decisions=4, windows=None):
        self.tickers.append(ticker)
        return {
            "status": "LIVE",
            "results": [{"decision_timestamp": "2026-01-05T00:00:00+00:00", "change_1d": 0.5}],
            "count": 1,
            "market_source": "fake-provider",
            "market_status": "LIVE",
            "history_start": "2025-11-01",
            "history_end": "2026-01-06",
        }


def _service(history=None, profile=None, macro=None):
    svc = MarketIntelligenceService()
    svc._rank_snapshot_min_seconds = 0
    svc.configure(history or _FakeHistory(), profile or _FakeProfile(), macro)
    return svc


def _cleanup():
    init_db()
    with session_scope() as db:
        db.query(CompanyMarketObservation).delete()
        db.query(MarketCapRankHistory).delete()
        db.query(CorporateActionEvent).delete()


@pytest.fixture()
def service():
    init_db()
    _cleanup()
    yield _service()
    _cleanup()


# ---------------------------------------------------------------------------
# §2–§6 — direction data through the service
# ---------------------------------------------------------------------------


class TestDirectionService:
    # pytest-asyncio strict mode: async tests carry the marker explicitly.
    pytestmark = pytest.mark.asyncio

    async def test_instrument_returns_series_with_source(self, service):
        payload = await service.get_instrument("spx")
        assert payload["source"] == "fake-provider"
        assert payload["data_status"] == "LIVE"
        assert payload["observation_count"] == 3
        assert payload["latest"]["close"] == 5025.0
        assert payload["latest"]["direction"] == "DOWN"

    async def test_spx_and_spy_requests_use_different_symbols(self, service):
        history = _FakeHistory()
        svc = _service(history=history)
        await svc.get_instrument("spx")
        await svc.get_instrument("spy")
        assert "^GSPC" in history.calls and "SPY" in history.calls

    async def test_statistics_report_period_and_sample_size(self, service):
        payload = await service.get_statistics("spx")
        stats = payload["statistics"]
        assert stats["sample_size"] == 2
        assert stats["period_start"] == "2026-01-02"
        assert stats["up_days"] == 1 and stats["down_days"] == 1

    async def test_rolling_returns_points(self, service):
        payload = await service.get_rolling("spx", window=2)
        assert payload["window"] == 2
        assert len(payload["points"]) == 3
        assert payload["points"][2]["rolling_return_pct"] is not None

    async def test_comparison_aligns_spx_and_spy_on_real_dates(self, service):
        payload = await service.get_comparison()
        assert payload["spx_source"] == "fake-provider"
        assert payload["observation_count"] == 3
        # 2026-01-06 is present in both series here.
        last = payload["aligned"][-1]
        assert last["spx_close"] == 5025.0 and last["spy_close"] == 501.0
        assert last["both_available"] is True

    async def test_dashboard_has_two_distinct_cards(self, service):
        payload = await service.get_dashboard()
        assert len(payload["cards"]) == 2
        keys = [card["instrument"]["key"] for card in payload["cards"]]
        assert keys == ["spx", "spy"]
        kinds = {card["instrument"]["kind"] for card in payload["cards"]}
        assert kinds == {"INDEX", "ETF"}

    async def test_unknown_instrument_raises(self, service):
        with pytest.raises(ValueError):
            await service.get_instrument("dow")

    async def test_provider_failure_is_unavailable_not_an_exception(self):
        svc = _service(history=_FakeHistory())
        svc._market_history.fail = True
        payload = await svc.get_instrument("spx")
        assert payload["data_status"] == "UNAVAILABLE"
        assert payload["latest"] is None
        assert payload["error"]

    async def test_unconfigured_service_degrades_honestly(self):
        svc = MarketIntelligenceService()
        payload = await svc.get_instrument("spx")
        assert payload["data_status"] == "UNAVAILABLE"
        assert "not configured" in payload["error"]
        assert svc.health()["market_data_configured"] is False


# ---------------------------------------------------------------------------
# §9–§14 — company market-cap service
# ---------------------------------------------------------------------------


class TestCompanyService:
    pytestmark = pytest.mark.asyncio

    async def test_leaderboard_ranks_from_real_observations(self, service):
        payload = await service.get_leaderboard()
        top = [row["ticker"] for row in payload["companies"][:3]]
        assert top == ["NVDA", "MSFT", "AAPL"]
        assert payload["ranked_count"] >= 3

    async def test_leaderboard_persists_observations(self, service):
        await service.get_leaderboard()
        with session_scope() as db:
            count = db.query(CompanyMarketObservation).count()
        assert count > 0

    async def test_rank_change_is_read_from_stored_history(self):
        init_db()
        _cleanup()
        first = _service(profile=_FakeProfile({"AAPL": 3.0e12, "NVDA": 4.0e12, "MSFT": 3.5e12}))
        await first.get_leaderboard()
        # Now Apple overtakes NVIDIA.
        second = _service()
        second._profile_fetcher = _FakeProfile({"AAPL": 5.0e12, "NVDA": 4.0e12, "MSFT": 3.5e12})
        payload = await second.get_leaderboard()
        apple = next(r for r in payload["companies"] if r["ticker"] == "AAPL")
        assert apple["rank"] == 1
        assert apple["previous_rank"] == 3
        assert apple["rank_change"] == 2
        _cleanup()

    async def test_unavailable_company_is_marked_not_invented(self):
        init_db()
        _cleanup()

        class _Partial(_FakeProfile):
            async def __call__(self, ticker):
                if ticker.upper() == "AAPL":
                    return {}
                return await super().__call__(ticker)

        svc = _service(profile=_Partial())
        payload = await svc.get_leaderboard()
        apple = next(r for r in payload["companies"] if r["ticker"] == "AAPL")
        assert apple["market_cap"] is None
        assert apple["rank"] is None
        assert apple["data_quality"] == "UNAVAILABLE"
        _cleanup()

    async def test_company_history_returns_stored_points(self, service):
        await service.get_leaderboard()
        payload = service.get_company_history("apple")
        assert payload["company_id"] == "apple"
        assert payload["point_count"] >= 1
        assert payload["points"][-1]["market_cap"] == 3.0e12

    async def test_company_history_unknown_company_raises(self, service):
        with pytest.raises(ValueError):
            service.get_company_history("does-not-exist")

    async def test_scenario_uses_current_company_data(self, service):
        result = await service.get_scenario("apple", 0.10)
        assert result["label"] == "HYPOTHETICAL_SCENARIO"
        assert result["reference_price"] == 100.0
        assert result["scenario_price"] == 110.0
        assert result["scenario_market_cap"] == 110.0 * (3.0e12 / 100.0)

    async def test_scenario_rejects_total_loss(self, service):
        with pytest.raises(ValueError):
            await service.get_scenario("apple", -1.0)

    async def test_corporate_action_is_idempotent_and_readable(self, service):
        first = service.record_corporate_action(
            "nvidia", "split", "2026-01-05", ratio=2.0, source="exchange-filing"
        )
        assert first["created"] is True and first["action_type"] == "SPLIT"
        again = service.record_corporate_action(
            "nvidia", "SPLIT", "2026-01-05T00:00:00Z", ratio=2.0, source="exchange-filing"
        )
        assert again["created"] is False and again["id"] == first["id"]
        listing = service.get_corporate_actions("nvidia")
        assert listing["count"] == 1
        assert listing["actions"][0]["ratio"] == 2.0

    async def test_corporate_action_validates_type(self, service):
        with pytest.raises(ValueError):
            service.record_corporate_action("nvidia", "MAGIC", "2026-01-05")


# ---------------------------------------------------------------------------
# §7 — event study reuses Phase 23A
# ---------------------------------------------------------------------------


class TestEventStudy:
    pytestmark = pytest.mark.asyncio

    async def test_event_study_uses_index_symbol_for_spx(self):
        macro = _FakeMacro()
        svc = _service(macro=macro)
        payload = await svc.get_event_study("FED", instrument_key="spx")
        assert macro.tickers == ["^GSPC"]
        assert payload["analysis_type"] == "OBSERVATIONAL"
        assert payload["count"] == 1
        assert payload["return_formula"]

    async def test_event_study_uses_etf_symbol_for_spy(self):
        macro = _FakeMacro()
        svc = _service(macro=macro)
        await svc.get_event_study("FED", instrument_key="spy")
        assert macro.tickers == ["SPY"]

    async def test_event_study_without_macro_service_is_unavailable(self):
        svc = _service(macro=None)
        payload = await svc.get_event_study("FED")
        assert payload["status"] == "UNAVAILABLE"
        assert payload["results"] == []


# ---------------------------------------------------------------------------
# §16 — HTTP routes
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    init_db()
    _cleanup()
    from app.main import app

    # Re-bind the global service to the fakes AFTER app.main imported and bound
    # the real provider manager (which happens at module import).
    global_service.configure(_FakeHistory(), _FakeProfile(), _FakeMacro())
    global_service._rank_snapshot_min_seconds = 0
    yield TestClient(app)
    _cleanup()


class TestRoutes:
    def test_instruments_route(self, client):
        res = client.get("/api/v1/market-intel/instruments")
        assert res.status_code == 200
        keys = [i["key"] for i in res.json()["instruments"]]
        assert keys == ["spx", "spy"]

    def test_health_route(self, client):
        res = client.get("/api/v1/market-intel/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_dashboard_route(self, client):
        res = client.get("/api/v1/market-intel/dashboard")
        assert res.status_code == 200
        assert len(res.json()["cards"]) == 2

    def test_dashboard_not_shadowed_by_instrument_route(self, client):
        res = client.get("/api/v1/market-intel/dashboard")
        assert res.status_code == 200
        assert "cards" in res.json()

    def test_spx_quote_route(self, client):
        res = client.get("/api/v1/market-intel/spx/quote")
        assert res.status_code == 200
        body = res.json()
        assert body["instrument"]["kind"] == "INDEX"
        assert body["latest"]["close"] == 5025.0

    def test_spy_quote_route_is_the_etf(self, client):
        res = client.get("/api/v1/market-intel/spy/quote")
        assert res.status_code == 200
        assert res.json()["instrument"]["kind"] == "ETF"

    def test_unknown_instrument_is_404(self, client):
        res = client.get("/api/v1/market-intel/dow/quote")
        # "dow" is not an instrument, but it is also not a declared literal, so
        # it must resolve to the instrument route and 404 cleanly.
        assert res.status_code == 404

    def test_statistics_route(self, client):
        res = client.get("/api/v1/market-intel/spx/statistics")
        assert res.status_code == 200
        assert res.json()["statistics"]["sample_size"] == 2

    def test_rolling_route_validates_window(self, client):
        assert client.get("/api/v1/market-intel/spx/rolling?window=1").status_code == 422
        assert client.get("/api/v1/market-intel/spx/rolling?window=20").status_code == 200

    def test_comparison_route(self, client):
        res = client.get("/api/v1/market-intel/comparison")
        assert res.status_code == 200
        assert res.json()["observation_count"] == 3

    def test_leaderboard_route(self, client):
        res = client.get("/api/v1/market-intel/leaderboard?refresh=false")
        assert res.status_code == 200
        assert res.json()["companies"][0]["ticker"] == "NVDA"

    def test_company_history_route_404_for_unknown(self, client):
        res = client.get("/api/v1/market-intel/company/nope/history")
        assert res.status_code == 404

    def test_scenario_route(self, client):
        res = client.get("/api/v1/market-intel/company/apple/scenario?return_pct=10")
        assert res.status_code == 200
        body = res.json()
        assert body["scenario_price"] == 110.0
        assert body["label"] == "HYPOTHETICAL_SCENARIO"
        assert body["scenario_return_pct"] == 10.0

    def test_scenario_route_rejects_out_of_range(self, client):
        assert client.get("/api/v1/market-intel/company/apple/scenario?return_pct=-200").status_code == 422

    def test_corporate_action_round_trip(self, client):
        post = client.post(
            "/api/v1/market-intel/corporate-actions",
            json={"company_id": "apple", "action_type": "buyback", "effective_date": "2026-02-01",
                  "source": "sec-filing", "notes": "test"},
        )
        assert post.status_code == 200
        assert post.json()["action_type"] == "BUYBACK"
        get = client.get("/api/v1/market-intel/company/apple/corporate-actions")
        assert get.status_code == 200
        assert get.json()["count"] == 1

    def test_corporate_action_rejects_bad_type(self, client):
        post = client.post(
            "/api/v1/market-intel/corporate-actions",
            json={"company_id": "apple", "action_type": "MAGIC", "effective_date": "2026-02-01"},
        )
        assert post.status_code == 400

    def test_event_study_route(self, client):
        res = client.get("/api/v1/market-intel/events/fed?instrument=spx")
        assert res.status_code == 200
        assert res.json()["analysis_type"] == "OBSERVATIONAL"
