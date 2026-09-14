"""
Classic stock screener - simplified version for basic filtering.

Deliberately technical/price-based only — P/E, P/S, market cap, and other
fundamentals filters are NOT included here, because there's no real
fundamentals data source wired up yet. Every filter here is computed from the
same real OHLCV+indicator pipeline (`indicators.py`) every other feature
in this app already uses.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

# A curated, liquid, well-known universe spanning sectors — not exhaustive,
# but real, named companies rather than an arbitrary/fake list. Easy to
# extend later (or replace with an index constituent list from a real
# provider once one is wired up).
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "ORCL", "ADBE",
    "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "UBER", "SHOP",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "PYPL",
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO",
    "WMT", "COST", "HD", "NKE", "MCD", "SBUX", "PG", "KO", "PEP",
    "XOM", "CVX", "CAT", "BA", "GE", "HON",
]


@dataclass
class ScreenerFilters:
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_pct_change: Optional[float] = None
    max_pct_change: Optional[float] = None
    min_rsi: Optional[float] = None
    max_rsi: Optional[float] = None
    trend: Optional[str] = None  # "uptrend" (Close > SMA10 > SMA30), "downtrend", or None
    min_volatility_pct: Optional[float] = None
    max_volatility_pct: Optional[float] = None
    sort_by: str = "pct_change"  # one of the ScreenerRow field names below
    sort_desc: bool = True
    limit: int = 25


def _row_from_history(ticker: str, df: pd.DataFrame) -> Optional[dict]:
    if df is None or len(df) < 2:
        return None
    last, prev = df.iloc[-1], df.iloc[-2]
    price = float(last["Close"])
    pct_change = round((price - float(prev["Close"])) / float(prev["Close"]) * 100, 4) if prev["Close"] else 0.0
    returns = df["Close"].pct_change().dropna().tail(30)
    volatility_pct = round(float(returns.std() * (252 ** 0.5) * 100), 4) if len(returns) > 1 else None
    sma_10 = float(last["sma_10"]) if "sma_10" in df.columns and pd.notna(last["sma_10"]) else None
    sma_30 = float(last["sma_30"]) if "sma_30" in df.columns and pd.notna(last["sma_30"]) else None
    trend = None
    if sma_10 is not None and sma_30 is not None:
        if price > sma_10 > sma_30:
            trend = "uptrend"
        elif price < sma_10 < sma_30:
            trend = "downtrend"
        else:
            trend = "mixed"
    return {
        "ticker": ticker,
        "price": round(price, 4),
        "pct_change": pct_change,
        "rsi_14": round(float(last["rsi_14"]), 4) if "rsi_14" in df.columns and pd.notna(last["rsi_14"]) else None,
        "volatility_pct": volatility_pct,
        "trend": trend,
        "volume": int(last["Volume"]) if "Volume" in df.columns and pd.notna(last["Volume"]) else None,
    }


def _passes(row: dict, f: ScreenerFilters) -> bool:
    checks = [
        (f.min_price is None or row["price"] >= f.min_price),
        (f.max_price is None or row["price"] <= f.max_price),
        (f.min_pct_change is None or row["pct_change"] >= f.min_pct_change),
        (f.max_pct_change is None or row["pct_change"] <= f.max_pct_change),
        (f.min_rsi is None or (row["rsi_14"] is not None and row["rsi_14"] >= f.min_rsi)),
        (f.max_rsi is None or (row["rsi_14"] is not None and row["rsi_14"] <= f.max_rsi)),
        (f.trend is None or row["trend"] == f.trend),
        (f.min_volatility_pct is None or (row["volatility_pct"] is not None and row["volatility_pct"] >= f.min_volatility_pct)),
        (f.max_volatility_pct is None or (row["volatility_pct"] is not None and row["volatility_pct"] <= f.max_volatility_pct)),
    ]
    return all(checks)


async def run_screener(history_fetcher, universe: list[str], filters: ScreenerFilters) -> dict:
    """`history_fetcher(ticker) -> awaitable[(DataFrame, source, status)]` — a
    thin wrapper the caller supplies (usually DataAgent.history bound to a
    fixed recent date range) so this module doesn't need to know about dates
    or the provider manager directly."""
    results = await asyncio.gather(*(history_fetcher(t) for t in universe), return_exceptions=True)
    rows, failed = [], []
    for ticker, result in zip(universe, results):
        if isinstance(result, Exception):
            failed.append(ticker)
            continue
        frame, source, status = result
        row = _row_from_history(ticker, frame)
        if row is not None:
            row["data_status"] = status.value if hasattr(status, "value") else str(status)
            rows.append(row)

    matched = [r for r in rows if _passes(r, filters)]
    reverse = filters.sort_desc
    matched.sort(key=lambda r: (r.get(filters.sort_by) is None, r.get(filters.sort_by) or 0), reverse=reverse)

    return {
        "universe_size": len(universe),
        "scanned": len(rows),
        "matched": len(matched),
        "failed": failed,
        "results": matched[: filters.limit],
    }