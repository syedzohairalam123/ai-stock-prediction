"""
PSX symbol resolution.

Yahoo Finance lists Pakistan Stock Exchange (PSX) companies with a `.KA`
suffix — the bare symbol (`OGDC`) returns *no data at all*, while `OGDC.KA`
returns the real quote/history. This module is the single place that knows
about that convention, so no agent/route/provider has to hardcode it.

Resolution strategy (deterministic, no guessing at the call site):
  * A symbol that already carries a suffix/prefix (`.` `=` `^`) is used as-is.
  * A known PSX symbol is mapped straight to `<TICKER>.KA`.
  * Anything else is tried as-is first, then with `.KA` appended once — this
    keeps US symbols (AAPL) working and still resolves unlisted PSX symbols.

Nothing here invents data; it only selects which symbol string to ask the
provider for. If both candidates fail, the provider still raises, and the
manager still reports UNAVAILABLE.
"""
from __future__ import annotations

#: Yahoo Finance's suffix for Karachi (PSX) listings.
PSX_SUFFIX = ".KA"

#: PSX symbols the app knows about (mirrors the frontend stock universe in
#: `frontend/src/lib/psxMarket.ts`, plus other common KSE names). Membership
#: only affects *how* a symbol is resolved — never whether data is fabricated.
PSX_SYMBOLS: frozenset[str] = frozenset({
    # Exploration & Production
    "OGDC", "PPL", "POL", "MARI",
    # Oil & Gas marketing / refinery
    "PSO", "APL", "SNGP", "SSGC", "ATRL", "NRL", "PRL",
    # Banks
    "HBL", "UBL", "MCB", "ABL", "BAFL", "BAHL", "MEBL", "FABL", "NBP", "BOP",
    "AKBL", "SBL", "JSBL", "BIPL",
    # Fertilizer
    "FFC", "ENGRO", "EFERT", "FATIMA",
    # Cement
    "LUCK", "DGKC", "MLCF", "FCCL", "CHCC", "PIOC", "KOHC", "ACPL",
    # Chemicals
    "ICI", "EPCL", "LOTCHEM", "NICL", "COLG", "SITC",
    # Technology
    "SYS", "NETSOL", "TRG", "TPL", "AVN", "PTC", "AIRLINK",
    # Power
    "HUBC", "KAPCO", "NCPL", "KEL",
    # Textile
    "NML", "ILP", "NCL", "GATM", "KTML",
    # Food / consumer / autos
    "NESTLE", "FFL", "MTL", "INDU", "GHGL", "GHNI", "ISL",
    # Others frequently traded on PSX
    "THALL", "MUGHAL", "ASTL", "ITTEFAQ", "PIAA", "PNSC", "SHEL", "NATF",
})


def is_psx_symbol(ticker: str) -> bool:
    """True when the bare symbol is a known PSX-listed ticker."""
    return (ticker or "").strip().upper() in PSX_SYMBOLS


def symbol_candidates(ticker: str, *, suffix_fallback: bool = True) -> list[str]:
    """Ordered candidate symbols to try against a Yahoo-style provider.

    `suffix_fallback=False` is for calls where an *empty* answer is a valid
    result for a real ticker (e.g. news with no headlines) — there we only
    apply the deterministic mapping and never spend an extra request probing a
    `.KA` variant.
    """
    t = (ticker or "").strip().upper()
    if not t:
        return [t]
    # Already qualified (BRK.B, EURUSD=X, GC=F, ^GSPC, OGDC.KA) — use as-is.
    if any(ch in t for ch in ".=^"):
        return [t]
    if t in PSX_SYMBOLS:
        return [f"{t}{PSX_SUFFIX}"]
    if suffix_fallback:
        return [t, f"{t}{PSX_SUFFIX}"]
    return [t]


def to_yahoo_symbol(ticker: str) -> str:
    """Primary candidate for a ticker (the one to show/cache first)."""
    return symbol_candidates(ticker)[0]
