"""
Crypto pro module — TWO selectable data sources, per the project's "when two
similar sources exist, let the user choose" rule:

  "coingecko" — CoinGecko public API: real market-cap, rank, supply, and
                24h/7d/30d changes. Free, no key needed for basic endpoints,
                rate-limited (~30 req/min) — responses are cached by the
                route layer. Reports UNAVAILABLE cleanly when unreachable.
  "yfinance"  — the existing Phase 2 provider manager (same cache/retry/
                honesty as stocks). Has price + change%, no market cap.

Both return the same normalized row shape so the frontend can switch
sources without any logic change.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from .multi_asset import CRYPTO_SYMBOLS

logger = logging.getLogger("neural_market.crypto_pro")

SOURCES = ("coingecko", "yfinance")

COINGECKO_IDS = {
    "BTC-USD": "bitcoin", "ETH-USD": "ethereum", "SOL-USD": "solana",
    "XRP-USD": "ripple", "ADA-USD": "cardano", "DOGE-USD": "dogecoin",
}

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"


COINGECKO_ID_TO_SYMBOL = {v: k for k, v in COINGECKO_IDS.items()}


def _fetch_coingecko_markets(timeout: float = 15.0) -> list[dict]:
    import requests
    resp = requests.get(
        COINGECKO_MARKETS_URL,
        params={
            "vs_currency": "usd",
            "ids": ",".join(COINGECKO_IDS.values()),
            "order": "market_cap_desc",
            "price_change_percentage": "24h,7d,30d",
            "per_page": 50,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def coingecko_rows() -> list[dict]:
    """CoinGecko source -> normalized rows. Raises on failure; the route turns
    that into an honest per-source error, never a fake row."""
    raw = _fetch_coingecko_markets()
    rows = []
    for c in raw:
        cg_id = c.get("id")
        rows.append({
            "symbol": COINGECKO_ID_TO_SYMBOL.get(cg_id, f"{(c.get('symbol') or cg_id or '?').upper()}-USD"),
            "name": c.get("name"),
            "price": c.get("current_price"),
            "change_percent_24h": c.get("price_change_percentage_24h_in_currency"),
            "change_percent_7d": c.get("price_change_percentage_7d_in_currency"),
            "change_percent_30d": c.get("price_change_percentage_30d_in_currency"),
            "market_cap": c.get("market_cap"),
            "market_cap_rank": c.get("market_cap_rank"),
            "total_volume": c.get("total_volume"),
            "circulating_supply": c.get("circulating_supply"),
            "ath": c.get("ath"),
            "ath_change_percent": c.get("ath_change_percentage"),
            "source": "coingecko",
        })
    return rows


async def yfinance_rows(manager) -> list[dict]:
    """Existing provider-manager source -> normalized rows (same shape, fewer
    fields — yfinance doesn't give market cap through this path)."""
    out = []
    end = date.today()
    start = end - timedelta(days=45)
    for sym, name in CRYPTO_SYMBOLS.items():
        try:
            frame, source, status = await manager.history(sym, start, end)
            closes = frame["Close"]
            price = float(closes.iloc[-1])
            chg = {}
            for days in (1, 7, 30):
                if len(closes) > days:
                    base = float(closes.iloc[-1 - days])
                    chg[days] = round((price - base) / base * 100, 4) if base else None
                else:
                    chg[days] = None
            out.append({
                "symbol": sym, "name": name, "price": round(price, 4),
                "change_percent_24h": chg[1], "change_percent_7d": chg[7],
                "change_percent_30d": chg[30],
                "market_cap": None, "market_cap_rank": None,
                "total_volume": float(frame["Volume"].tail(1).iloc[0]) if "Volume" in frame.columns and len(frame) else None,
                "circulating_supply": None, "ath": None, "ath_change_percent": None,
                "source": source,
            })
        except Exception as exc:
            logger.warning("crypto row failed for %s: %s", sym, exc)
            out.append({"symbol": sym, "name": name, "price": None, "change_percent_24h": None,
                        "change_percent_7d": None, "change_percent_30d": None, "market_cap": None,
                        "market_cap_rank": None, "total_volume": None, "circulating_supply": None,
                        "ath": None, "ath_change_percent": None, "source": "none",
                        "error": str(exc)})
    return out


async def crypto_overview(manager, source: str = "coingecko") -> dict:
    """Source-selectable crypto dashboard. A failing source reports UNAVAILABLE
    with the real reason instead of silently switching to the other one."""
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r} — expected one of {list(SOURCES)}.")
    try:
        rows = coingecko_rows() if source == "coingecko" else await yfinance_rows(manager)
    except Exception as exc:
        return {"source": source, "status": "UNAVAILABLE", "reason": str(exc), "coins": []}
    if not rows:
        return {"source": source, "status": "UNAVAILABLE", "reason": "No rows returned.", "coins": []}

    priced = [r for r in rows if r.get("price")]
    total_mc = sum(r["market_cap"] for r in rows if r.get("market_cap"))
    btc = next((r for r in rows if r["symbol"] == "BTC-USD" and r.get("market_cap")), None)
    eth = next((r for r in rows if r["symbol"] == "ETH-USD" and r.get("market_cap")), None)
    ranking = (
        sorted(rows, key=lambda r: (r.get("market_cap") or 0), reverse=True)
        if any(r.get("market_cap") for r in rows)
        else sorted([r for r in rows if r.get("change_percent_7d") is not None],
                    key=lambda r: r["change_percent_7d"], reverse=True)
    )
    return {
        "source": source,
        "status": "OK",
        "summary": {
            "tracked": len(rows),
            "priced": len(priced),
            "total_market_cap": total_mc or None,
            "btc_dominance_pct": round(btc["market_cap"] / total_mc * 100, 4) if btc and total_mc else None,
            "eth_dominance_pct": round(eth["market_cap"] / total_mc * 100, 4) if eth and total_mc else None,
            "top_gainer_7d": ranking[0]["symbol"] if ranking else None,
            "worst_performer_7d": ranking[-1]["symbol"] if ranking else None,
        },
        "coins": rows,
        "disclaimer": "Analytical market data only — not investment advice or a recommendation to buy any asset.",
    }
