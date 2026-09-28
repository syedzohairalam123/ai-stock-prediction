"""
Phase 20 — instrument resolution.

The Quick Order ticket must be context-aware: opened from a stock page it is a
stock ticket, from the crypto page a crypto ticket, from a Phase 14 forecast a
*probability* ticket. This module is the single place that decides what a
symbol actually is, so no route has to guess.

Classification is **shape-based**, deterministic and documented — it never
invents a fact about a symbol it cannot verify. A symbol it cannot classify is
treated as a STOCK, which is what the provider layer assumes anyway.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..security import validate_ticker


class InstrumentKind(str, Enum):
    STOCK = "STOCK"
    INDEX = "INDEX"
    CRYPTO = "CRYPTO"
    COMMODITY = "COMMODITY"
    FOREX = "FOREX"
    FORECAST = "FORECAST"


class QuoteMode(str, Enum):
    """How the ticket talks about the instrument's reference value."""

    PRICE = "PRICE"              # financial quote terminology (price/bid/ask)
    PROBABILITY = "PROBABILITY"  # forecast-event terminology (YES/NO, %)


#: Yahoo's crypto convention: `<BASE>-<QUOTE>`, e.g. BTC-USD, ETH-USD.
_CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}-(USD|USDT|EUR|GBP|PKR|BTC|ETH)$")
#: Yahoo's FX convention: `<PAIR>=X`, e.g. EURUSD=X, USDPKR=X.
_FX_RE = re.compile(r"^[A-Z]{3,8}=X$")
#: Yahoo's futures convention: `<ROOT>=F`, e.g. GC=F, SI=F, CL=F.
_FUTURES_RE = re.compile(r"^[A-Z0-9]{1,6}=F$")
#: Yahoo's index convention: `^<NAME>`, e.g. ^GSPC, ^VIX.
_INDEX_RE = re.compile(r"^\^[A-Z0-9]{1,10}$")

#: Instrument families the ticket can render. Anything else is refused rather
#: than silently shown as something it is not.
SUPPORTED_KINDS = frozenset(k.value for k in InstrumentKind)

#: Order sides accepted per quote mode. Deliberately separate vocabularies:
#: a forecast event is not "bought" or "sold" and must never read like one.
SIDES_BY_MODE: dict[QuoteMode, tuple[str, ...]] = {
    QuoteMode.PRICE: ("BUY", "SELL"),
    QuoteMode.PROBABILITY: ("YES", "NO"),
}

ORDER_TYPES = ("MARKET", "LIMIT")

AMOUNT_MODES = ("NOTIONAL", "QUANTITY")

#: Forecast instruments are addressed as `FORECAST:<marketId>`.
FORECAST_PREFIX = "FORECAST:"


@dataclass(frozen=True)
class PaperInstrument:
    """A resolved, quotable instrument plus everything the ticket needs to
    label it honestly."""

    symbol: str
    kind: InstrumentKind
    display_name: str
    quote_mode: QuoteMode = QuoteMode.PRICE
    currency: Optional[str] = None
    #: Market-data symbol actually asked of the provider (may differ from the
    #: user-facing symbol — e.g. PSX resolution happens inside the provider).
    provider_symbol: str = ""
    price_precision: int = 4
    quantity_precision: int = 8
    #: Phase 14 forecast linkage (only populated for FORECAST instruments).
    market_id: Optional[str] = None
    close_time: Optional[str] = None
    question: Optional[str] = None
    category: Optional[str] = None
    source_url: Optional[str] = None
    #: True when the instrument comes from an external provider vs. this app's
    #: own recorded data. Kept explicit for the risk panel.
    external_source: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def is_forecast(self) -> bool:
        return self.kind is InstrumentKind.FORECAST

    @property
    def sides(self) -> tuple[str, ...]:
        return SIDES_BY_MODE[self.quote_mode]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "kind": self.kind.value,
            "displayName": self.display_name,
            "quoteMode": self.quote_mode.value,
            "currency": self.currency,
            "providerSymbol": self.provider_symbol or self.symbol,
            "pricePrecision": self.price_precision,
            "quantityPrecision": self.quantity_precision,
            "marketId": self.market_id,
            "closeTime": self.close_time,
            "question": self.question,
            "category": self.category,
            "sourceUrl": self.source_url,
            "externalSource": self.external_source,
            "sides": list(self.sides),
            "orderTypes": list(ORDER_TYPES),
            "amountModes": list(AMOUNT_MODES),
            "isForecast": self.is_forecast,
            "notes": list(self.notes),
            "paper": True,
            "simulationOnly": True,
        }


def classify_symbol(symbol: str) -> InstrumentKind:
    """Deterministic classification from the symbol's shape alone."""
    s = (symbol or "").strip().upper()
    if s.startswith(FORECAST_PREFIX):
        return InstrumentKind.FORECAST
    if _FX_RE.match(s):
        return InstrumentKind.FOREX
    if _CRYPTO_RE.match(s):
        return InstrumentKind.CRYPTO
    if _FUTURES_RE.match(s):
        return InstrumentKind.COMMODITY
    if _INDEX_RE.match(s):
        return InstrumentKind.INDEX
    return InstrumentKind.STOCK


_DISPLAY_SUFFIX: dict[InstrumentKind, str] = {
    InstrumentKind.STOCK: "Equity",
    InstrumentKind.INDEX: "Index",
    InstrumentKind.CRYPTO: "Crypto pair",
    InstrumentKind.COMMODITY: "Futures / commodity",
    InstrumentKind.FOREX: "FX pair",
    InstrumentKind.FORECAST: "Forecast event",
}

_QUANTITY_PRECISION: dict[InstrumentKind, int] = {
    InstrumentKind.CRYPTO: 8,
    InstrumentKind.FOREX: 2,
    InstrumentKind.FORECAST: 2,
}


def resolve_instrument(
    symbol: str,
    kind: Optional[str] = None,
    *,
    display_name: Optional[str] = None,
    currency: Optional[str] = None,
) -> PaperInstrument:
    """Resolve a symbol into a `PaperInstrument`.

    `kind` is an optional *hint* from the client (the page the ticket was
    opened from). It is accepted only when it is a real kind and does not
    contradict a FORECAST id; otherwise the shape-based classification wins —
    the client can describe the context but cannot lie about what an
    instrument fundamentally is.

    Raises `ValueError` for a malformed symbol so routes can turn it into a
    clean 4xx instead of reaching a provider with junk.
    """
    raw = (symbol or "").strip()
    if not raw:
        raise ValueError("A symbol is required.")

    if raw.upper().startswith(FORECAST_PREFIX):
        market_id = raw[len(FORECAST_PREFIX):].strip()
        if not market_id:
            raise ValueError("A forecast instrument needs a market id.")
        return PaperInstrument(
            symbol=f"{FORECAST_PREFIX}{market_id}",
            kind=InstrumentKind.FORECAST,
            display_name=display_name or f"Forecast event {market_id}",
            quote_mode=QuoteMode.PROBABILITY,
            currency=None,
            provider_symbol=market_id,
            price_precision=2,
            quantity_precision=2,
            market_id=market_id,
        )

    ticker = validate_ticker(raw)  # raises ValueError on malformed input
    resolved_kind = classify_symbol(ticker)
    if kind:
        hinted = kind.strip().upper()
        if hinted not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported instrument kind: {kind}")
        # A hint may only refine a plain STOCK classification (e.g. the PSX
        # index page). It may never downgrade a recognised FORECAST id.
        if hinted != InstrumentKind.FORECAST.value and (
            resolved_kind is InstrumentKind.STOCK or hinted == resolved_kind.value
        ):
            resolved_kind = InstrumentKind(hinted)

    return PaperInstrument(
        symbol=ticker,
        kind=resolved_kind,
        display_name=display_name or f"{ticker} · {_DISPLAY_SUFFIX[resolved_kind]}",
        quote_mode=QuoteMode.PRICE,
        currency=currency,
        provider_symbol=ticker,
        quantity_precision=_QUANTITY_PRECISION.get(resolved_kind, 8),
    )


def is_supported_kind(kind: str) -> bool:
    return (kind or "").strip().upper() in SUPPORTED_KINDS
