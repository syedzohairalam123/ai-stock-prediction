"""
Discovery sub-categories (spec §41–§46, §74).

Five filters, each with an honest data story:

``ALL``          the curated asset catalogue with live quotes.
``PRE-MARKET``   **explicitly not** a fabricated "crypto market open". Crypto
                 trades 24/7, so this surface is presented as *PRE-SESSION /
                 UPCOMING MARKET EVENT*: real UTC session boundaries (which are
                 calendar facts), real observed search-interest ranking, and an
                 explicit statement that no open/close auction exists.
``INSTITUTIONS`` publicly disclosed corporate/treasury holdings from the
                 configured source, with source, coverage and limitations. No
                 institutional intent, flow or ETF number is inferred. Where a
                 dataset (e.g. ETF creations/redemptions) is not available from
                 the configured sources it is reported as ``UNAVAILABLE``.
``TARGETS``      analytical milestones — see :mod:`app.crypto.targets`.
``INDUSTRY``     the documented internal taxonomy plus the provider's own real
                 category taxonomy with its published market caps.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.crypto.schemas import DataStatus, ValueOrigin
from app.crypto.symbols import INDUSTRY_TAXONOMY, symbol_service

logger = logging.getLogger("neural_market.crypto.categories")

#: How many provider categories to surface (top by published market cap).
TOP_SOURCE_CATEGORIES = 24

CATEGORY_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "all",
        "label": "All",
        "description": "Every asset in the curated catalogue with live quotes.",
        "origin": ValueOrigin.SOURCE.value,
    },
    {
        "id": "pre-market",
        "label": "Pre-Session",
        "description": (
            "Session-boundary and upcoming-event intelligence. Crypto is a 24/7 market, so "
            "there is no opening auction: this shows real UTC calendar boundaries and observed "
            "search interest instead of an invented pre-market session."
        ),
        "origin": ValueOrigin.DERIVED.value,
    },
    {
        "id": "institutions",
        "label": "Institutions",
        "description": (
            "Publicly disclosed corporate treasury holdings, attributed to the publishing source. "
            "No flow, intent or ETF figure is inferred."
        ),
        "origin": ValueOrigin.SOURCE.value,
    },
    {
        "id": "targets",
        "label": "Targets",
        "description": "Analytical price milestones monitored against real timestamped candles.",
        "origin": ValueOrigin.CALCULATED.value,
    },
    {
        "id": "industry",
        "label": "Industry",
        "description": (
            "Documented internal sector taxonomy plus the provider's own published category "
            "metadata with its real market caps."
        ),
        "origin": ValueOrigin.DERIVED.value,
    },
]


def list_categories() -> List[Dict[str, Any]]:
    return [dict(entry) for entry in CATEGORY_DEFINITIONS]


# ---------------------------------------------------------------------------
# pre-session / upcoming events
# ---------------------------------------------------------------------------
def _session_boundaries(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Real UTC calendar boundaries.

    These are arithmetic facts about the Gregorian calendar, not market claims —
    stated plainly as such so the surface cannot be mistaken for an exchange
    session.
    """
    current = now or datetime.now(timezone.utc)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=current.weekday())
    month_start = day_start.replace(day=1)
    boundaries = [
        ("DAY", day_start, day_start + timedelta(days=1)),
        ("WEEK", week_start, week_start + timedelta(days=7)),
        ("MONTH", month_start, (month_start + timedelta(days=32)).replace(day=1)),
    ]
    out: List[Dict[str, Any]] = []
    for label, start, end in boundaries:
        out.append(
            {
                "period": label,
                "current_period_start": start.isoformat(),
                "next_boundary": end.isoformat(),
                "seconds_to_boundary": max(0, int((end - current).total_seconds())),
                "basis": "UTC calendar boundary. Crypto does not halt at these times.",
                "origin": ValueOrigin.DERIVED.value,
            }
        )
    return out


async def pre_session_view(manager) -> Dict[str, Any]:
    """Session boundaries + real observed search-interest ranking (spec §42)."""
    trending = await manager.get_trending()
    payload: Dict[str, Any] = {
        "category": "pre-market",
        "label": "Pre-Session / Upcoming Market Event",
        "market_structure": {
            "is_24_7": True,
            "statement": (
                "Crypto spot markets trade continuously. There is no opening or closing auction, "
                "so no pre-market session is fabricated. This surface reports real calendar "
                "boundaries and observed interest instead."
            ),
            "origin": ValueOrigin.DERIVED.value,
        },
        "session_boundaries": _session_boundaries(),
        "market_events": None,
        "event_source_note": (
            "No configured source publishes a machine-readable crypto market-event calendar "
            "(listings, halvings, unlocks) on the public keyless tier, so this field is "
            "UNAVAILABLE rather than filled with speculative dates."
        ),
    }
    if trending is None:
        payload["trending"] = None
        payload["trending_status"] = DataStatus.UNAVAILABLE.value
        payload["trending_note"] = "No configured source could supply search-interest data."
    else:
        payload["trending"] = trending
        payload["trending_status"] = DataStatus.LIVE.value
        payload["trending_source"] = trending[0].get("source") if trending else None
        payload["trending_note"] = (
            "Observed search-interest ranking as published by the source; it is a measurement of "
            "attention, not a price forecast."
        )
    return payload


# ---------------------------------------------------------------------------
# institutions
# ---------------------------------------------------------------------------
async def institutions_view(manager, symbol: str) -> Dict[str, Any]:
    """Publicly disclosed holdings for one asset, with full attribution (§43)."""
    treasury = await manager.get_public_treasury(symbol)
    payload: Dict[str, Any] = {
        "category": "institutions",
        "symbol": symbol.upper(),
        "etf_flows": None,
        "etf_flows_status": DataStatus.UNAVAILABLE.value,
        "etf_flows_note": (
            "ETF creation/redemption flow data is not published by the configured keyless "
            "sources, so it is reported UNAVAILABLE rather than estimated."
        ),
        "onchain_holder_data": None,
        "onchain_note": (
            "No configured source provides verifiable large-holder on-chain balances on the "
            "public keyless tier; surfacing this would require a dedicated on-chain data provider."
        ),
    }
    if treasury is None:
        payload["disclosed_holdings"] = None
        payload["status"] = DataStatus.UNAVAILABLE.value
        payload["reason"] = "No configured source publishes disclosed treasury holdings for this asset."
        return payload

    payload["disclosed_holdings"] = {
        "source": treasury.get("source"),
        "asset": treasury.get("asset"),
        "total_holdings": treasury.get("total_holdings"),
        "total_value_usd": treasury.get("total_value_usd"),
        "market_cap_dominance_percent": treasury.get("market_cap_dominance"),
        "company_count": treasury.get("company_count"),
        "companies": treasury.get("companies"),
        "coverage": treasury.get("coverage"),
        "limitations": treasury.get("limitations"),
        "origin": ValueOrigin.SOURCE.value,
    }
    payload["status"] = DataStatus.LIVE.value
    payload["note"] = (
        "Reported, published disclosure only. This module never infers institutional activity "
        "that has not been publicly disclosed."
    )
    return payload


# ---------------------------------------------------------------------------
# industry
# ---------------------------------------------------------------------------
async def industry_view(manager) -> Dict[str, Any]:
    """Internal documented taxonomy + the provider's own published categories."""
    internal = symbol_service.by_industry()
    source_categories = await manager.get_categories()
    payload: Dict[str, Any] = {
        "category": "industry",
        "taxonomy": {
            "type": "internal-documented",
            "basis": "Classified by what the asset's protocol actually is; see `definition`.",
            "industries": [
                {
                    "id": industry,
                    "label": meta["label"],
                    "definition": meta["basis"],
                    "symbols": sorted(internal.get(industry, [])),
                    "count": len(internal.get(industry, [])),
                }
                for industry, meta in INDUSTRY_TAXONOMY.items()
            ],
            "origin": ValueOrigin.DERIVED.value,
        },
        "source_categories": None,
        "source_categories_status": DataStatus.UNAVAILABLE.value,
    }
    if source_categories:
        trimmed = sorted(
            [c for c in source_categories if c.get("market_cap")],
            key=lambda c: c["market_cap"] or 0,
            reverse=True,
        )[:TOP_SOURCE_CATEGORIES]
        payload["source_categories"] = trimmed
        payload["source_categories_status"] = DataStatus.LIVE.value
        payload["source_categories_note"] = (
            f"Published category metadata from {trimmed[0].get('source')} with its real aggregate "
            "market caps. Category membership is the source's, not ours."
        )
    return payload


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------
def catalogue_view() -> List[Dict[str, Any]]:
    """The curated catalogue with its provider mappings and industry tag."""
    return symbol_service.list_assets()


def catalogue_counts() -> Dict[str, int]:
    assets = symbol_service.list_assets()
    industries = symbol_service.by_industry()
    return {
        "assets": len(assets),
        "industries": len(industries),
        "streaming": len(symbol_service.streaming_assets()),
    }
