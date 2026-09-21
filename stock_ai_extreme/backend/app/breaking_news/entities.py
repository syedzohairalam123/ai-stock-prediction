"""
Market entity extraction for Phase 17 (spec §7).

Phase 8 links an article to the **PSX** universe (``symbols.PSX_SYMBOLS``), which
is exactly right for the local desk and exactly wrong for a global breaking feed:
a headline about Nvidia, gold or the Nasdaq would associate with nothing, and
"market impact" could not be measured at all.

This module adds a second, strictly curated layer:

* **Equities** — a fixed list of large, liquid tickers that financial copy names
  by symbol (``NVDA``, ``AAPL``, ``TSLA`` …). A token only counts when it is an
  uppercase word matching a symbol in the list, so the ordinary English words
  that collide with tickers are not picked up.
* **Indices, commodities, FX and crypto** — name and alias driven
  ("S&P 500"/"S&P"/"SPX", "gold", "crude", "bitcoin", "dollar index"), each
  mapping to the provider symbol the Phase 2 layer can actually price.

Nothing here is inferred or generated: every mapping is a hard-coded, reviewable
table, and an entity is only emitted when its pattern really appears in the text.
The result is deliberately separate from ``news_analytics.extract_symbols`` so
Phase 8's behaviour is untouched — this only enriches what Phase 17 stores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .market_impact import ASSET_SYMBOLS, INDEX_SYMBOLS, POLICY_ENTITIES

#: Large, liquid, widely-quoted tickers. Kept short on purpose: a long list starts
#: matching ordinary words ("ALL", "KEY", "NOW"), which is exactly the failure
#: mode ``news_analytics`` documents avoiding for PSX symbols.
GLOBAL_TICKERS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC",
    "NFLX", "AVGO", "ORCL", "CRM", "ADBE", "QCOM", "TXN", "MU", "PYPL", "UBER",
    "JPM", "BAC", "GS", "MS", "WFC", "BRK", "MA", "AXP",
    "XOM", "CVX", "COP", "SLB", "OXY", "BP", "TTE",
    "JNJ", "PFE", "MRK", "LLY", "ABBV", "UNH", "CVS",
    "WMT", "COST", "TGT", "HD", "MCD", "NKE", "SBUX", "DIS",
    "BA", "CAT", "GE", "GM", "HON", "LMT", "RTX",
    "BABA", "TSM", "ASML", "SONY", "TM", "SAP", "SHOP", "COIN", "PLTR", "SNOW",
})

#: Provider symbols for index aliases. Mirrors ``market_impact.INDEX_SYMBOLS`` and
#: covers the labels global copy actually uses.
INDEX_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bs&p\s?500\b|\bs&p\b|\bspx\b|\bstandard & poor'?s\b", re.I), "SPX", "INDEX"),
    (re.compile(r"\bnasdaq\s?100\b|\bnasdaq\b|\bndx\b|\bixic\b", re.I), "NDAQ", "INDEX"),
    (re.compile(r"\bdow\s?jones\b|\bdow\b|\bdjia\b", re.I), "DJI", "INDEX"),
    (re.compile(r"\bftse\s?100\b|\bftse\b", re.I), "FTSE", "INDEX"),
    (re.compile(r"\bdax\b", re.I), "DAX", "INDEX"),
    (re.compile(r"\bnikkei\b|\bn225\b", re.I), "N225", "INDEX"),
    (re.compile(r"\bnifty\b|\bsensex\b", re.I), "NIFTY", "INDEX"),
    (re.compile(r"\bkse[\s-]?100\b|\bkse100\b", re.I), "KSE100", "INDEX"),
    (re.compile(r"\bkse[\s-]?30\b|\bkse30\b", re.I), "KSE30", "INDEX"),
    (re.compile(r"\bkmi[\s-]?30\b|\bkmi30\b", re.I), "KMI30", "INDEX"),
    (re.compile(r"\ball[\s-]?share\b|\ballshr\b", re.I), "ALLSHR", "INDEX"),
)

#: Company name (as written in prose) -> ticker. Financial copy names a company
#: by word far more often than by ticker, so without this an article about
#: "Nvidia" or "Amazon" would associate with nothing. Deliberately limited to
#: unambiguous names: "apple" (the fruit), "target", "visa" and "shell" are left
#: out because they collide with ordinary English far too often, and the
#: single-letter symbols Ford/Visa/Citigroup are reachable only by name.
COMPANY_NAMES: dict[str, str] = {
    "nvidia": "NVDA",
    "microsoft": "MSFT",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "amazon": "AMZN",
    "meta platforms": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "advanced micro devices": "AMD",
    "intel": "INTC",
    "netflix": "NFLX",
    "broadcom": "AVGO",
    "oracle": "ORCL",
    "salesforce": "CRM",
    "qualcomm": "QCOM",
    "paypal": "PYPL",
    "uber": "UBER",
    "jpmorgan": "JPM",
    "goldman sachs": "GS",
    "morgan stanley": "MS",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "exxon": "XOM",
    "chevron": "CVX",
    "boeing": "BA",
    "caterpillar": "CAT",
    "johnson & johnson": "JNJ",
    "pfizer": "PFE",
    "merck": "MRK",
    "eli lilly": "LLY",
    "unitedhealth": "UNH",
    "walmart": "WMT",
    "costco": "COST",
    "mcdonald's": "MCD",
    "nike": "NKE",
    "starbucks": "SBUX",
    "disney": "DIS",
    "alibaba": "BABA",
    "taiwan semiconductor": "TSM",
    "asml": "ASML",
    "sony": "SONY",
    "toyota": "TM",
    "sap": "SAP",
    "shopify": "SHOP",
    "coinbase": "COIN",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "ford": "F",
    "citigroup": "C",
    "citibank": "C",
    "berkshire hathaway": "BRK-B",
}

#: Name/alias -> (entity value, entity type). Ordered longest-alias-first at
#: match time so "natural gas" wins over "gas".
NAME_ENTITIES: dict[str, tuple[str, str]] = {
    # commodities
    "gold": ("GOLD", "COMMODITY"),
    "bullion": ("GOLD", "COMMODITY"),
    "silver": ("SILVER", "COMMODITY"),
    "crude oil": ("OIL", "COMMODITY"),
    "crude": ("OIL", "COMMODITY"),
    "brent": ("BRENT", "COMMODITY"),
    "wti": ("OIL", "COMMODITY"),
    "natural gas": ("NATURALGAS", "COMMODITY"),
    "copper": ("COPPER", "COMMODITY"),
    "platinum": ("PLATINUM", "COMMODITY"),
    # crypto
    "bitcoin": ("BTC", "CRYPTO"),
    "ethereum": ("ETH", "CRYPTO"),
    "solana": ("SOL", "CRYPTO"),
    "dogecoin": ("DOGE", "CRYPTO"),
    "ripple": ("XRP", "CRYPTO"),
    # fx
    "dollar index": ("DXY", "FOREX"),
    "dxy": ("DXY", "FOREX"),
    "euro": ("EUR", "FOREX"),
    "yen": ("JPY", "FOREX"),
    "sterling": ("GBP", "FOREX"),
    "pound": ("GBP", "FOREX"),
    "rupee": ("PKR", "FOREX"),
    "interbank": ("PKR", "FOREX"),
    # rates / policy actors that move markets
    "federal reserve": ("FED", "INDEX"),
    "fed": ("FED", "INDEX"),
    "ecb": ("ECB", "INDEX"),
    "opec": ("OPEC", "INDEX"),
    "imf": ("IMF", "INDEX"),
    "state bank": ("SBP", "INDEX"),
    "sbp": ("SBP", "INDEX"),
    "secp": ("SECP", "INDEX"),
}

#: Placeholder entity values that are policy actors, not priceable instruments.
#: They still matter for scoring (importance, association) but must never be sent
#: to a market-data provider, so they are excluded from impact targets. Single
#: source of truth lives next to the symbol tables in :mod:`market_impact`.
NON_PRICEABLE_ENTITIES: frozenset[str] = POLICY_ENTITIES

#: Only 2–6 letter uppercase tokens can be a quoted ticker. Deliberately \>= 2 so
#: a stray "A" or "I" in a headline is never read as a symbol.
_UPPER_TOKEN_RE = re.compile(r"\b[A-Z]{2,6}\b")


def _alias_pattern(alias: str) -> re.Pattern[str]:
    """Word-bounded, case-insensitive matcher for one alias.

    Plain substring matching is not good enough here: "gold" would fire on
    "Goldman", "euro" on "Europe" and "pound" on "compound", all of which are
    common in financial copy. The boundaries are letter-only rather than ``\\b``
    so an alias still matches inside hyphenated text ("dollar-index", "crude-oil").
    """
    return re.compile(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", re.I)


#: Compiled once at import time: matching runs on every ingested article, so the
#: alias table must not be re-escaped per call.
_NAME_ENTITY_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (_alias_pattern(alias), entity, kind) for alias, (entity, kind) in NAME_ENTITIES.items()
)


@dataclass(frozen=True)
class MarketEntity:
    """One market instrument an article actually mentions."""

    entity: str
    entity_type: str
    matched: str
    #: True when the Phase 2 provider layer can be expected to price it.
    priceable: bool

    def as_dict(self) -> dict:
        return {
            "entity": self.entity,
            "entity_type": self.entity_type,
            "matched": self.matched,
            "priceable": self.priceable,
        }


def provider_symbol(entity: str, entity_type: str) -> str | None:
    """The provider symbol for an entity, or ``None`` when not priceable."""
    if entity in NON_PRICEABLE_ENTITIES:
        return None
    if entity_type == "INDEX":
        return INDEX_SYMBOLS.get(entity)
    return ASSET_SYMBOLS.get(entity, entity if entity_type in {"COMMODITY", "FOREX", "CRYPTO"} else None)


def extract_market_entities(text: str, *, max_entities: int = 12) -> list[MarketEntity]:
    """Every curated market entity present in ``text``.

    Order of evidence: index patterns, then named instruments, then uppercase
    tickers. Ties resolve to the first match, so the result is deterministic for a
    given input string.
    """
    if not text:
        return []

    found: dict[str, MarketEntity] = {}

    for pattern, label, kind in INDEX_PATTERNS:
        match = pattern.search(text)
        if match:
            found.setdefault(label, MarketEntity(label, kind, match.group(0), provider_symbol(label, kind) is not None))

    lowered = text.lower()
    for pattern, entity, kind in _NAME_ENTITY_PATTERNS:
        match = pattern.search(text)
        if match:
            found.setdefault(
                entity,
                MarketEntity(entity, kind, match.group(0).lower(), provider_symbol(entity, kind) is not None),
            )

    for name, ticker in COMPANY_NAMES.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            found.setdefault(ticker, MarketEntity(ticker, "STOCK", name, True))

    for token in _UPPER_TOKEN_RE.findall(text):
        if token in GLOBAL_TICKERS:
            found.setdefault(token, MarketEntity(token, "STOCK", token, True))

    return list(found.values())[:max_entities]


def entity_types_for(entities: Iterable[MarketEntity | str]) -> dict[str, str]:
    """``{entity: type}`` map for storage on a breaking row."""
    out: dict[str, str] = {}
    for entry in entities:
        if isinstance(entry, MarketEntity):
            out[entry.entity] = entry.entity_type
        else:
            out[str(entry)] = "STOCK"
    return out


__all__ = [
    "MarketEntity",
    "COMPANY_NAMES",
    "GLOBAL_TICKERS",
    "INDEX_PATTERNS",
    "NAME_ENTITIES",
    "NON_PRICEABLE_ENTITIES",
    "extract_market_entities",
    "entity_types_for",
    "provider_symbol",
]
