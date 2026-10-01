"""
Crypto Volatility & Forecasting Intelligence module (Phase 22).

A real-data-only analytics layer over public, keyless market providers:

  * **Binance spot** — REST klines/ticker + WebSocket kline streams (primary,
    keyless). Granular intervals (1m … 1M) come from here.
  * **CoinGecko** — market cap / rank / supply metadata and a coarse
    `1d` history fallback (keyless).

No module in this package fabricates a price, candle, volume, market cap,
timestamp, target or probability. When a configured source cannot supply a
value the API returns ``UNAVAILABLE`` rather than a placeholder, and anything
computed from real source data is labelled ``CALCULATED`` / ``MODELLED``
according to spec §99.

Import surface is kept lazy where a sub-module pulls heavy optional
dependencies (scikit-learn, WebSockets), so importing ``app.crypto`` stays cheap
and cannot break application startup.
"""

from __future__ import annotations

__all__ = [
    "config",
    "schemas",
    "symbols",
    "timeframes",
    "normalization",
]

__version__ = "1.0.0"
