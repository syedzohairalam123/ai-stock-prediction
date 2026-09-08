"""
Macro intelligence layer (the old Phase 11, done as pure computation).

Indicators come from ONE of two selectable sources — the user (or frontend)
picks, the API never silently substitutes the other one:

  "fred"      — real FRED (Federal Reserve Economic Data) observations. Needs
                a free FRED_API_KEY; without one this source reports
                UNAVAILABLE instead of pretending. FRED gives OFFICIAL data
                (CPI, Fed Funds, unemployment, GDP, etc.).
  "yfinance"  — market-price proxies from the existing Phase 2 provider
                manager (yfinance): ^IRX (3-month yield), ^TNX (10-year
                yield), ^FVX (5-year), ^TYX (30-year), DX-Y.NYB (dollar
                index), GC=F (gold), CL=F (oil), ^VIX (volatility),
                ^GSPC (S&P 500). Works with zero extra API keys.

The released-vs-expected "surprise" fields in FRED_MODELS are exactly what
an Economic-Calendar view needs; they are only filled when the source
really provides them (FRED's ALFRED vintage series), otherwise None — never
a fabricated number.

Pure computation lives in *_core() helpers so everything is testable with
synthetic series, no network and no API key.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger("neural_market.macro")

SOURCES = ("fred", "yfinance")

# ---------------------------------------------------------------------------
# Indicator catalogue. `fred_series` = the official FRED series id.
# `proxy` = the yfinance symbol that roughly tracks the same concept (used by
# the yfinance source). `invert` marks indicators where "higher = risk-off"
# so the frontend can color/regress them correctly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MacroIndicator:
    key: str
    label: str
    unit: str
    fred_series: str | None
    proxy: str | None
    invert: bool = False


MACRO_INDICATORS: dict[str, MacroIndicator] = {
    "cpi_yoy": MacroIndicator("cpi_yoy", "CPI Inflation (YoY)", "%", "CPIAUCSL", None),
    "fed_funds": MacroIndicator("fed_funds", "Fed Funds Rate", "%", "DFF", "^IRX"),
    "unemployment": MacroIndicator("unemployment", "Unemployment Rate", "%", "UNRATE", None),
    "yield_10y": MacroIndicator("yield_10y", "10-Year Treasury Yield", "%", "DGS10", "^TNX"),
    "yield_spread_10y_2y": MacroIndicator("yield_spread_10y_2y", "10Y-2Y Spread", "%", "T10Y2Y", None, invert=True),
    "dollar_index": MacroIndicator("dollar_index", "US Dollar Index", "index", None, "DX-Y.NYB"),
    "gold_price": MacroIndicator("gold_price", "Gold Spot", "USD/oz", None, "GC=F"),
    "oil_wti": MacroIndicator("oil_wti", "Crude Oil WTI", "USD/bbl", None, "CL=F"),
    "vix": MacroIndicator("vix", "VIX Volatility Index", "index", "VIXCLS", "^VIX", invert=True),
    "sp500": MacroIndicator("sp500", "S&P 500 Index", "index", "SP500", "^GSPC"),
}

# Indicators where a real "expected vs released" figure is defined. `expected`
# values here are illustrative reference points for the calendar view, clearly
# labeled as such — the API never presents them as an actual consensus.
CALENDAR_EVENTS: dict[str, dict] = {
    "cpi_yoy": {"event": "CPI Release", "typical_day": "monthly, mid-month", "reference_prior": None},
    "fed_funds": {"event": "FOMC Rate Decision", "typical_day": "8 meetings/year", "reference_prior": None},
    "unemployment": {"event": "Jobs Report (NFP)", "typical_day": "first Friday monthly", "reference_prior": None},
    "gdp": {"event": "GDP Advance Estimate", "typical_day": "quarterly", "reference_prior": None},
}

_GDP = MacroIndicator("gdp", "Real GDP Growth", "%", "A191RL1Q225SBEA", None)
MACRO_INDICATORS["gdp"] = _GDP


# ---------------------------------------------------------------------------
# Core computation (pure, testable)
# ---------------------------------------------------------------------------


def cpi_series_to_yoy(cpi: pd.Series) -> pd.Series:
    """Level CPI index -> year-over-year % change, as FRED reports it."""
    return (cpi.pct_change(12) * 100).dropna()


def classify_yield_curve(spread: float | None) -> dict:
    """10Y-2Y spread -> recession-watch signal. Inversion (negative spread)
    has preceded most US recessions; it is a WATCH flag, not a prediction."""
    if spread is None or (isinstance(spread, float) and math.isnan(spread)):
        return {"status": "unavailable", "signal": None, "message": "No spread data available."}
    if spread < 0:
        return {"status": "inverted", "signal": "warning",
                "message": f"Yield curve inverted ({spread:.2f}%) — historically a recession warning, not a guarantee."}
    if spread < 0.5:
        return {"status": "flat", "signal": "caution",
                "message": f"Yield curve nearly flat ({spread:.2f}%) — watch for inversion."}
    return {"status": "normal", "signal": "ok",
            "message": f"Yield curve normal ({spread:.2f}%)."}


def regime_from_macro(rows: list[dict]) -> dict:
    """Simple 3-factor macro tone: growth, inflation, policy. Each factor maps
    the latest reading into plain English. Deterministic, explainable."""
    latest = {r["key"]: r for r in rows if r.get("latest_value") is not None}
    gdp = latest.get("gdp", {}).get("latest_value")
    unemp = latest.get("unemployment", {}).get("latest_value")
    cpi = latest.get("cpi_yoy", {}).get("latest_value")
    ffr = latest.get("fed_funds", {}).get("latest_value")

    growth = "expanding" if (gdp is not None and gdp > 0) and (unemp is None or unemp < 5.5) else \
             "contracting" if (gdp is not None and gdp < 0) else "unclear"
    inflation = "high" if cpi is not None and cpi > 4 else "moderate" if cpi is not None and cpi > 2.5 else \
                "low" if cpi is not None else "unclear"
    policy = "restrictive" if ffr is not None and ffr > 4 else "neutral" if ffr is not None and ffr > 2 else \
             "accommodative" if ffr is not None else "unclear"

    tone = "risk-on" if growth == "expanding" and inflation != "high" else \
           "risk-off" if growth == "contracting" or policy == "restrictive" else "mixed"
    return {"growth": growth, "inflation": inflation, "policy": policy, "tone": tone,
            "explanation": "Derived from the latest official readings shown above; a snapshot, not a forecast."}


# ---------------------------------------------------------------------------
# Source adapters
# ---------------------------------------------------------------------------


def _fred_observation_payload(series_id: str, api_key: str) -> dict:
    import requests  # local import keeps module import cheap for tests
    resp = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": 400},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Official FRED observations -> float Series indexed by date. '.' (missing)
    values are dropped, not zero-filled."""
    payload = _fred_observation_payload(series_id, api_key)
    out = {}
    for obs in payload.get("observations", []):
        try:
            out[pd.Timestamp(obs["date"])] = float(obs["value"])
        except (ValueError, KeyError):
            continue  # '.' or malformed — skip, never fabricate
    if not out:
        raise ValueError(f"FRED returned no usable observations for {series_id}.")
    return pd.Series(out).sort_index()


def build_fred_indicator(ind: MacroIndicator, api_key: str, history: int) -> dict:
    """One indicator from official FRED data. Raises on failure so the route can
    report this source as UNAVAILABLE honestly."""
    if ind.fred_series is None:
        raise ValueError(f"{ind.key} has no FRED series mapping (market-proxy only).")
    raw = fetch_fred_series(ind.fred_series, api_key).tail(max(history, 60))
    if ind.key == "cpi_yoy":
        series = cpi_series_to_yoy(raw)
    else:
        series = raw
    if series.empty:
        raise ValueError(f"No usable {ind.key} values from FRED after transformation.")
    latest = float(series.iloc[-1])
    prev = float(series.iloc[-2]) if len(series) > 1 else None
    return _pack_indicator(ind, series, latest, prev, source="fred")


async def build_proxy_indicator(ind: MacroIndicator, manager, history: int) -> dict:
    """One indicator from market-price proxies (yfinance). Raises on failure.
    Async because the provider manager's history() is async."""
    if ind.proxy is None:
        raise ValueError(f"{ind.key} has no market-proxy mapping (FRED-only).")
    end_from = 400 if ind.key == "cpi_yoy" else history
    frame, _, _ = await manager.history(ind.proxy, _start_for(end_from), _end_for())
    series = frame["Close"].tail(max(history, 60))
    if series.empty:
        raise ValueError(f"No usable {ind.key} values from market proxy {ind.proxy}.")
    latest = float(series.iloc[-1])
    prev = float(series.iloc[-2]) if len(series) > 1 else None
    return _pack_indicator(ind, series, latest, prev, source="yfinance-proxy")


def _start_for(days: int):
    from datetime import date, timedelta
    return date.today() - timedelta(days=days)


def _end_for():
    from datetime import date
    return date.today()


def _pack_indicator(ind: MacroIndicator, series: pd.Series, latest: float, prev: float | None, source: str) -> dict:
    change = (latest - prev) if (prev is not None and prev != 0) else None
    return {
        "key": ind.key, "label": ind.label, "unit": ind.unit,
        "latest_value": round(latest, 4), "previous_value": round(prev, 4) if prev is not None else None,
        "change": round(change, 4) if change is not None else None,
        "history": [{"date": pd.Timestamp(d).date().isoformat(), "value": round(float(v), 4)} for d, v in series.tail(120).items()],
        "source": source,
        "fred_series": ind.fred_series, "proxy_symbol": ind.proxy,
        "expected": None,  # only a real vintage/consensus source may ever fill this
        "released": None,
    }


async def macro_report(manager, source: str = "fred", indicators: list[str] | None = None, fred_api_key: str | None = None,
                       history: int = 365) -> dict:
    """Build the full macro dashboard for ONE selectable source. Failing
    indicators degrade individually; total failure reports UNAVAILABLE."""
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r} — expected one of {list(SOURCES)}.")
    keys = indicators or list(MACRO_INDICATORS)
    unknown = [k for k in keys if k not in MACRO_INDICATORS]
    if unknown:
        raise ValueError(f"Unknown indicator(s): {unknown} — valid keys: {list(MACRO_INDICATORS)}")

    rows: list[dict] = []
    errors: dict[str, str] = {}
    for key in keys:
        ind = MACRO_INDICATORS[key]
        try:
            if source == "fred":
                if not fred_api_key:
                    raise ValueError("FRED_API_KEY not set — this source requires it.")
                rows.append(build_fred_indicator(ind, fred_api_key, history))
            else:
                rows.append(await build_proxy_indicator(ind, manager, history))
        except Exception as exc:
            errors[key] = str(exc)
            logger.warning("macro indicator %s (%s) failed: %s", key, source, exc)

    if not rows:
        return {"source": source, "status": "UNAVAILABLE", "indicators": [], "errors": errors,
                "yield_curve": classify_yield_curve(None), "regime": None, "calendar": [],
                "disclaimer": "Macro data is contextual information, not investment advice."}

    spread = next((r["latest_value"] for r in rows if r["key"] == "yield_spread_10y_2y"), None)
    calendar = []
    for key, meta in CALENDAR_EVENTS.items():
        row = next((r for r in rows if r["key"] == key), None)
        calendar.append({
            **meta, "indicator": key,
            "latest_value": row["latest_value"] if row else None,
            "previous_value": row["previous_value"] if row else None,
            "expected": None, "actual": row["latest_value"] if row else None,
            "surprise": None,  # requires an official expected/consensus feed; never invented
        })

    return {
        "source": source, "status": "OK", "indicators": rows, "errors": errors,
        "yield_curve": classify_yield_curve(spread), "regime": regime_from_macro(rows),
        "calendar": calendar,
        "disclaimer": "Macro data is contextual information, not investment advice.",
    }
