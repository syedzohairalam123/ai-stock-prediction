"""Phase 23B additions — engine facade, numpy analytics, mappings, snapshots.

These tests lock down the pieces added on top of the original Phase 23B module:
the spec §3 ``MarketDirectionEngine`` class, the spec §17 NumPy/SciPy analytics,
the spec §15 ``company_security_mappings`` / ``market_cap_snapshots`` tables,
the spec §16 pagination, and the provider ``market_cap`` fallback that makes a
reported (VERIFIED) capitalisation actually reachable in production.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.db import init_db, session_scope
from app.providers.base import DataStatus, ProviderError
from app.market_intel import analytics as analytics_mod
from app.market_intel.companies import (
    COMPANY_UNIVERSE,
    CompanyDefinition,
    METHOD_PROVIDER,
    QUALITY_VERIFIED,
    build_company_market_data,
)
from app.market_intel.db_models import (
    CompanyMarketObservation,
    CompanySecurityMapping,
    CorporateActionEvent,
    MarketCapRankHistory,
    MarketCapSnapshot,
    SharesOutstandingObservation,
)
from app.market_intel.direction import (
    INSTRUMENTS,
    MarketDirectionEngine,
)
from app.market_intel.facades import (
    CompanyDataService,
    MarketCapService,
    MarketDirectionService,
)
from app.market_intel.service import MarketIntelligenceService
from app.market_intel.service import market_intel_service as global_service

ROWS = [
    {"date": "2026-01-02", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000},
    {"date": "2026-01-05", "open": 105.0, "high": 105.0, "low": 105.0, "close": 105.0, "volume": 1000},
    {"date": "2026-01-06", "open": 102.0, "high": 102.0, "low": 102.0, "close": 102.25, "volume": 1000},
    {"date": "2026-01-07", "open": 101.0, "high": 101.0, "low": 101.0, "close": 101.0, "volume": 1000},
]


# ---------------------------------------------------------------------------
# §3 — MarketDirectionEngine class
# ---------------------------------------------------------------------------


class TestMarketDirectionEngine:
    def test_engine_binds_an_instrument(self):
        engine = MarketDirectionEngine("spx")
        assert engine.instrument.key == "spx"
        assert engine.as_dict()["return_formula"] == "(currentClose / previousTradingClose) - 1"

    def test_engine_rejects_unknown_instrument(self):
        with pytest.raises(ValueError):
            MarketDirectionEngine("dow")

    def test_engine_build_matches_free_function(self):
        engine = MarketDirectionEngine("spx", source="test")
        observations = engine.build(ROWS)
        assert [o.trading_date.isoformat() for o in observations] == [
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        ]
        assert observations[0].direction is None          # no previous session
        assert observations[3].previous_close == 102.25   # previous trading session
        assert observations[3].direction == "DOWN"

    def test_engine_daily_return_matches_the_rule(self):
        engine = MarketDirectionEngine("spx")
        result = engine.daily_return(105.0, 100.0)
        assert round(result["return_pct"], 6) == 0.05
        assert result["direction"] == "UP"
        assert engine.daily_return(100.0, 0.0)["direction"] is None

    def test_engine_classify_uses_precision(self):
        engine = MarketDirectionEngine("spy")
        assert engine.classify(0.004) == "FLAT"
        assert engine.classify(0.02) == "UP"
        assert engine.classify(-0.02) == "DOWN"

    def test_engine_statistics_and_rolling(self):
        engine = MarketDirectionEngine("spx")
        observations = engine.build(ROWS)
        stats = engine.statistics(observations)
        assert stats.sample_size == 3
        points = engine.rolling(observations, window=2)
        assert points[-1].rolling_return_pct is not None

    def test_engine_align_keeps_missing_sessions_null(self):
        spx = MarketDirectionEngine("spx").build(ROWS[:2])
        spy_engine = MarketDirectionEngine("spy")
        spy = spy_engine.build(
            [
                {"date": "2026-01-02", "close": 500.0},
                {"date": "2026-01-06", "close": 505.0},
            ]
        )
        aligned = MarketDirectionEngine("spx").align(spx, spy, "spy")
        by_date = {row["trading_date"]: row for row in aligned}
        assert by_date["2026-01-05"]["spy_close"] is None
        assert by_date["2026-01-06"]["spx_close"] is None


# ---------------------------------------------------------------------------
# §17 — numpy/scipy analytics
# ---------------------------------------------------------------------------


class TestAnalytics:
    def test_simple_returns(self):
        returns = analytics_mod.simple_returns([100.0, 105.0, 102.25])
        assert np.allclose(returns, [0.05, 102.25 / 105.0 - 1.0])

    def test_simple_returns_skips_nonpositive_prior(self):
        returns = analytics_mod.simple_returns([0.0, 100.0])
        assert returns.size == 0

    def test_annualized_volatility_needs_two_points(self):
        assert analytics_mod.annualized_volatility([0.01]) is None
        value = analytics_mod.annualized_volatility([0.01, -0.01, 0.02])
        assert value is not None and value > 0

    def test_max_drawdown(self):
        assert analytics_mod.max_drawdown([100.0, 120.0, 90.0, 110.0]) == -25.0
        assert analytics_mod.max_drawdown([100.0]) is None

    def test_pearson_correlation(self):
        assert analytics_mod.pearson_correlation([1, 2, 3], [2, 4, 6]) == 1.0
        assert analytics_mod.pearson_correlation([1, 2, 3], [3, 2, 1]) == -1.0
        assert analytics_mod.pearson_correlation([1, 2, 3], [1, 2]) is None

    def test_spearman_rank_correlation(self):
        assert analytics_mod.spearman_rank_correlation([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
        assert analytics_mod.spearman_rank_correlation([1, 2], [1, 2]) is None

    def test_value_at_risk_is_negative_quantile(self):
        var = analytics_mod.value_at_risk([0.01, -0.02, 0.03, -0.05, 0.0, -0.01], 0.95)
        assert var is not None and var < 0

    def test_rolling_mean_std_marks_warmup_nan(self):
        means, stds = analytics_mod.rolling_mean_std([0.01, 0.02, 0.03], window=2)
        assert len(means) == 3
        assert np.isnan(stds[0])       # only one observation so far
        assert not np.isnan(stds[1])


# ---------------------------------------------------------------------------
# §10 — provider reported cap reachable in production (snake_case key)
# ---------------------------------------------------------------------------


class TestProviderCapKey:
    def test_yfinance_adapter_market_cap_key_is_used(self):
        definition = CompanyDefinition("apple", "Apple Inc.", "AAPL", "Information Technology")
        record = build_company_market_data(
            definition,
            {
                "market_cap": 3_000_000_000_000,   # this project's adapter key
                "currentPrice": 200.0,
                "sharesOutstanding": 15_000_000_000,
                "regularMarketTime": int(datetime.now(timezone.utc).timestamp()),
                "source": "yfinance",
            },
            source="yfinance",
        )
        assert record.market_cap == 3_000_000_000_000
        assert record.market_cap_methodology == METHOD_PROVIDER
        assert record.data_quality == QUALITY_VERIFIED


# ---------------------------------------------------------------------------
# Service fixtures for mappings / snapshots / pagination / correlation
# ---------------------------------------------------------------------------


def _frame(pairs):
    index = pd.to_datetime([day for day, _ in pairs])
    closes = [close for _, close in pairs]
    frame = pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1_000] * len(closes)},
        index=index,
    )
    frame.index.name = "Date"
    return frame


SPX_ROWS = [("2026-01-02", 5000.0), ("2026-01-05", 5050.0), ("2026-01-06", 5025.0), ("2026-01-07", 5100.0)]
SPY_ROWS = [("2026-01-02", 500.0), ("2026-01-05", 505.0), ("2026-01-06", 501.0), ("2026-01-07", 509.0)]


class _FakeHistory:
    async def __call__(self, ticker, start, end, interval="1d"):
        rows = SPX_ROWS if ticker.startswith("^") else SPY_ROWS
        return _frame(rows), "fake-provider", DataStatus.LIVE


class _FakeProfile:
    async def __call__(self, ticker):
        cap = {"AAPL": 3.0e12, "NVDA": 4.0e12, "MSFT": 3.5e12}.get(ticker.upper(), 1.0e11)
        return {
            "ticker": ticker.upper(),
            "source": "fake-provider",
            "market_cap": cap,
            "currentPrice": 100.0,
            "sharesOutstanding": cap / 100.0,
            "currency": "USD",
            "exchange": "NASDAQ",
            "sector": "Information Technology",
            "regularMarketTime": int(datetime.now(timezone.utc).timestamp()),
        }


class _FakeSplits:
    async def __call__(self, ticker):
        if ticker.upper() == "NVDA":
            return (
                [{"date": "2024-06-10", "ratio": 10.0}, {"date": "2021-07-20", "ratio": 4.0}],
                "fake-splits",
                DataStatus.LIVE,
            )
        return [], "fake-splits", DataStatus.LIVE


def _cleanup():
    init_db()
    with session_scope() as db:
        db.query(CompanyMarketObservation).delete()
        db.query(CompanySecurityMapping).delete()
        db.query(MarketCapSnapshot).delete()
        db.query(MarketCapRankHistory).delete()
        db.query(CorporateActionEvent).delete()
        db.query(SharesOutstandingObservation).delete()


@pytest.fixture()
def service():
    init_db()
    _cleanup()
    svc = MarketIntelligenceService()
    svc._rank_snapshot_min_seconds = 0
    svc.configure(_FakeHistory(), _FakeProfile(), None, _FakeSplits())
    yield svc
    _cleanup()


class TestMappingsAndSnapshots:
    pytestmark = pytest.mark.asyncio

    async def test_leaderboard_populates_security_mappings(self, service):
        await service.get_leaderboard()
        with session_scope() as db:
            count = db.query(CompanySecurityMapping).count()
        # At least one mapping row per company in the watch universe.
        assert count >= len(COMPANY_UNIVERSE)
        payload = service.get_security_mappings("alphabet")
        tickers = {row["ticker"] for row in payload["mappings"]}
        assert tickers == {"GOOGL", "GOOG"}
        primary = next(row for row in payload["mappings"] if row["is_primary"])
        assert primary["ticker"] == "GOOGL"
        assert primary["security_type"] == "CLASS_A"

    async def test_leaderboard_writes_market_cap_snapshots(self, service):
        await service.get_leaderboard()
        payload = service.get_market_cap_snapshots("apple")
        assert payload["count"] >= 1
        snapshot = payload["snapshots"][-1]
        assert snapshot["market_cap"] == 3.0e12
        assert snapshot["market_cap_methodology"] == METHOD_PROVIDER

    async def test_security_mappings_unknown_company_raises(self, service):
        with pytest.raises(ValueError):
            service.get_security_mappings("does-not-exist")


class TestPaginationAndCorrelation:
    pytestmark = pytest.mark.asyncio

    async def test_instrument_offset_skips_newest(self, service):
        page0 = await service.get_instrument("spx", limit=2)
        page1 = await service.get_instrument("spx", limit=2, offset=2)
        assert page0["page"]["returned"] == 2
        assert page1["page"]["returned"] == 2
        # The newest two dates must not appear on the second page.
        dates0 = {row["trading_date"] for row in page0["series"]}
        dates1 = {row["trading_date"] for row in page1["series"]}
        assert dates0.isdisjoint(dates1)

    async def test_comparison_includes_numpy_analytics(self, service):
        payload = await service.get_comparison()
        # 4 real sessions, but the first has no prior close on either side, so
        # exactly 3 sessions carry a return in both series.
        assert payload["analytics"]["overlapping_sessions"] == 3
        assert payload["analytics"]["return_correlation"] is not None
        assert payload["analytics"]["spx_annualized_volatility_pct"] is not None

    async def test_health_reports_new_surface(self, service):
        health = service.health()
        assert "market_cap_snapshots" in health["tables"]
        assert "MarketScenarioService" in health["services"]
        assert health["analytics_backend"] == "numpy+scipy"


# ---------------------------------------------------------------------------
# Route surface for the additions
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    init_db()
    _cleanup()
    from app.main import app

    global_service.configure(_FakeHistory(), _FakeProfile(), None, _FakeSplits())
    global_service._rank_snapshot_min_seconds = 0
    # _cleanup() wipes the mapping rows between tests, so the singleton's
    # "registry already upserted" flag must be reset too (a fresh instance per
    # test is used elsewhere; the route tests share the process-wide one).
    global_service._company_registry_ready = False
    yield TestClient(app)
    _cleanup()
    global_service._company_registry_ready = False


class TestAddedRoutes:
    def test_companies_route(self, client):
        res = client.get("/api/v1/market-intel/companies")
        assert res.status_code == 200
        assert res.json()["count"] >= 1

    def test_company_mappings_route(self, client):
        res = client.get("/api/v1/market-intel/company/alphabet/mappings")
        assert res.status_code == 200
        assert {row["ticker"] for row in res.json()["mappings"]} == {"GOOGL", "GOOG"}

    def test_company_snapshots_route(self, client):
        client.get("/api/v1/market-intel/leaderboard?refresh=true")
        res = client.get("/api/v1/market-intel/company/apple/snapshots")
        assert res.status_code == 200
        assert res.json()["count"] >= 1

    def test_company_snapshots_404_for_unknown(self, client):
        assert client.get("/api/v1/market-intel/company/nope/snapshots").status_code == 404

    def test_history_offset_validates_and_pages(self, client):
        assert client.get("/api/v1/market-intel/spx/history?offset=-1").status_code == 422
        res = client.get("/api/v1/market-intel/spx/history?limit=2&offset=2")
        assert res.status_code == 200
        assert res.json()["page"]["offset"] == 2

    def test_company_history_accepts_offset(self, client):
        client.get("/api/v1/market-intel/leaderboard?refresh=true")
        res = client.get("/api/v1/market-intel/company/apple/history?limit=5&offset=0")
        assert res.status_code == 200
        assert res.json()["page"]["offset"] == 0


# ---------------------------------------------------------------------------
# §10 — provider-reported splits ingested as real corporate actions
# ---------------------------------------------------------------------------


class TestSplitIngestion:
    pytestmark = pytest.mark.asyncio

    async def test_refresh_records_provider_splits_idempotently(self, service):
        first = await service.refresh_corporate_actions("nvidia")
        assert first["status"] == "LIVE"
        assert first["source"] == "fake-splits"
        assert first["splits_found"] == 2
        assert first["recorded"] == 2
        # A second refresh must not duplicate history.
        second = await service.refresh_corporate_actions("nvidia")
        assert second["recorded"] == 0
        listing = service.get_corporate_actions("nvidia")
        assert listing["count"] == 2
        ratios = sorted(a["ratio"] for a in listing["actions"])
        assert ratios == [4.0, 10.0]

    async def test_refresh_unknown_company_raises(self, service):
        with pytest.raises(ValueError):
            await service.refresh_corporate_actions("does-not-exist")

    async def test_refresh_without_splits_source_is_unavailable(self):
        init_db()
        _cleanup()
        svc = MarketIntelligenceService()
        svc.configure(_FakeHistory(), _FakeProfile(), None)  # no splits fetcher
        result = await svc.refresh_corporate_actions("nvidia")
        assert result["status"] == "UNAVAILABLE"
        assert result["recorded"] == 0


# ---------------------------------------------------------------------------
# §15 — explicit share-count observations + cross-company rank history
# ---------------------------------------------------------------------------


class TestSharesAndRankHistory:
    pytestmark = pytest.mark.asyncio

    async def test_leaderboard_writes_share_count_observations(self, service):
        await service.get_leaderboard()
        payload = service.get_shares_outstanding("apple")
        assert payload["count"] >= 1
        assert payload["observations"][-1]["shares_outstanding"] == 3.0e12 / 100.0
        assert payload["observations"][-1]["source"]

    async def test_shares_unknown_company_raises(self, service):
        with pytest.raises(ValueError):
            service.get_shares_outstanding("nope")

    async def test_rank_history_groups_snapshots_by_ticker(self, service):
        await service.get_leaderboard()
        payload = service.get_rank_history()
        assert payload["observation_count"] >= 1
        by_ticker = {entry["ticker"]: entry for entry in payload["series"]}
        assert "NVDA" in by_ticker
        assert by_ticker["NVDA"]["points"][-1]["rank"] == 1


# ---------------------------------------------------------------------------
# §7 — market-session metadata on the event-window analysis
# ---------------------------------------------------------------------------


class TestEventSessionMetadata:
    def test_analyze_event_window_records_the_sessions(self):
        from datetime import timedelta

        from app.macro_intelligence.analytics import analyze_event_window

        start = date(2026, 1, 1)
        # 30 consecutive weekday sessions around the decision date.
        market_data = [
            {"date": (start + timedelta(days=i)).isoformat(), "close": 100.0 + i}
            for i in range(0, 30)
        ]
        decision = datetime(2026, 1, 11)  # tz-naive, matching a parsed session date
        result = analyze_event_window(market_data, decision, windows=[1, 5])
        assert result.decision_session == "2026-01-11"
        assert result.pre_session == "2026-01-10"
        assert result.window_end_sessions["window_1d"] == "2026-01-12"
        assert result.window_end_sessions["window_5d"] == "2026-01-16"


class TestAdditionalRoutes:
    def test_rank_history_route(self, client):
        client.get("/api/v1/market-intel/leaderboard?refresh=true")
        res = client.get("/api/v1/market-intel/rank-history?limit=100")
        assert res.status_code == 200
        assert res.json()["observation_count"] >= 1

    def test_company_shares_route(self, client):
        client.get("/api/v1/market-intel/leaderboard?refresh=true")
        res = client.get("/api/v1/market-intel/company/apple/shares")
        assert res.status_code == 200
        assert res.json()["count"] >= 1

    def test_company_shares_404_for_unknown(self, client):
        assert client.get("/api/v1/market-intel/company/nope/shares").status_code == 404

    def test_refresh_corporate_actions_route(self, client):
        res = client.post("/api/v1/market-intel/corporate-actions/refresh/nvidia")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "LIVE"
        assert body["recorded"] == 2

    def test_refresh_corporate_actions_404_for_unknown(self, client):
        assert client.post("/api/v1/market-intel/corporate-actions/refresh/nope").status_code == 404
