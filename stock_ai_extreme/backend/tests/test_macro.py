"""Tests for macro.py — pure computation plus the source-selection logic.

FRED network calls are mocked at the requests seam; yfinance-proxy source
is tested with a stub manager, same as the rest of this suite.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.macro import (
    MACRO_INDICATORS,
    build_fred_indicator,
    build_proxy_indicator,
    cpi_series_to_yoy,
    classify_yield_curve,
    macro_report,
    regime_from_macro,
)


def _fake_frame(n_days: int = 200, base: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    closes = [base + (i % 7) for i in range(n_days)]
    return pd.DataFrame({
        "Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
        "Close": closes, "Volume": [1_000_000] * n_days,
    }, index=idx)


class StubManager:
    """Mimics MarketDataManager.history() enough for proxy indicators."""

    def __init__(self, frame=None, fail_symbols: set[str] | None = None):
        self.frame = frame if frame is not None else _fake_frame()
        self.fail_symbols = fail_symbols or set()
        self.calls: list[str] = []

    async def history(self, ticker, start, end, interval="1d"):
        self.calls.append(ticker)
        if ticker in self.fail_symbols:
            raise ValueError(f"provider down for {ticker}")
        return self.frame.copy(), "yfinance", "LIVE"


def test_cpi_series_to_yoy_matches_fred_definition():
    idx = pd.date_range("2024-01-01", periods=14, freq="MS")
    cpi = pd.Series([100.0 * (1.03 ** (i / 12)) for i in range(14)], index=idx)
    yoy = cpi_series_to_yoy(cpi)
    assert len(yoy) == 2
    assert yoy.iloc[0] == pytest.approx(3.0, abs=0.01)


def test_classify_yield_curve_all_states():
    assert classify_yield_curve(-0.3)["status"] == "inverted"
    assert classify_yield_curve(0.2)["status"] == "flat"
    assert classify_yield_curve(1.4)["status"] == "normal"
    assert classify_yield_curve(None)["status"] == "unavailable"


def test_regime_from_macro_risk_off_when_restrictive():
    rows = [
        {"key": "gdp", "latest_value": 1.5},
        {"key": "unemployment", "latest_value": 4.0},
        {"key": "cpi_yoy", "latest_value": 5.2},
        {"key": "fed_funds", "latest_value": 5.3},
    ]
    regime = regime_from_macro(rows)
    assert regime["growth"] == "expanding"
    assert regime["inflation"] == "high"
    assert regime["policy"] == "restrictive"
    assert regime["tone"] == "risk-off"


def test_regime_from_macro_handles_missing_data():
    regime = regime_from_macro([])
    assert regime["growth"] == "unclear"
    assert regime["tone"] == "mixed"


def test_fred_indicator_parses_observations_and_skips_missing():
    ind = MACRO_INDICATORS["yield_10y"]
    payload = {"observations": [
        {"date": "2026-09-01", "value": "4.21"},
        {"date": "2026-09-02", "value": "."},  # FRED's missing marker
        {"date": "2026-09-03", "value": "4.25"},
    ]}
    with patch("app.macro._fred_observation_payload", return_value=payload):
        row = build_fred_indicator(ind, api_key="fake", history=365)
    assert row["source"] == "fred"
    assert row["latest_value"] == 4.25
    assert row["previous_value"] == 4.21
    assert row["expected"] is None  # never invented


def test_fred_indicator_rejects_series_without_mapping():
    ind = MACRO_INDICATORS["gold_price"]  # proxy-only
    with pytest.raises(ValueError, match="no FRED series"):
        build_fred_indicator(ind, api_key="fake", history=365)


def test_proxy_indicator_uses_manager_and_reports_change():
    ind = MACRO_INDICATORS["vix"]
    frame = _fake_frame(base=20.0)  # closes = 20+(i%7) -> last close = 20+(199%7) = 23.0
    manager = StubManager(frame)
    row = __import__("asyncio").run(build_proxy_indicator(ind, manager, 365))
    assert row["source"] == "yfinance-proxy"
    assert row["proxy_symbol"] == "^VIX"
    assert row["latest_value"] == pytest.approx(23.0, abs=0.1)
    assert row["change"] is not None


def test_macro_report_yfinance_source_degrades_per_indicator():
    manager = StubManager(fail_symbols={"^TNX", "GC=F"})
    report = __import__("asyncio").run(
        macro_report(manager, source="yfinance", history=365)
    )
    # Several indicators succeed, the failed ones land in errors honestly
    assert report["status"] == "OK"
    assert report["source"] == "yfinance"
    assert len(report["indicators"]) >= 3
    # errors keys are indicator keys; the real reason (with the symbol) is in the values
    assert any("^TNX" in v for v in report["errors"].values())
    assert any("GC=F" in v for v in report["errors"].values())
    assert report["yield_curve"]["status"] in ("unavailable", "normal", "flat", "inverted")


def test_macro_report_fred_source_requires_key():
    manager = StubManager()
    report = __import__("asyncio").run(macro_report(manager, source="fred", fred_api_key=None))
    assert report["status"] == "UNAVAILABLE"
    assert report["indicators"] == []


def test_macro_report_fred_source_with_key_and_mocked_network():
    payload_tpl = {"observations": [
        {"date": "2026-09-01", "value": "1.0"},
        {"date": "2026-09-02", "value": "1.1"},
    ]}
    with patch("app.macro._fred_observation_payload", return_value=payload_tpl):
        report = __import__("asyncio").run(
            macro_report(_fake_manager(), source="fred", fred_api_key="fake")
        )
    assert report["status"] == "OK"
    assert all(r["source"] == "fred" for r in report["indicators"])


def _fake_manager():
    m = StubManager()
    # Only proxy-capable indicators would call this; fred path shouldn't.
    return m


def test_macro_report_rejects_unknown_source():
    manager = StubManager()
    with pytest.raises(ValueError, match="Unknown source"):
        __import__("asyncio").run(macro_report(manager, source="not-a-source"))


def test_macro_report_calendar_never_fabricates_expected():
    manager = StubManager()
    report = __import__("asyncio").run(macro_report(manager, source="yfinance"))
    for event in report["calendar"]:
        assert event["expected"] is None
        assert event["surprise"] is None
