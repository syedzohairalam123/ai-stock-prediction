"""
Phase 10 — portfolio P&L computation.

Pure, deterministic math over holdings + current prices — no network here.
The route fetches current quotes through the provider manager and passes
them in as a {ticker: price} map; this module attaches market value, cost
basis, and P&L to each holding and rolls everything up into a summary.
Quotes that fail to fetch are handled honestly: that holding shows
current_price: null and is excluded from the totals rather than priced at
a fabricated value.
"""
from __future__ import annotations

from typing import Optional


def enrich_holding(holding: dict, current_price: Optional[float]) -> dict:
    """One holding -> one enriched row. `current_price` None means the live
    quote couldn't be fetched; the row still returns with null market
    fields instead of a guessed number."""
    shares = float(holding["shares"])
    avg_cost = float(holding["avg_cost"])
    cost_basis = round(avg_cost * shares, 4)
    row = {
        **holding,
        "current_price": current_price,
        "cost_basis": cost_basis,
    }
    if current_price is not None:
        row["market_value"] = round(current_price * shares, 4)
        row["pnl"] = round(row["market_value"] - cost_basis, 4)
        row["pnl_pct"] = round((current_price - avg_cost) / avg_cost * 100.0, 4) if avg_cost else None
    else:
        row["market_value"] = None
        row["pnl"] = None
        row["pnl_pct"] = None
    return row


def portfolio_summary(holdings: list[dict], quotes: dict[str, float]) -> dict:
    """`holdings`: rows from the repository. `quotes`: {ticker: current price}.
    Totals are computed only over holdings with a live price, and the count
    of missing quotes is reported so the UI can show that some prices
    couldn't be fetched rather than silently understating value."""
    enriched = [enrich_holding(h, quotes.get(h["ticker"])) for h in holdings]
    priced = [r for r in enriched if r["market_value"] is not None]

    total_cost = round(sum(r["cost_basis"] for r in enriched), 4)
    total_value = round(sum(r["market_value"] for r in priced), 4)
    total_pnl = round(total_value - total_cost, 4)
    total_pnl_pct = round(total_pnl / total_cost * 100.0, 4) if total_cost else None

    return {
        "holdings": enriched,
        "summary": {
            "positions": len(enriched),
            "priced_positions": len(priced),
            "total_cost_basis": total_cost,
            "total_market_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
        },
        "disclaimer": "Portfolio tracking for education/simulation only, not investment advice.",
    }