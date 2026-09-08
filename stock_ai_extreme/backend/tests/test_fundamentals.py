"""Tests for fundamentals.py — pure math, no network needed."""
from app.fundamentals import (
    analyst_view,
    balance_sheet_health,
    build_fundamentals,
    dividend_info,
    profitability_health,
    valuation_ratios,
)

FAKE_INFO = {
    "trailingEps": 6.2,
    "forwardEps": 7.0,
    "bookValue": 55.0,
    "revenuePerShare": 90.0,
    "trailingPegRatio": 1.4,
    "marketCap": 2_900_000_000_000,
    "enterpriseValue": 2_950_000_000_000,
    "grossMargins": 0.46,
    "operatingMargins": 0.30,
    "profitMargins": 0.26,
    "returnOnEquity": 0.55,
    "returnOnAssets": 0.28,
    "totalCash": 70_000_000_000,
    "totalDebt": 100_000_000_000,
    "currentRatio": 0.99,
    "debtToEquity": 145.0,
    "dividendRate": 0.96,
    "dividendYield": 0.0055,  # fraction form — should normalize to 0.55%
    "payoutRatio": 0.15,
    "fiveYearAvgDividendYield": 0.65,
    "recommendationMean": 1.8,
    "recommendationKey": "buy",
    "numberOfAnalystOpinions": 42,
    "targetMeanPrice": 230.0,
    "targetHighPrice": 260.0,
    "targetLowPrice": 180.0,
    "fullTimeEmployees": 161_000,
    "sector": "Technology",
}


def test_valuation_ratios_compute_from_real_inputs():
    v = valuation_ratios(FAKE_INFO, price=200.0)
    assert v["trailing_pe"] == round(200.0 / 6.2, 4)
    assert v["forward_pe"] == round(200.0 / 7.0, 4)
    assert v["price_to_book"] == round(200.0 / 55.0, 4)
    assert v["market_cap"] == 2_900_000_000_000


def test_valuation_ratios_none_when_inputs_missing():
    v = valuation_ratios({}, price=100.0)
    assert v["trailing_pe"] is None  # never a fake 0
    assert v["price_to_book"] is None


def test_profitability_normalizes_fractions_to_percent():
    p = profitability_health(FAKE_INFO)
    assert p["profit_margin_pct"] == 26.0
    assert p["return_on_equity_pct"] == 55.0
    assert p["grade"] == "strong"


def test_profitability_grade_weak_on_negative():
    p = profitability_health({"returnOnEquity": -0.1, "profitMargins": -0.05})
    assert p["grade"] == "weak"


def test_balance_sheet_leverage_and_net_cash():
    b = balance_sheet_health(FAKE_INFO)
    assert b["net_cash"] == 70_000_000_000 - 100_000_000_000
    assert b["leverage"] == "moderate"


def test_dividend_yield_normalizes_fraction_form():
    d = dividend_info(FAKE_INFO)
    assert d["dividend_yield_pct"] == 0.55  # 0.0055 fraction -> 0.55%
    assert d["payout_ratio_pct"] == 15.0


def test_dividend_handles_missing_fields():
    d = dividend_info({})
    assert d["dividend_rate"] is None
    assert d["dividend_yield_pct"] is None


def test_analyst_upside_requires_real_price():
    a = analyst_view(FAKE_INFO)
    assert a["target_upside_pct"] is None
    full = build_fundamentals(FAKE_INFO, price=200.0)
    assert full["analyst"]["target_upside_pct"] == round((230.0 - 200.0) / 200.0 * 100, 4)


def test_build_fundamentals_price_context_from_history():
    import pandas as pd
    from datetime import date
    idx = pd.date_range(end=date.today(), periods=260, freq="B")
    closes = pd.DataFrame({"Close": [100 + i * 0.1 for i in range(260)]}, index=idx)
    full = build_fundamentals(FAKE_INFO, price=200.0, history_frame=closes)
    assert full["price_context"]["position_52w_pct"] == 100.0  # steadily rising -> at the high
    assert full["price_context"]["high_52w"] == round(100 + 259 * 0.1, 4)
    assert full["sector"] == "Technology"
    assert "not investment advice" in full["disclaimer"]
