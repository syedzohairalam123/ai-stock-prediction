"""
Phase 20 — the ticket's quote layer.

It does **not** introduce a second market-data stack. It reads:

  * `MarketDataManager` — the Phase 2 provider manager every other page uses
    for price/status/freshness (so the ticket shares one cache and one
    fallback chain, spec §16).
  * `providers.fx_rates.yahoo_quotes` — the Phase 7 real bid/ask source, reused
    here for the spread/mid readout instead of inventing a spread.
  * `forecast_markets` — the Phase 14 real probability source for event tickets.

Honesty rules enforced in this file:

  * An UNAVAILABLE quote keeps `price=None`. It never becomes 0.
  * `bid`/`ask` are only reported when the source actually published them;
    a missing side is `None` and the UI renders "—".
  * A quote older than the configured window (or classified STALE by the
    provider layer) sets `stale=True`, and the ticket then refuses to present
    it as the current price (spec §17).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from ..config import settings
from ..logging_config import get_logger
from ..providers import DataStatus
from ..providers import fx_rates
from ..symbols import symbol_candidates
from .config import paper_settings
from .instruments import InstrumentKind, PaperInstrument, QuoteMode
from .pnl import finite_or_none
from .state import get_manager

logger = get_logger("neural_market.paper.quotes")


class PaperDataMode:
    """The label the ticket shows. Never DEMO — this app does not ship fake prices."""

    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


def _data_mode_for(status: DataStatus) -> str:
    if status is DataStatus.LIVE:
        return PaperDataMode.LIVE
    if status in (DataStatus.RECENT, DataStatus.CACHED):
        return PaperDataMode.DELAYED
    if status is DataStatus.STALE:
        return PaperDataMode.STALE
    return PaperDataMode.UNAVAILABLE


@dataclass
class PaperQuote:
    """A normalized, honest quote for one ticket."""

    symbol: str
    kind: str
    quote_mode: str
    price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    spread: Optional[float] = None
    spread_percent: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    previous_close: Optional[float] = None
    currency: Optional[str] = None
    timestamp: Optional[str] = None
    source: Optional[str] = None
    status: str = DataStatus.UNAVAILABLE.value
    data_mode: str = PaperDataMode.UNAVAILABLE
    stale: bool = False
    stale_reason: Optional[str] = None
    age_seconds: Optional[float] = None
    #: Annualised volatility from real daily bars (percent), or None.
    volatility_percent: Optional[float] = None
    volatility_lookback: Optional[int] = None
    #: Forecast-event fields.
    probability_yes: Optional[float] = None
    probability_no: Optional[float] = None
    market_status: Optional[str] = None
    close_time: Optional[str] = None
    question: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    @property
    def has_price(self) -> bool:
        return self.price is not None and self.quote_mode == QuoteMode.PRICE.value

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "kind": self.kind,
            "quoteMode": self.quote_mode,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread": self.spread,
            "spreadPercent": self.spread_percent,
            "change": self.change,
            "changePercent": self.change_percent,
            "previousClose": self.previous_close,
            "currency": self.currency,
            "timestamp": self.timestamp,
            "source": self.source,
            "status": self.status,
            "dataMode": self.data_mode,
            "stale": self.stale,
            "staleReason": self.stale_reason,
            "ageSeconds": self.age_seconds,
            "volatilityPercent": self.volatility_percent,
            "volatilityLookback": self.volatility_lookback,
            "probabilityYes": self.probability_yes,
            "probabilityNo": self.probability_no,
            "marketStatus": self.market_status,
            "closeTime": self.close_time,
            "question": self.question,
            "notes": list(self.notes),
            "simulationOnly": True,
        }


def historical_volatility_percent(
    closes: list[float],
    *,
    trading_days: Optional[int] = None,
) -> Optional[float]:
    """Annualised volatility (percent) from real daily closes.

    Standard sample standard deviation of daily log-ish simple returns scaled by
    sqrt(trading days). Returns None when there are too few real observations —
    the risk panel then shows "not available" instead of a made-up figure.
    """
    series = [finite_or_none(c) for c in closes]
    series = [c for c in series if c is not None and c > 0]
    if len(series) < 20:
        return None
    returns: list[float] = []
    for previous, current in zip(series, series[1:]):
        if previous:
            returns.append((current - previous) / previous)
    if len(returns) < 10:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    if variance <= 0:
        return 0.0
    days = trading_days or paper_settings.paper_trading_days_per_year
    annualised = math.sqrt(variance) * math.sqrt(days) * 100.0
    return round(annualised, 3) if math.isfinite(annualised) else None


async def _bid_ask(symbol: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Real bid/ask from the Phase 7 source, or (None, None, None).

    Tries the same symbol candidates the price path uses, so a bare PSX symbol
    resolves to its `.KA` listing here too. A symbol the source has no book for
    simply returns nothing — it is never replaced with a synthetic spread.
    """
    for candidate in symbol_candidates(symbol):
        try:
            quotes = await fx_rates.yahoo_quotes([candidate])
        except Exception as exc:  # a bid/ask miss must never fail the ticket
            logger.debug("bid/ask lookup failed for %s: %s", candidate, exc)
            continue
        raw = quotes.get(candidate)
        if raw is None or raw.status == "UNAVAILABLE":
            continue
        bid = finite_or_none(raw.bid)
        ask = finite_or_none(raw.ask)
        # Reject inverted/incoherent sides the way the FX module does rather
        # than displaying a negative spread as if it were real.
        if bid is not None and ask is not None and ask < bid:
            logger.debug("inverted bid/ask for %s (%s/%s) — discarded", candidate, bid, ask)
            bid = ask = None
        if bid is not None and bid <= 0:
            bid = None
        if ask is not None and ask <= 0:
            ask = None
        if bid is not None or ask is not None:
            return bid, ask, raw.source
    return None, None, None


async def _volatility(symbol: str) -> Optional[float]:
    manager = get_manager()
    if manager is None:
        return None
    end = date.today()
    start = end - timedelta(days=paper_settings.paper_volatility_lookback_days * 2)
    try:
        frame, _source, _status = await manager.history(symbol, start, end)
    except Exception as exc:
        logger.debug("volatility history unavailable for %s: %s", symbol, exc)
        return None
    if frame is None or getattr(frame, "empty", True) or "Close" not in getattr(frame, "columns", []):
        return None
    try:
        closes = [float(v) for v in frame["Close"].dropna().tolist()]
    except (TypeError, ValueError):
        return None
    window = closes[-(paper_settings.paper_volatility_lookback_days + 1):]
    return historical_volatility_percent(window)


async def build_forecast_quote(instrument: PaperInstrument) -> PaperQuote:
    """Quote for a Phase 14 forecast event: a probability, not a price."""
    from ..forecast_markets import fetch_market_by_id

    quote = PaperQuote(
        symbol=instrument.symbol,
        kind=instrument.kind.value,
        quote_mode=QuoteMode.PROBABILITY.value,
        source="Polymarket public market data",
        status=DataStatus.UNAVAILABLE.value,
        data_mode=PaperDataMode.UNAVAILABLE,
    )
    market_id = instrument.market_id or instrument.provider_symbol
    try:
        market = await fetch_market_by_id(market_id, settings.forecast_market_timeout_seconds)
    except Exception as exc:
        logger.warning("forecast market lookup failed for %s: %s", market_id, exc)
        market = None
    if not market:
        quote.notes.append("The forecast source did not return this event; no probability is shown.")
        return quote

    yes = finite_or_none(market.get("yesProbability"))
    no = finite_or_none(market.get("noProbability"))
    quote.probability_yes = yes
    quote.probability_no = no
    quote.question = market.get("title")
    quote.close_time = market.get("closeTime")
    quote.market_status = market.get("status")
    quote.source = (market.get("sources") or [{}])[0].get("name") or quote.source
    quote.timestamp = market.get("updatedAt")
    # A forecast market is a live probability feed while it is OPEN; once it
    # has CLOSED or RESOLVED the reading is historical, not current.
    if market.get("status") == "OPEN":
        quote.status = DataStatus.LIVE.value
        quote.data_mode = PaperDataMode.LIVE
    else:
        quote.status = DataStatus.RECENT.value
        quote.data_mode = PaperDataMode.DELAYED
    age = _age_seconds(quote.timestamp)
    quote.age_seconds = age
    if age is not None and age > paper_settings.paper_stale_after_seconds:
        quote.stale = True
        quote.data_mode = PaperDataMode.STALE
        quote.stale_reason = f"The feed's last update is {int(age)}s old."
    return quote


def _age_seconds(timestamp: Optional[str]) -> Optional[float]:
    if not timestamp:
        return None
    text = str(timestamp).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


async def build_quote(
    instrument: PaperInstrument,
    *,
    with_bid_ask: bool = True,
    with_volatility: bool = True,
) -> PaperQuote:
    """Build the ticket's quote for any supported instrument."""
    if instrument.quote_mode is QuoteMode.PROBABILITY:
        return await build_forecast_quote(instrument)

    manager = get_manager()
    quote = PaperQuote(
        symbol=instrument.symbol,
        kind=instrument.kind.value,
        quote_mode=QuoteMode.PRICE.value,
        currency=instrument.currency,
    )
    if manager is None:
        quote.stale = True
        quote.stale_reason = "The market-data provider layer is not available."
        quote.notes.append("No provider manager is configured on the server.")
        return quote

    try:
        provider_quote = await manager.quote(instrument.provider_symbol or instrument.symbol)
    except Exception as exc:
        logger.warning("quote failed for %s: %s", instrument.symbol, exc)
        quote.stale = True
        quote.stale_reason = "The provider layer could not answer for this symbol."
        return quote

    status = provider_quote.status
    quote.status = status.value
    quote.source = provider_quote.source
    quote.data_mode = _data_mode_for(status)
    price = finite_or_none(provider_quote.price)
    if status is DataStatus.UNAVAILABLE or price is None or price <= 0:
        # Never coerce a failure into a 0.0 price.
        quote.price = None
        quote.data_mode = PaperDataMode.UNAVAILABLE
        quote.stale = True
        quote.stale_reason = "No live price was available, so no current price is claimed."
        quote.notes.append("The provider returned no usable price for this symbol.")
        return quote

    quote.price = price
    quote.previous_close = finite_or_none(provider_quote.previous_close)
    quote.change_percent = finite_or_none(provider_quote.change_percent)
    if quote.previous_close is not None:
        quote.change = round(price - quote.previous_close, 8)
    quote.timestamp = provider_quote.timestamp.isoformat() if provider_quote.timestamp else None
    quote.age_seconds = _age_seconds(quote.timestamp)

    if status is DataStatus.STALE:
        quote.stale = True
        quote.data_mode = PaperDataMode.STALE
        quote.stale_reason = "The provider classified this reading as stale."
    elif quote.age_seconds is not None and quote.age_seconds > paper_settings.paper_stale_after_seconds:
        quote.stale = True
        quote.data_mode = PaperDataMode.STALE
        quote.stale_reason = f"The last update is {int(quote.age_seconds)}s old."

    if with_bid_ask:
        bid, ask, _source = await _bid_ask(instrument.provider_symbol or instrument.symbol)
        quote.bid = bid
        quote.ask = ask
        if bid is not None and ask is not None:
            quote.mid = round((bid + ask) / 2.0, 8)
            quote.spread = round(ask - bid, 8)
            quote.spread_percent = round((ask - bid) / quote.mid * 100.0, 6) if quote.mid else None
        elif bid is None and ask is None:
            # Fall back to the observed traded price as the "mid" so the panel
            # still has an honest reference; bid/ask stay None and render "—".
            quote.mid = price

    if with_volatility:
        quote.volatility_percent = await _volatility(instrument.provider_symbol or instrument.symbol)
        quote.volatility_lookback = paper_settings.paper_volatility_lookback_days

    if quote.currency is None:
        quote.currency = None
    return quote


async def observed_bars_after(
    symbol: str,
    after: datetime,
    *,
    limit: int = 60,
    interval: str = "1d",
) -> list[dict[str, Any]]:
    """Real OHLC bars that occurred *after* a timestamp — used to judge whether
    a hypothetical LIMIT condition would have been met.

    Returns `[]` (never synthetic rows) when the provider has nothing new. The
    caller must treat `[]` as "not determinable yet", not as "did not fill".
    """
    manager = get_manager()
    if manager is None:
        return []
    start = (after.date() - timedelta(days=1))
    end = date.today()
    if end < start:
        return []
    try:
        frame, _source, _status = await manager.history(symbol, start, end, interval)
    except Exception as exc:
        logger.debug("bar lookup failed for %s: %s", symbol, exc)
        return []
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        try:
            stamp = index.to_pydatetime()
        except AttributeError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp.astimezone(timezone.utc) <= after.astimezone(timezone.utc):
            continue
        rows.append(
            {
                "timestamp": stamp.astimezone(timezone.utc).isoformat(),
                "open": finite_or_none(row.get("Open")),
                "high": finite_or_none(row.get("High")),
                "low": finite_or_none(row.get("Low")),
                "close": finite_or_none(row.get("Close")),
            }
        )
        if len(rows) >= limit:
            break
    return rows
