"""
Category + sub-tag system for discovery (spec §5, §6, §13).

Two kinds of tags exist and they are never confused with each other:

``derived`` tags
    taken straight from a real attribute an entity already has — a PSX stock's
    curated sector group (``popular_stocks.POPULAR_PSX_STOCKS``), its profile
    sector/industry, a forecast event's source category, a topic's engine
    category. Nothing is inferred.

``lexicon`` tags
    a deterministic keyword → tag match applied to an entity's *name/title*
    (``Technology`` matches "technology" in a headline topic, ``Bitcoin``
    matches a market question). Same input text ⇒ same tags; there is no model
    and no randomness.

Both kinds end up in the entity's ``tags`` list, so clicking a tag anywhere
filters exactly the entities that carry it — a *Technology* tag therefore
reaches the stock SYS, a technology news topic and a tech forecast event
without ever matching something unrelated (spec §13).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from .config import discovery_settings

#: Canonical category vocabulary (spec §5). Loaded from settings so the whole
#: vocabulary is one configurable value, not a constant sprinkled around.
CATEGORIES: tuple[str, ...] = tuple(discovery_settings.categories)

_CATEGORY_LOOKUP = {c.lower(): c for c in CATEGORIES}

#: Fallback map for the labels other modules in this app already use
#: (Phase 17 topic categories, Phase 14 forecast categories).
_CATEGORY_ALIASES: Dict[str, str] = {
    "equity": "Stocks",
    "equities": "Stocks",
    "share market": "Stocks",
    "psx": "Stocks",
    "global equity": "Stocks",
    "market theme": "Finance",
    "keyword": "Finance",
    "index": "Finance",
    "indices": "Finance",
    "digital assets": "Crypto",
    "metal": "Commodities",
    "metals": "Commodities",
    "energy": "Commodities",
    "currency": "Forex",
    "currencies": "Forex",
    "fx": "Forex",
    "world": "Geopolitics",
    "international": "Geopolitics",
    "government": "Politics",
    "business": "Finance",
    "markets": "Finance",
    "technology": "Tech",
    "tech news": "Tech",
}


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Map any case/alias of a known category onto the canonical one."""
    if not value:
        return None
    text = str(value).strip().lower()
    if text in _CATEGORY_LOOKUP:
        return _CATEGORY_LOOKUP[text]
    alias = _CATEGORY_ALIASES.get(text)
    return alias or None


# ---------------------------------------------------------------------------
# Sub-tag lexicon (spec §6 examples: Elections / Banking / Oil & Gas / …)
# ---------------------------------------------------------------------------

#: ``(tag, keywords)`` — a tag is applied when any keyword appears in the
#: entity's name/title as a whole word (or word phrase), case-insensitive.
#: Curated, reviewable and finite: a tag list nobody can read is not a
#: taxonomy. Matching is done with ``\\bkeyword\\b`` regexes, so ``AI`` never
#: matches "airways" and ``oil`` never matches "boiler".
TAG_LEXICON: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Politics
    ("Elections", ("election", "elections", "poll", "polls", "ballot", "vote", "voting", "primary", "primaries")),
    ("Midterms", ("midterm", "midterms")),
    ("Global Elections", ("parliament", "senate", "congress", "prime minister", "president", "governor")),
    # Finance / Economy
    ("Banking", ("bank", "banks", "banking", "lender", "lenders")),
    ("Interest Rates", ("interest rate", "interest rates", "rate cut", "rate hike", "central bank", "fed")),
    ("Inflation", ("inflation", "cpi", "consumer prices")),
    ("Earnings", ("earnings", "profit", "profits", "revenue", "quarterly results", "eps")),
    ("IPO", ("ipo", "public offering")),
    ("Oil & Gas", ("oil", "gas", "crude", "petroleum", "refinery", "refineries", "ogdc")),
    ("Cement", ("cement",)),
    ("Technology", ("technology", "software", "tech", "cloud", "semiconductor", "digital", "internet")),
    ("AI", ("ai", "artificial intelligence", "chatbot", "llm", "machine learning", "nvidia", "openai")),
    ("Energy", ("energy", "power", "electricity", "renewable", "solar", "turbine")),
    ("Automobiles", ("auto", "autos", "cars", "vehicle", "vehicles", "motor")),
    ("Pharma", ("pharma", "drugs", "drug", "vaccine", "medicine", "healthcare")),
    ("Fertilizer", ("fertilizer", "fertiliser", "urea")),
    ("Textile", ("textile", "textiles", "garment", "fabrics")),
    ("Aviation", ("airline", "airlines", "aviation", "airport", "aircraft")),
    ("Telecom", ("telecom", "mobile", "broadband", "5g")),
    # Crypto
    ("Bitcoin", ("bitcoin", "btc")),
    ("Ethereum", ("ethereum", "ether", "eth")),
    ("DeFi", ("defi", "decentralized finance", "staking")),
    ("Altcoins", ("altcoin", "altcoins", "solana", "ripple", "xrp", "cardano", "dogecoin")),
    # Commodities
    ("Gold", ("gold", "xau", "bullion")),
    ("Silver", ("silver", "xag")),
    ("Crude Oil", ("brent", "wti", "oil price")),
    ("Natural Gas", ("natural gas", "lng", "gas price")),
    # Forex
    ("USD", ("usd", "dollar", "dollars", "greenback")),
    ("PKR", ("pkr", "rupee", "rupees")),
    ("EUR", ("euro", "euros", "eur/usd")),
    # Geopolitics
    ("War & Conflict", ("war", "ceasefire", "conflict", "military", "invasion", "troops")),
    ("Sanctions", ("sanction", "sanctions", "embargo", "tariff", "tariffs", "trade war")),
    # Sports / Esports / Culture
    ("Cricket", ("cricket", "icc", "world cup")),
    ("Football", ("football", "soccer", "uefa", "fifa")),
    ("Basketball", ("basketball", "nba")),
    ("Esports", ("esports", "counter-strike", "valorant", "league of legends", "gaming")),
    ("Awards", ("oscar", "oscars", "grammy", "grammys", "emmy", "awards")),
)

#: Keyword → tag, longest keyword first so "interest rate" beats "fed".
_TAG_BY_KEYWORD: List[tuple[str, str]] = sorted(
    ((keyword, tag) for tag, keywords in TAG_LEXICON for keyword in keywords),
    key=lambda kv: -len(kv[0]),
)
_COMPILED: List[tuple["re.Pattern[str]", str]] = [
    # `s?` → "bank" also matches "banks", "election" matches "elections":
    # the sub-tag vocabulary people actually type is plural more often than
    # not, and a singular-only matcher would silently miss it.
    (re.compile(rf"\b{re.escape(keyword)}s?\b", re.IGNORECASE), tag)
    for keyword, tag in _TAG_BY_KEYWORD
]


def normalize_tag(value: str) -> str:
    """Canonical display form of a tag: strip, collapse spaces, title-case
    ordinary words while leaving short acronyms (BTC, PSX, EUR) alone."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    if text.isupper() and len(text) <= 5:
        return text
    return " ".join(part.capitalize() if part.islower() else part for part in text.split())


def tags_from_name(name: str) -> List[str]:
    """Deterministic lexicon tags implied by an entity's name/title."""
    if not name:
        return []
    found: List[str] = []
    for pattern, tag in _COMPILED:
        if pattern.search(name) and tag not in found:
            found.append(tag)
    return found


def tags_from_sector_groups(category_map: Dict[str, Iterable[str]]) -> Dict[str, str]:
    """Invert ``{group: [symbols]}`` into ``{symbol: group tag}``.

    Uses the real curated PSX sector groups from ``popular_stocks`` (Banking,
    Cement, Oil & Gas, Technology, …) — a stock's group is a fact about the
    universe, not a guess from its price.
    """
    inverted: Dict[str, str] = {}
    for group, symbols in category_map.items():
        tag = normalize_tag(str(group).replace("_", " "))
        for symbol in symbols:
            inverted.setdefault(str(symbol).upper(), tag)
    return inverted


def entity_category_and_tags(
    *,
    category: Optional[str],
    tags: Iterable[str] = (),
    name: str = "",
    extra_tags: Iterable[str] = (),
) -> tuple[str, List[str]]:
    """Resolve the canonical category + de-duplicated tag list for an entity."""
    resolved = (
        normalize_category(category)
        or normalize_category(_lexicon_hint(name))
        or "Finance"
    )
    merged: List[str] = []
    for tag in list(tags) + list(extra_tags) + tags_from_name(name):
        clean = normalize_tag(tag)
        if clean and clean.lower() != resolved.lower() and clean not in merged:
            merged.append(clean)
    return resolved, merged


#: Tag → category, used before the word hints below. A news topic literally
#: named "GOLD" therefore lands in Commodities and "BITCOIN" in Crypto — the
#: classification follows the same lexicon that produces the sub-tags, so a
#: tag and its category can never disagree.
_TAG_CATEGORY: Dict[str, str] = {
    "Gold": "Commodities",
    "Silver": "Commodities",
    "Crude Oil": "Commodities",
    "Natural Gas": "Commodities",
    "Bitcoin": "Crypto",
    "Ethereum": "Crypto",
    "DeFi": "Crypto",
    "Altcoins": "Crypto",
    "USD": "Forex",
    "PKR": "Forex",
    "EUR": "Forex",
    "Elections": "Politics",
    "Midterms": "Politics",
    "Global Elections": "Politics",
    "War & Conflict": "Geopolitics",
    "Sanctions": "Geopolitics",
    "Cricket": "Sports",
    "Football": "Sports",
    "Basketball": "Sports",
    "Esports": "Esports",
    "Awards": "Culture",
    "AI": "Tech",
    "Technology": "Tech",
    "Earnings": "Stocks",
    "IPO": "Stocks",
}


def _lexicon_hint(name: str) -> Optional[str]:
    """Which category a title most plausibly belongs to.

    First the tag lexicon (deterministic, and consistent with the sub-tags the
    same title gets), then keyword hints, then None → caller default.
    """
    for tag in tags_from_name(name):
        mapped = _TAG_CATEGORY.get(tag)
        if mapped:
            return mapped
    lowered = name.lower()
    hints: Dict[str, tuple[str, ...]] = {
        "Politics": ("election", "president", "congress", "parliament", "prime minister", "senate"),
        "Sports": ("nba", "nfl", "football", "cricket", "match", "league", "tournament", "world cup"),
        "Crypto": ("bitcoin", "ethereum", "crypto", "token", "defi", "solana"),
        "Esports": ("esports", "counter-strike", "league of legends", "valorant"),
        "Geopolitics": ("war", "ceasefire", "nato", "ukraine", "gaza", "sanctions", "missile"),
        "Tech": ("ai model", "software", "iphone", "data center", "semiconductor"),
        "Culture": ("oscar", "grammy", "movie", "album", "box office"),
        "Economy": ("gdp", "inflation", "recession", "unemployment", "jobs report"),
        "Commodities": ("gold price", "crude oil", "brent", "copper", "wheat"),
        "Forex": ("exchange rate", "currency", "eur/usd", "usdpkr"),
        "Stocks": ("shares", "stock", "ipo", "earnings", "buyback", "dividend"),
    }
    for category, words in hints.items():
        if any(word in lowered for word in words):
            return category
    return None


def taxonomy_from(entities: Iterable[dict]) -> dict:
    """Build the category/tag navigation model from the real entity set.

    Counts are *entity counts* — how many discoverable entities a category or
    tag actually has right now. Nothing is estimated.
    """
    categories: Dict[str, int] = {c: 0 for c in CATEGORIES}
    tags: Dict[str, int] = {}
    tag_categories: Dict[str, set] = {}
    for entity in entities:
        cat = entity.get("category") or "Finance"
        categories[cat] = categories.get(cat, 0) + 1
        for tag in entity.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
            tag_categories.setdefault(tag, set()).add(cat)
    return {
        "categories": [{"name": name, "count": count} for name, count in categories.items()],
        "tags": [
            {"name": name, "count": count, "categories": sorted(tag_categories.get(name, set()))}
            for name, count in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0].lower()))
        ],
    }


__all__ = [
    "CATEGORIES",
    "TAG_LEXICON",
    "normalize_category",
    "normalize_tag",
    "tags_from_name",
    "tags_from_sector_groups",
    "entity_category_and_tags",
    "taxonomy_from",
]
