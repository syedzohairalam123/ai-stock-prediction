"""
Phase 7 — PKR precious-metals center (real data, explicit units).

Where the numbers come from
---------------------------
No free, keyless API publishes the Karachi Sarafa Association retail board, so
this module does not pretend to have one. It derives local PKR rates from two
real, live inputs it can verify:

  1. The international metal price — COMEX front-month futures from Yahoo
     (`GC=F` gold, `SI=F` silver, `PL=F` platinum, USD per troy ounce). Yahoo
     publishes no spot symbol (XAUUSD=X returns nothing — verified), so the
     futures contract is named explicitly as the source rather than dressed up
     as a spot quote.
  2. The live interbank USD/PKR rate (`USDPKR=X`, real bid/ask).

  price(PKR per unit) = (USD per troy ounce ÷ 31.1034768) × USD/PKR × grams_per_unit × purity_ratio

Every row carries its unit. Per gram, per 10 gram and per tola are separate rows
with explicit units — never silently mixed, which is the failure mode the spec
calls out. The raw inputs are returned alongside the results so the arithmetic
can be checked by eye, and the response states plainly that this is a derived
international-parity rate, not a local retail quote.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from .config import settings
from .forex import classify_data_mode, get_data_freshness, normalize_bid_ask
from .logging_config import get_logger
from .providers import fx_rates as fx

logger = get_logger("neural_market.commodities")

#: Troy ounce is the unit every international metal quote uses.
TROY_OUNCE_GRAMS = 31.1034768
#: Pakistan's tola (11.6638125 g) — the unit local bullion is actually traded in.
TOLA_GRAMS = 11.6638125

UNIT_GRAMS: dict[str, float] = {"gram": 1.0, "10_gram": 10.0, "tola": TOLA_GRAMS}
UNIT_LABELS: dict[str, str] = {
    "gram": "PKR per gram",
    "10_gram": "PKR per 10 gram",
    "tola": "PKR per tola",
}

SPARKLINE_POINTS = 30


@dataclass(frozen=True)
class MetalSpec:
    """One tradable purity of one metal."""

    key: str
    symbol: str
    name: str
    type: str
    purity: str
    fineness: float
    #: Price ratio against the pure metal. Gold 22K is 22/24 of 24K by definition;
    #: the fine qualities are 1.0 because the source contract is already fine.
    purity_ratio: float
    series: str
    units: tuple[str, ...]
    #: Gold and silver are quoted per tola in Pakistan; platinum has no local
    #: tola convention, so it leads with the per-gram price.
    primary_unit: str


METALS: tuple[MetalSpec, ...] = (
    MetalSpec(
        key="gold_24k", symbol="XAU-24K", name="Gold 24K", type="gold",
        purity="24K", fineness=999.9, purity_ratio=1.0, series="XAU",
        units=("gram", "10_gram", "tola"), primary_unit="tola",
    ),
    MetalSpec(
        key="gold_22k", symbol="XAU-22K", name="Gold 22K", type="gold",
        purity="22K", fineness=916.7, purity_ratio=22 / 24, series="XAU",
        units=("gram", "10_gram", "tola"), primary_unit="tola",
    ),
    MetalSpec(
        key="silver", symbol="XAG", name="Silver", type="silver",
        purity="999 fine", fineness=999.0, purity_ratio=1.0, series="XAG",
        units=("gram", "10_gram", "tola"), primary_unit="tola",
    ),
    MetalSpec(
        key="platinum", symbol="XPT", name="Platinum", type="platinum",
        purity="950 (99.95%)", fineness=950.0, purity_ratio=1.0, series="XPT",
        units=("gram", "10_gram", "tola"), primary_unit="gram",
    ),
)

METAL_BY_KEY = {m.key: m for m in METALS}
METAL_BY_SYMBOL = {m.symbol.upper(): m for m in METALS}


@dataclass
class CommodityQuote:
    """One metal purity in one unit (spec H). Raw numbers, no formatted strings."""

    id: str
    symbol: str
    name: str
    type: str
    purity: str
    fineness: Optional[float]
    #: explicit human unit, e.g. "PKR per tola"; `unit_key` is the machine form
    unit: str
    unit_key: str = ""
    currency: str = "PKR"
    #: PKR per `unit` — None when no source could price it (never 0 as a stand-in)
    price: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    previous_price: Optional[float] = None
    timestamp: Optional[str] = None
    timestamp_epoch: Optional[int] = None
    source: str = "none"
    data_mode: str = "UNAVAILABLE"
    freshness: str = "UNKNOWN"
    is_primary_unit: bool = False
    #: underlying USD-per-troy-ounce quote this row was derived from
    usd_per_troy_ounce: Optional[float] = None
    usdpkr: Optional[float] = None
    bid_ask_note: Optional[str] = None
    error: Optional[str] = None
    sparkline_pkr: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def price_per_unit(
    usd_per_troy_ounce: float,
    usdpkr: float,
    unit: str,
    purity_ratio: float = 1.0,
) -> Optional[float]:
    """The one conversion this module performs, isolated so it can be tested.

    Returns None for an unknown unit or a non-positive/non-finite result rather
    than passing a bogus number on to the UI.
    """
    grams = UNIT_GRAMS.get(unit)
    if grams is None or purity_ratio is None:
        return None
    try:
        usd = float(usd_per_troy_ounce)
        rate = float(usdpkr)
    except (TypeError, ValueError):
        return None
    if not (usd > 0 and rate > 0):
        return None
    value = (usd / TROY_OUNCE_GRAMS) * rate * grams * float(purity_ratio)
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        return None
    return round(value, 2)


def _sparkline(metal_prices_usd: Optional[pd.Series], usdpkr_series: Optional[pd.Series], unit: str, ratio: float) -> list[float]:
    """A real PKR series for the card trend line: the metal's own daily closes
    multiplied by the matching day's USD/PKR close (inner-joined on date), then
    converted to the card's unit. Empty when either series is unavailable."""
    if metal_prices_usd is None or usdpkr_series is None:
        return []
    try:
        joined = pd.concat([metal_prices_usd.rename("metal"), usdpkr_series.rename("fx")], axis=1).dropna()
    except Exception:  # misaligned/duplicate indexes — trend line is optional
        return []
    if joined.empty:
        return []
    joined = joined.tail(SPARKLINE_POINTS)
    grams = UNIT_GRAMS.get(unit, 1.0)
    series = (joined["metal"] / TROY_OUNCE_GRAMS) * joined["fx"] * grams * ratio
    return [round(float(v), 2) for v in series.tolist() if v == v]


async def _daily_closes(manager, symbol: str, days: int = 400) -> Optional[pd.Series]:
    """Real daily closes through the existing provider layer (cached)."""
    try:
        frame, _, _ = await manager.history(symbol, datetime.now(timezone.utc).date() - timedelta(days=days), datetime.now(timezone.utc).date())
        if frame is None or frame.empty or "Close" not in frame:
            return None
        return frame["Close"].astype(float)
    except Exception as exc:
        logger.debug("history unavailable for %s: %s", symbol, exc)
        return None


async def build_commodity_quotes(manager, *, force_refresh: bool = False) -> dict[str, Any]:
    """The full commodities payload: unit-explicit rows + the inputs they came from."""
    series_symbols = [fx.METAL_SERIES[m.series] for m in METALS]
    symbols = sorted(set(series_symbols) | {fx.PKR_CROSS_SYMBOLS["USD"]})
    raws = await fx.yahoo_quotes(symbols, force_refresh=force_refresh)

    usd_raw = raws.get(fx.PKR_CROSS_SYMBOLS["USD"])
    usdpkr = None
    if usd_raw is not None and usd_raw.status != "UNAVAILABLE":
        # Mid when the source gives a valid pair, else its traded price.
        _, _, mid, _, _, _ = normalize_bid_ask(usd_raw.bid, usd_raw.ask)
        usdpkr = mid or usd_raw.price
    usdpkr_timestamp = usd_raw.timestamp_epoch if usd_raw is not None else None

    now_epoch = fx.utc_now_epoch()

    # Trend lines need real history; fetched once per metal and once for USD/PKR.
    metal_series: dict[str, Optional[pd.Series]] = {}
    usdpkr_series: Optional[pd.Series] = None
    if usdpkr:
        usdpkr_series = await _daily_closes(manager, fx.PKR_CROSS_SYMBOLS["USD"])
        for metal in METALS:
            if metal.series not in metal_series:
                metal_series[metal.series] = await _daily_closes(manager, fx.METAL_SERIES[metal.series])

    rows: list[CommodityQuote] = []
    inputs: dict[str, Any] = {}
    for metal in METALS:
        source_symbol = fx.METAL_SERIES[metal.series]
        raw = raws.get(source_symbol)
        last = raw.price if raw is not None and raw.status != "UNAVAILABLE" else None
        previous = raw.previous_close if raw is not None and raw.status != "UNAVAILABLE" else None
        if last is not None and not (last > 0):
            last = None
        if previous is not None and not (previous > 0):
            previous = None

        if metal.series not in inputs:
            bid, ask, mid, spread, spread_percent, note = (None, None, None, None, None, None)
            if raw is not None:
                bid, ask, mid, spread, spread_percent, note = normalize_bid_ask(raw.bid, raw.ask)
            inputs[metal.series] = {
                "contract": source_symbol,
                "usd_per_troy_ounce": last,
                "previous_close_usd_per_troy_ounce": previous,
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "spread_percent": spread_percent,
                "bid_ask_note": note,
                "source": raw.source if raw else fx.SOURCE_YAHOO,
                "timestamp_epoch": raw.timestamp_epoch if raw else None,
                "status": raw.status if raw else "UNAVAILABLE",
                "error": raw.error if raw else "no source available",
            }

        for unit in metal.units:
            row = CommodityQuote(
                id=f"{metal.key}-{unit}",
                symbol=metal.symbol,
                name=metal.name,
                type=metal.type,
                purity=metal.purity,
                fineness=metal.fineness,
                unit=UNIT_LABELS[unit],
                unit_key=unit,
                is_primary_unit=unit == metal.primary_unit,
            )
            if usdpkr is None:
                row.data_mode = "UNAVAILABLE"
                row.error = "USD/PKR rate unavailable — cannot derive a PKR price"
                rows.append(row)
                continue

            row.usdpkr = round(float(usdpkr), 4)
            row.usd_per_troy_ounce = last
            if last is None:
                row.data_mode = "UNAVAILABLE"
                row.freshness = "UNKNOWN"
                row.source = raw.source if raw else "none"
                row.error = (raw.error if raw else None) or "no international price available"
                rows.append(row)
                continue

            row.price = price_per_unit(last, usdpkr, unit, metal.purity_ratio)
            if row.price is None:
                row.data_mode = "UNAVAILABLE"
                row.error = "derived price was not a usable positive number — rejected"
                rows.append(row)
                continue

            if previous is not None:
                prev_price = price_per_unit(previous, usdpkr, unit, metal.purity_ratio)
                if prev_price is not None:
                    row.previous_price = prev_price
                    row.change = round(row.price - prev_price, 2)
                    if prev_price:
                        row.change_percent = round(((row.price - prev_price) / prev_price) * 100, 4)

            row.timestamp_epoch = raw.timestamp_epoch if raw else None
            if row.timestamp_epoch:
                row.timestamp = datetime.fromtimestamp(row.timestamp_epoch, tz=timezone.utc).isoformat()
            row.source = raw.source if raw else fx.SOURCE_YAHOO
            row.bid_ask_note = inputs[metal.series]["bid_ask_note"]
            row.freshness = get_data_freshness(row.timestamp_epoch, now_epoch=now_epoch)
            row.data_mode = classify_data_mode(
                row.timestamp_epoch, raw.granularity if raw else fx.GRANULARITY_REALTIME,
                now_epoch=now_epoch, has_value=True,
            )
            if unit == metal.primary_unit:
                row.sparkline_pkr = _sparkline(metal_series.get(metal.series), usdpkr_series, unit, metal.purity_ratio)
            rows.append(row)

    inputs["usdpkr"] = {
        "symbol": fx.PKR_CROSS_SYMBOLS["USD"],
        "rate": round(float(usdpkr), 4) if usdpkr else None,
        "source": usd_raw.source if usd_raw else "none",
        "timestamp_epoch": usdpkr_timestamp,
        "timestamp": datetime.fromtimestamp(usdpkr_timestamp, tz=timezone.utc).isoformat() if usdpkr_timestamp else None,
        "status": usd_raw.status if usd_raw else "UNAVAILABLE",
        "error": usd_raw.error if usd_raw else "no source available",
    }

    usable = [r for r in rows if r.price is not None]
    return {
        "currency": "PKR",
        "count": len(rows),
        "items": [r.to_dict() for r in rows],
        "by_metal": [
            {
                "key": m.key, "symbol": m.symbol, "name": m.name, "type": m.type,
                "purity": m.purity, "fineness": m.fineness, "primary_unit": m.primary_unit,
                "units": [{"unit": UNIT_LABELS[u], "unit_key": u} for u in m.units],
            }
            for m in METALS
        ],
        "unavailable": [r.id for r in rows if r.price is None],
        "inputs": inputs,
        "units": {
            "troy_ounce_grams": TROY_OUNCE_GRAMS,
            "tola_grams": TOLA_GRAMS,
            "definition": "1 tola = 11.6638125 g (Pakistan); 1 troy ounce = 31.1034768 g",
        },
        "derivation": (
            "price = (USD per troy ounce ÷ 31.1034768) × USD/PKR × grams per unit × purity ratio "
            "(22K gold = 24K × 22/24)"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "live_seconds": settings.fx_live_threshold_seconds,
            "aging_seconds": settings.fx_aging_threshold_seconds,
            "stale_seconds": settings.fx_stale_threshold_seconds,
        },
        "priced_count": len(usable),
        "label": "PKR-based data — international parity rates converted at the live USD/PKR rate.",
        "disclaimer": (
            "Derived from the international COMEX front-month price and the interbank USD/PKR rate. "
            "This is NOT the Karachi Sarafa Association retail board: local retail prices additionally "
            "include dealer premiums, making charges, taxes and per-shop margins, so they are usually "
            "higher than the parity value shown here. Information only, not investment advice."
        ),
    }
