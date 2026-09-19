"""
Phase 9 — Popular Stocks Discovery Service

Fetches real market data for popular PSX stocks and calculates:
- Current price and change (vs the provider's own previous close)
- Price trends (sparkline data from real daily closes)
- Sector / industry / market-cap info from the company profile

Uses the same provider manager as every other feature — no separate price
dataset lives here (spec P: data consistency). Symbols that the provider
cannot price are reported in `unavailable` with a reason instead of being
silently dropped or filled with dummy values (spec S).
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Popular PSX stocks by category (not hardcoded — just the initial discovery
# list; the module is list-driven so new symbols/categories need no code
# changes). All symbols resolve through the provider's PSX `.KA` mapping.
POPULAR_PSX_STOCKS = {
    "oil_gas": ["OGDC", "PPL", "POL", "MARI"],
    "banking": ["HBL", "UBL", "MCB", "NBP", "BAFL", "MEBL"],
    "cement": ["LUCK", "MLCF", "PIOC", "DGKC", "KOHC"],
    "fertilizer": ["FFC", "ENGRO", "FATIMA"],
    "power": ["HUBC", "KAPCO", "KEL", "SNGP"],
    "technology": ["SYS", "TRG", "AGTL", "NETSOL", "AVN"],
    "chemicals": ["ICI", "LOTCHEM", "EPCL"],
    "auto": ["INDU", "PSMC", "MTL"],
    "food": ["NESTLE", "NRL"],
    "pharma": ["SEARL", "GLAXO", "ABBOTT"],
    "textile": ["NML", "ILP", "NCL"],
    "steel": ["ASL", "ISL", "MUGHAL"],
    "oil_marketing": ["PSO", "APL", "SHEL"],
}


def get_popular_stocks_list(category: Optional[str] = None, limit: int = 20) -> List[str]:
    """
    Get list of popular PSX stocks.

    Args:
        category: Optional category filter (oil_gas, banking, etc.)
        limit: Maximum number of stocks to return

    Returns:
        List of stock symbols
    """
    if category and category in POPULAR_PSX_STOCKS:
        return POPULAR_PSX_STOCKS[category][:max(0, limit)]

    # Return mix of popular stocks from different categories
    all_stocks: List[str] = []
    for cat_stocks in POPULAR_PSX_STOCKS.values():
        all_stocks.extend(cat_stocks)

    # Remove duplicates while preserving order
    seen = set()
    unique_stocks = []
    for stock in all_stocks:
        if stock not in seen:
            seen.add(stock)
            unique_stocks.append(stock)

    return unique_stocks[:max(0, limit)]


def _round_or_none(value, digits: int = 2) -> Optional[float]:
    """Round a number for display; NaN/inf/None stay None (never faked)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


async def fetch_stock_data(manager, symbol: str) -> Optional[Dict]:
    """
    Fetch comprehensive data for a single stock.

    Args:
        manager: MarketDataManager instance
        symbol: Stock symbol

    Returns:
        Dict with stock data or None if unavailable
    """
    import pandas as pd  # local import: only needed when trend rows exist

    try:
        # Get current quote — the one source of truth for price + prev close
        quote = await manager.quote(symbol)

        if quote.status.value == "unavailable" or math.isnan(quote.price):
            logger.debug("quote unavailable for %s", symbol)
            return None

        # Get historical data for trend (last 30 days)
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        trend_data: List[Dict] = []
        try:
            history_df, _source, _status = await manager.history(
                symbol, start_date, end_date
            )

            # Calculate trend data (sparkline) — Phase 9 fix: this block used
            # `pd.isna` with pandas imported only inside get_popular_stocks(),
            # so ANY symbol with history rows crashed this function and the
            # card silently vanished from the grid. The import now exists.
            if history_df is not None and not history_df.empty and "Close" in history_df.columns:
                recent = history_df.tail(10)
                for idx, row in recent.iterrows():
                    close = row.get("Close")
                    if close is None or pd.isna(close):
                        continue
                    trend_data.append({"date": str(idx.date()), "price": round(float(close), 4)})
        except Exception as e:
            logger.debug("history fetch failed for %s: %s", symbol, e)
            trend_data = []

        # Get company profile (optional — absence degrades, never fails)
        profile: Dict = {}
        try:
            profile = await manager.profile(symbol)
        except Exception as e:
            logger.debug("profile unavailable for %s: %s", symbol, e)

        price = _round_or_none(quote.price, 4)
        if price is None:
            return None

        # Phase 9 fix: day change must be measured against the PREVIOUS CLOSE
        # (the quote's own, which is yesterday's settlement), not against the
        # close 10 days ago — the old code used trend[-2], producing wildly
        # wrong "day change" numbers whenever a 10-day sparkline existed.
        change = None
        change_pct = None
        prev_close = _round_or_none(quote.previous_close, 4)
        if prev_close and prev_close > 0:
            raw_change = price - prev_close
            change = round(raw_change, 2)
            change_pct = round((raw_change / prev_close) * 100, 2)

        return {
            "symbol": symbol.upper(),
            "name": profile.get("name") or symbol.upper(),
            "price": price,
            # Phase 9 fix: `if change else None` treated a real 0.00 change as
            # missing. Only None/NaN is missing now — a flat day is a flat day.
            "change": change,
            "change_pct": change_pct,
            "previous_close": prev_close,
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "market_cap": _round_or_none(profile.get("market_cap"), 0),
            "trend": trend_data,
            "source": quote.source,
            "status": quote.status.value,
            "timestamp": quote.timestamp.isoformat(),
        }

    except Exception as e:
        logger.error("error fetching data for %s: %s", symbol, e)
        return None


async def get_popular_stocks(manager, category: Optional[str] = None,
                            limit: int = 20) -> Dict:
    """
    Get popular stocks with real market data.

    Args:
        manager: MarketDataManager instance
        category: Optional category filter
        limit: Maximum number of stocks

    Returns:
        Dict with stocks data, per-symbol failures, and metadata
    """
    from datetime import datetime, timezone

    # Get stock list
    symbols = get_popular_stocks_list(category, limit)

    # Fetch data for all stocks concurrently; every failure is isolated so one
    # dead symbol can never blank out the whole grid.
    tasks = [fetch_stock_data(manager, symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    stocks: List[Dict] = []
    unavailable: List[Dict] = []
    for symbol, result in zip(symbols, results):
        if isinstance(result, Exception):
            logger.debug("stock fetch failed for %s: %s", symbol, result)
            unavailable.append({"symbol": symbol, "reason": str(result)})
        elif result is None:
            unavailable.append({"symbol": symbol, "reason": "quote unavailable"})
        else:
            stocks.append(result)

    # Sort by market cap (if available); symbols without one keep input order
    # after the priced ones — a missing cap must not sink a real quote to the
    # bottom of the grid by comparing None against float (which raises).
    stocks.sort(
        key=lambda x: x.get("market_cap") if x.get("market_cap") is not None else 0,
        reverse=True,
    )

    return {
        "stocks": stocks,
        "count": len(stocks),
        "requested": len(symbols),
        "unavailable": unavailable,
        "category": category,
        "categories": list(POPULAR_PSX_STOCKS.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_stock_categories() -> List[Dict]:
    """Get available stock categories."""
    return [
        {"id": cat, "name": cat.replace("_", " ").title(), "count": len(stocks)}
        for cat, stocks in POPULAR_PSX_STOCKS.items()
    ]
