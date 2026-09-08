"""
Phase 13 — crypto, commodities, forex.

No new data provider needed: yfinance already quotes crypto pairs
(BTC-USD), commodity futures (GC=F), and FX pairs (EURUSD=X) through the
exact same interface already built for stocks in Phase 2 — same caching,
same retry/fallback, same LIVE/CACHED/STALE honesty. All that's genuinely
new here is a curated symbol list with friendly display names per asset
class, and a fan-out helper to fetch a whole category at once.
"""
from __future__ import annotations

import asyncio
import math

from .providers import MarketDataManager

CRYPTO_SYMBOLS = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "XRP-USD": "XRP", "ADA-USD": "Cardano", "DOGE-USD": "Dogecoin",
}
COMMODITY_SYMBOLS = {
    "GC=F": "Gold", "SI=F": "Silver", "CL=F": "Crude Oil (WTI)",
    "NG=F": "Natural Gas", "HG=F": "Copper",
}
FOREX_SYMBOLS = {
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF", "AUDUSD=X": "AUD/USD",
}

ASSET_CLASSES = {"crypto": CRYPTO_SYMBOLS, "commodities": COMMODITY_SYMBOLS, "forex": FOREX_SYMBOLS}


async def _quote_one(manager: MarketDataManager, symbol: str, name: str) -> dict:
    try:
        q = await manager.quote(symbol)
        price = None if math.isnan(q.price) else round(q.price, 4)
        return {
            "symbol": symbol, "name": name, "price": price,
            "change_percent": round(q.change_percent, 4) if q.change_percent is not None else None,
            "source": q.source, "status": q.status.value,
        }
    except Exception as exc:
        # A single bad/delisted symbol must not take down the whole category
        # view — report it as unavailable and keep going.
        return {"symbol": symbol, "name": name, "price": None, "change_percent": None,
                "source": "none", "status": "UNAVAILABLE", "error": str(exc)}


async def build_overview(manager: MarketDataManager, asset_class: str) -> list[dict]:
    symbols = ASSET_CLASSES.get(asset_class)
    if symbols is None:
        raise ValueError(f"Unknown asset class {asset_class!r} — expected one of {list(ASSET_CLASSES)}.")
    return list(await asyncio.gather(*(_quote_one(manager, sym, name) for sym, name in symbols.items())))
