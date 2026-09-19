"""
Phase 7 — Forex center (PKR-based, real data).

Every quote here comes from a real source; nothing is simulated. The primary
source is Yahoo Finance, which publishes live bid/ask for all eight required
currencies against PKR (`USDPKR=X`, `GBPPKR=X`, …). When Yahoo cannot answer for
a given currency, the module falls back to the keyless ExchangeRate-API daily
rates and **says so** in `source`/`data_mode`, because a daily publication must
never be presented as a live rate.

Validation is the part that matters here (spec N). Real feeds are messy in ways
that would otherwise reach the screen:

  * Yahoo returns bid/ask for USD-quoted majors (EURUSD, GBPUSD, AUDUSD) with the
    two sides *inverted* (bid > ask). Those levels are rejected outright rather
    than "fixed" — an invented spread is worse than no spread.
  * Missing, zero and negative sides are dropped individually.
  * `NaN`/`Infinity` never survive the trip (`_as_float` in fx_rates).

`mid` therefore falls back to the source's own traded price when a valid
bid/ask pair does not exist, and `bid`/`ask`/`spread` stay `null` with a reason
the UI can show.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .config import settings
from .logging_config import get_logger
from .providers import fx_rates as fx

logger = get_logger("neural_market.forex")

QUOTE_CURRENCY = "PKR"

#: The eight currencies the forex center is required to cover, with real names.
SUPPORTED_CURRENCIES: dict[str, str] = {
    "USD": "US Dollar",
    "GBP": "British Pound Sterling",
    "EUR": "Euro",
    "AED": "UAE Dirham",
    "SAR": "Saudi Riyal",
    "AUD": "Australian Dollar",
    "CAD": "Canadian Dollar",
    "JPY": "Japanese Yen",
}

#: ISO-4217 codes accepted when validating a pair. Kept deliberately small and
#: explicit: this is a validation allow-list, not a currency database.
VALID_CURRENCY_CODES: frozenset[str] = frozenset(
    set(SUPPORTED_CURRENCIES)
    | {
        # the local currency plus the majors/locals users realistically search
        "PKR", "CHF", "CNY", "HKD", "NZD", "SEK", "NOK", "DKK", "SGD", "INR",
        "TRY", "ZAR", "KWD", "QAR", "OMR", "BHD", "MYR", "THB", "IDR", "BDT",
        "LKR", "AFN", "IRR", "JOD", "EGP", "RUB", "BRL", "MXN", "KRW", "TWD",
    }
)

DATA_MODES = ("LIVE", "DELAYED", "DEMO", "UNAVAILABLE")
FRESHNESS_STATES = ("FRESH", "AGING", "STALE", "UNKNOWN")

#: Only timestamps inside this window are believed. Anything else is treated as
#: "no timestamp" instead of a value that would make freshness look harmless.
_MIN_EPOCH = 946_684_800  # 2000-01-01


def is_valid_currency(code: str) -> bool:
    return isinstance(code, str) and code.strip().upper() in VALID_CURRENCY_CODES


def get_data_freshness(
    timestamp_epoch: Optional[float],
    *,
    now_epoch: Optional[float] = None,
    fresh_seconds: Optional[int] = None,
    aging_seconds: Optional[int] = None,
) -> str:
    """FRESH / AGING / STALE / UNKNOWN for a source timestamp (spec O).

    Thresholds are configurable (`fx_live_threshold_seconds`,
    `fx_aging_threshold_seconds`) so a caller — or an env var — can tighten them
    without touching the UI. A missing or implausible timestamp is UNKNOWN, never
    silently treated as fresh.
    """
    if timestamp_epoch is None:
        return "UNKNOWN"
    try:
        ts = float(timestamp_epoch)
    except (TypeError, ValueError):
        return "UNKNOWN"
    now = float(now_epoch if now_epoch is not None else fx.utc_now_epoch())
    if ts < _MIN_EPOCH or ts > now + 86400:
        return "UNKNOWN"
    age = now - ts
    if age < 0:
        return "FRESH"
    fresh = settings.fx_live_threshold_seconds if fresh_seconds is None else fresh_seconds
    aging = settings.fx_aging_threshold_seconds if aging_seconds is None else aging_seconds
    if age <= fresh:
        return "FRESH"
    if age <= aging:
        return "AGING"
    return "STALE"


def classify_data_mode(
    timestamp_epoch: Optional[float],
    granularity: str,
    *,
    now_epoch: Optional[float] = None,
    has_value: bool = True,
) -> str:
    """LIVE / DELAYED / DEMO / UNAVAILABLE, decided by what the source really is.

    A source that publishes daily is never LIVE. A realtime source is only LIVE
    while its own timestamp is inside the live window; past that it is DELAYED,
    and past the stale window it is UNAVAILABLE (a rate that old must not be
    shown as a current one). DEMO exists for an explicitly-requested demo feed —
    the real sources here never produce it.
    """
    if not has_value:
        return "UNAVAILABLE"
    if granularity != fx.GRANULARITY_REALTIME:
        # Daily (or slower) publication that is still within the stale window.
        age_state = get_data_freshness(timestamp_epoch, now_epoch=now_epoch)
        return "UNAVAILABLE" if age_state == "STALE" else "DELAYED"
    state = get_data_freshness(timestamp_epoch, now_epoch=now_epoch)
    if state == "FRESH":
        return "LIVE"
    if state == "AGING":
        return "DELAYED"
    if state == "STALE":
        # Still real, still shown — but only while it is inside the stale window.
        # Past that it is refused outright rather than presented as a current rate.
        now = float(now_epoch if now_epoch is not None else fx.utc_now_epoch())
        age = now - float(timestamp_epoch or 0)
        return "DELAYED" if age <= settings.fx_stale_threshold_seconds else "UNAVAILABLE"
    # UNKNOWN timestamp: the value is real but undated, so it cannot be called live.
    return "DELAYED"


@dataclass
class ForexQuote:
    """One currency pair, exactly as the API exposes it (spec B).

    Raw numeric values only — no display formatting lives in the model.
    """

    symbol: str
    base_currency: str
    quote_currency: str
    name: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    spread: Optional[float] = None
    spread_percent: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    timestamp: Optional[str] = None
    timestamp_epoch: Optional[int] = None
    source: str = "none"
    data_mode: str = "UNAVAILABLE"
    freshness: str = "UNKNOWN"
    previous_close: Optional[float] = None
    granularity: str = fx.GRANULARITY_REALTIME
    #: why bid/ask are missing (inverted, zero, absent) — shown, not hidden
    bid_ask_note: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_bid_ask(
    bid: Optional[float], ask: Optional[float]
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[str]]:
    """(bid, ask, mid, spread, spread_percent, note) — safely.

    Returns only what the source actually published and is internally
    consistent. `bid > ask` is rejected as a pair (with a note explaining why),
    which is exactly what Yahoo does for USD-quoted majors; keeping that would
    mean showing a negative spread as if it were tradable.
    """
    if bid is not None and (not _finite_positive(bid)):
        bid = None
    if ask is not None and (not _finite_positive(ask)):
        ask = None

    if bid is None or ask is None:
        missing = "bid" if bid is None else "ask"
        return bid, ask, None, None, None, f"{missing} unavailable from source"

    if bid > ask:
        return None, None, None, None, None, (
            f"source quoted bid {bid} > ask {ask} (inverted) — rejected rather than shown as a spread"
        )

    mid = (bid + ask) / 2
    spread = ask - bid
    spread_percent = (spread / mid * 100) if mid else None
    return bid, ask, round(mid, 6), round(spread, 6), round(spread_percent, 6) if spread_percent else None, None


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number > 0 and number == number and number not in (float("inf"), float("-inf"))


def build_quote(
    currency: str,
    raw: Optional[fx.RawQuote],
    *,
    fallback_rate: Optional[float] = None,
    fallback_epoch: Optional[float] = None,
    now_epoch: Optional[float] = None,
) -> ForexQuote:
    """Turn one raw source quote (or a fallback cross rate) into a validated quote."""
    currency = currency.strip().upper()
    symbol = f"{currency}/{QUOTE_CURRENCY}"
    if not is_valid_currency(currency) or not is_valid_currency(QUOTE_CURRENCY):
        raise ValueError(f"invalid currency code in pair {symbol!r}")

    name = SUPPORTED_CURRENCIES.get(currency, currency)
    quote = ForexQuote(symbol=symbol, base_currency=currency, quote_currency=QUOTE_CURRENCY, name=name)

    if raw is not None and raw.status != "UNAVAILABLE":
        bid, ask, mid, spread, spread_percent, note = normalize_bid_ask(raw.bid, raw.ask)
        quote.bid, quote.ask, quote.spread, quote.spread_percent = bid, ask, spread, spread_percent
        quote.bid_ask_note = note
        quote.previous_close = raw.previous_close if _finite_positive(raw.previous_close) else None
        # Prefer the published bid/ask midpoint; fall back to the source's own
        # traded price. Both are real published numbers, never an average we made up.
        reference = mid if mid is not None else (raw.price if _finite_positive(raw.price) else None)
        quote.mid = round(reference, 6) if reference is not None else None
        quote.timestamp_epoch = raw.timestamp_epoch
        quote.source = raw.source
        quote.granularity = raw.granularity
        if raw.price is None and reference is not None:
            quote.mid = round(reference, 6)
        if quote.mid is None:
            quote.data_mode = "UNAVAILABLE"
            quote.error = raw.error or "source published no usable price"
            return quote
    elif fallback_rate is not None and _finite_positive(fallback_rate):
        # Daily cross rate from the keyless ExchangeRate-API feed.
        quote.mid = round(float(fallback_rate), 6)
        quote.source = fx.SOURCE_ERAPI
        quote.granularity = fx.GRANULARITY_DAILY
        quote.timestamp_epoch = int(fallback_epoch) if fallback_epoch else None
        quote.bid_ask_note = "no bid/ask published by this source (daily reference rate)"
        if raw is not None and raw.error:
            quote.error = raw.error
    else:
        quote.data_mode = "UNAVAILABLE"
        quote.freshness = "UNKNOWN"
        quote.source = raw.source if raw is not None else fx.SOURCE_ERAPI
        quote.bid_ask_note = "no source could price this pair"
        quote.error = (raw.error if raw is not None else None) or "no data available"
        return quote

    # Change is measured against the source's own previous close.
    if quote.previous_close and quote.mid is not None:
        quote.change = round(quote.mid - quote.previous_close, 6)
        quote.change_percent = round((quote.change / quote.previous_close) * 100, 6)

    if quote.timestamp_epoch:
        quote.timestamp = datetime.fromtimestamp(quote.timestamp_epoch, tz=timezone.utc).isoformat()

    quote.freshness = get_data_freshness(quote.timestamp_epoch, now_epoch=now_epoch)
    quote.data_mode = classify_data_mode(
        quote.timestamp_epoch, quote.granularity, now_epoch=now_epoch, has_value=quote.mid is not None
    )
    return quote


async def build_forex_quotes(
    currencies: Optional[Iterable[str]] = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """The full forex payload: quotes + provenance + honest per-pair failures."""
    wanted = [c.strip().upper() for c in (currencies or SUPPORTED_CURRENCIES.keys())]
    unknown = [c for c in wanted if not is_valid_currency(c)]

    symbols = {c: fx.PKR_CROSS_SYMBOLS[c] for c in wanted if c in fx.PKR_CROSS_SYMBOLS}
    raws = await fx.yahoo_quotes(list(symbols.values()), force_refresh=force_refresh)

    # Only reach for the daily fallback if at least one primary quote is missing,
    # so a healthy live run never pays for a second source.
    needs_fallback = any(
        raws.get(sym) is None or raws[sym].status == "UNAVAILABLE" for sym in symbols.values()
    ) or any(c not in fx.PKR_CROSS_SYMBOLS for c in wanted)

    fallback_rates: Optional[dict[str, Any]] = None
    fallback_error: Optional[str] = None
    if needs_fallback:
        try:
            fallback_rates = await fx.usd_currency_rates(force_refresh=force_refresh)
        except Exception as exc:
            fallback_error = str(exc)[:200]
            logger.debug("exchangerate-api fallback unavailable: %s", exc)

    now_epoch = fx.utc_now_epoch()
    quotes: list[ForexQuote] = []
    for currency in wanted:
        if not is_valid_currency(currency):
            continue
        symbol = symbols.get(currency)
        raw = raws.get(symbol) if symbol else None
        cross = None
        cross_epoch = None
        if fallback_rates is not None:
            cross = fx.cross_rate(fallback_rates, currency, QUOTE_CURRENCY)
            cross_epoch = fallback_rates.get("updated_epoch")
        quotes.append(build_quote(currency, raw, fallback_rate=cross, fallback_epoch=cross_epoch, now_epoch=now_epoch))

    live = sum(1 for q in quotes if q.data_mode == "LIVE")
    unavailable = [q.symbol for q in quotes if q.data_mode == "UNAVAILABLE"]
    sources = sorted({q.source for q in quotes if q.source != "none"})

    return {
        "base": QUOTE_CURRENCY,
        "quote_currency": QUOTE_CURRENCY,
        "pairs": "each pair is quoted as <CURRENCY>/PKR",
        "count": len(quotes),
        "quotes": [q.to_dict() for q in quotes],
        "failed": unavailable,
        "rejected_currencies": unknown,
        "live_count": live,
        "delayed_count": sum(1 for q in quotes if q.data_mode == "DELAYED"),
        "sources": sources,
        "fallback_source": fx.SOURCE_ERAPI if fallback_rates is not None else None,
        "fallback_error": fallback_error,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "live_seconds": settings.fx_live_threshold_seconds,
            "aging_seconds": settings.fx_aging_threshold_seconds,
            "stale_seconds": settings.fx_stale_threshold_seconds,
        },
        "label": "PKR-based data — every rate is quoted against the Pakistani Rupee.",
        "disclaimer": (
            "Indicative interbank/reference rates for information only, not a dealing price or "
            "investment advice. Actual execution rates from a bank or exchange company will differ."
        ),
    }


async def build_single_quote(currency: str, *, force_refresh: bool = False) -> Optional[dict[str, Any]]:
    """One pair, for `GET /api/forex/{symbol}`."""
    payload = await build_forex_quotes([currency], force_refresh=force_refresh)
    quotes = payload.get("quotes") or []
    return {"quote": quotes[0], "data_meta": {"source": quotes[0]["source"], "status": quotes[0]["data_mode"]},
            "generated_at": payload["generated_at"], "disclaimer": payload["disclaimer"]} if quotes else None


def parse_pair(symbol: str) -> tuple[str, str]:
    """`USD/PKR` (or `USDPKR`, or `USD-PKR`) -> ("USD", "PKR"). Raises ValueError."""
    text = (symbol or "").strip().upper().replace("-", "/")
    if "/" not in text:
        if len(text) == 6:
            text = f"{text[:3]}/{text[3:]}"
        else:
            raise ValueError(f"{symbol!r} is not a currency pair — use a form like USD/PKR")
    base, _, quote = text.partition("/")
    if not is_valid_currency(base) or not is_valid_currency(quote):
        raise ValueError(f"{symbol!r} contains an unrecognised currency code")
    return base, quote
