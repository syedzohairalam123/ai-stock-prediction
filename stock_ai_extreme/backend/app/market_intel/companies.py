"""Phase 23B — corporate market-cap dataset, calculation and ranking (spec §8–§13).

The company list here is a *watch universe*, not a ranking: ranks are always
computed from the latest verified observations at request time (spec §11). A
provider that reports a verified market capitalisation is trusted and labelled;
only when it is absent is ``price × sharesOutstanding`` used, and that result is
labelled an estimate — never presented as an official reported figure (spec §10).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("neural_market.market_intel.companies")

#: A provider-reported market cap older than this is flagged STALE rather than
#: shown as current (spec §9, §11).
STALE_AFTER_DAYS = 7

#: ``data_quality`` vocabulary.
QUALITY_VERIFIED = "VERIFIED"      # provider reports the market cap itself
QUALITY_ESTIMATED = "ESTIMATED"    # price × shares, from a single provider snapshot
QUALITY_STALE = "STALE"            # inputs are old enough to be unreliable
QUALITY_UNAVAILABLE = "UNAVAILABLE"  # no usable inputs — never zero-filled

METHOD_PROVIDER = "PROVIDER_REPORTED"
METHOD_COMPUTED = "PRICE_X_SHARES"
METHOD_UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CompanyDefinition:
    """A company in the watch universe (spec §8)."""

    company_id: str
    name: str
    ticker: str
    sector: str
    exchange: str = "NASDAQ"
    additional_tickers: tuple[str, ...] = ()

    @property
    def all_tickers(self) -> list[str]:
        return [self.ticker, *self.additional_tickers]


#: Major publicly listed companies, weighted toward large-cap technology
#: (spec §8). This is the set the engine *tries*; a company the provider cannot
#: answer for is reported UNAVAILABLE, never given a made-up cap.
COMPANY_UNIVERSE: tuple[CompanyDefinition, ...] = (
    CompanyDefinition("apple", "Apple Inc.", "AAPL", "Information Technology"),
    CompanyDefinition("microsoft", "Microsoft Corporation", "MSFT", "Information Technology"),
    CompanyDefinition("nvidia", "NVIDIA Corporation", "NVDA", "Information Technology"),
    CompanyDefinition("alphabet", "Alphabet Inc.", "GOOGL", "Communication Services",
                      additional_tickers=("GOOG",)),
    CompanyDefinition("amazon", "Amazon.com, Inc.", "AMZN", "Consumer Discretionary"),
    CompanyDefinition("meta", "Meta Platforms, Inc.", "META", "Communication Services"),
    CompanyDefinition("broadcom", "Broadcom Inc.", "AVGO", "Information Technology"),
    CompanyDefinition("tesla", "Tesla, Inc.", "TSLA", "Consumer Discretionary"),
    CompanyDefinition("berkshire", "Berkshire Hathaway Inc.", "BRK-B", "Financials",
                      additional_tickers=("BRK-A",)),
    CompanyDefinition("jpmorgan", "JPMorgan Chase & Co.", "JPM", "Financials"),
    CompanyDefinition("visa", "Visa Inc.", "V", "Financials"),
    CompanyDefinition("mastercard", "Mastercard Incorporated", "MA", "Financials"),
    CompanyDefinition("walmart", "Walmart Inc.", "WMT", "Consumer Staples"),
    CompanyDefinition("johnson", "Johnson & Johnson", "JNJ", "Health Care"),
    CompanyDefinition("exxon", "Exxon Mobil Corporation", "XOM", "Energy"),
    CompanyDefinition("lilly", "Eli Lilly and Company", "LLY", "Health Care"),
    CompanyDefinition("unitedhealth", "UnitedHealth Group Incorporated", "UNH", "Health Care"),
    CompanyDefinition("procter", "The Procter & Gamble Company", "PG", "Consumer Staples"),
    CompanyDefinition("home_depot", "The Home Depot, Inc.", "HD", "Consumer Discretionary"),
    CompanyDefinition("bank_of_america", "Bank of America Corporation", "BAC", "Financials"),
    CompanyDefinition("costco", "Costco Wholesale Corporation", "COST", "Consumer Staples"),
    CompanyDefinition("abbvie", "AbbVie Inc.", "ABBV", "Health Care"),
    CompanyDefinition("coca_cola", "The Coca-Cola Company", "KO", "Consumer Staples"),
    CompanyDefinition("pepsico", "PepsiCo, Inc.", "PEP", "Consumer Staples"),
    CompanyDefinition("oracle", "Oracle Corporation", "ORCL", "Information Technology"),
    CompanyDefinition("amd", "Advanced Micro Devices, Inc.", "AMD", "Information Technology"),
    CompanyDefinition("salesforce", "Salesforce, Inc.", "CRM", "Information Technology"),
    CompanyDefinition("adobe", "Adobe Inc.", "ADBE", "Information Technology"),
    CompanyDefinition("netflix", "Netflix, Inc.", "NFLX", "Communication Services"),
    CompanyDefinition("tsmc", "Taiwan Semiconductor Manufacturing Company Limited", "TSM",
                      "Information Technology"),
    CompanyDefinition("asml", "ASML Holding N.V.", "ASML", "Information Technology"),
    CompanyDefinition("broadcom_alt", "QUALCOMM Incorporated", "QCOM", "Information Technology"),
    CompanyDefinition("intel", "Intel Corporation", "INTC", "Information Technology"),
    CompanyDefinition("cisco", "Cisco Systems, Inc.", "CSCO", "Information Technology"),
    CompanyDefinition("ibm", "International Business Machines Corporation", "IBM",
                      "Information Technology"),
    CompanyDefinition("pltr", "Palantir Technologies Inc.", "PLTR", "Information Technology"),
    CompanyDefinition("uber", "Uber Technologies, Inc.", "UBER", "Industrials"),
)


def get_company(company_id_or_ticker: str) -> Optional[CompanyDefinition]:
    """Resolve a company by id or by any of its listed tickers."""
    if not company_id_or_ticker:
        return None
    needle = company_id_or_ticker.strip().lower()
    for definition in COMPANY_UNIVERSE:
        if definition.company_id == needle:
            return definition
        if any(t.lower() == needle for t in definition.all_tickers):
            return definition
    return None


@dataclass
class CompanyMarketData:
    """The company market-data record (spec §9)."""

    company_id: str
    name: str
    ticker: str
    exchange: Optional[str]
    sector: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    shares_outstanding: Optional[float]
    market_cap: Optional[float]
    observation_timestamp: Optional[datetime]
    price_source: Optional[str]
    shares_source: Optional[str]
    data_quality: str
    market_cap_methodology: str = METHOD_UNAVAILABLE
    previous_market_cap: Optional[float] = None
    previous_rank: Optional[int] = None
    rank: Optional[int] = None
    rank_change: Optional[int] = None
    market_cap_change: Optional[float] = None
    market_cap_change_pct: Optional[float] = None
    additional_tickers: tuple[str, ...] = ()
    note: Optional[str] = None
    source_document: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "company_id": self.company_id,
            "name": self.name,
            "ticker": self.ticker,
            "exchange": self.exchange,
            "sector": self.sector,
            "price": self.price,
            "currency": self.currency,
            "shares_outstanding": self.shares_outstanding,
            "market_cap": self.market_cap,
            "market_cap_methodology": self.market_cap_methodology,
            "observation_timestamp": (
                self.observation_timestamp.isoformat() if self.observation_timestamp else None
            ),
            "price_source": self.price_source,
            "shares_source": self.shares_source,
            "data_quality": self.data_quality,
            "previous_market_cap": self.previous_market_cap,
            "previous_rank": self.previous_rank,
            "rank": self.rank,
            "rank_change": self.rank_change,
            "market_cap_change": self.market_cap_change,
            "market_cap_change_pct": self.market_cap_change_pct,
            "additional_tickers": list(self.additional_tickers),
            "note": self.note,
            "source_document": self.source_document,
        }


def _as_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _market_time_to_datetime(value) -> Optional[datetime]:
    """Yahoo's ``regularMarketTime`` is an epoch second or an ISO string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def compute_market_cap(
    price: Optional[float], shares_outstanding: Optional[float]
) -> Optional[float]:
    """``marketCap = sharePrice × sharesOutstanding`` (spec §10).

    Returns ``None`` when either input is missing/non-positive — a missing input
    is never treated as zero, which would silently produce a fake $0 company.
    """
    if price is None or shares_outstanding is None:
        return None
    if price <= 0 or shares_outstanding <= 0:
        return None
    return price * shares_outstanding


def build_company_market_data(
    definition: CompanyDefinition,
    info: dict,
    source: str,
    now: Optional[datetime] = None,
) -> CompanyMarketData:
    """Turn a provider's company payload into a sourced ``CompanyMarketData``.

    Priority (spec §10): a provider that supplies a verified market cap is kept
    verbatim with its methodology; otherwise the value is computed from price ×
    shares and labelled an estimate. Nothing is fabricated when the provider
    omits a field.
    """
    now = now or datetime.now(timezone.utc)
    info = info or {}

    price = _as_float(
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    shares = _as_float(info.get("sharesOutstanding"))
    # Accept both provider shapes: raw Yahoo payloads use ``marketCap`` while
    # this project's own yfinance adapter (get_profile) exposes ``market_cap``.
    # Without the snake_case fallback a provider-reported cap was never seen and
    # every figure silently degraded to a computed estimate.
    provider_cap = _as_float(info.get("marketCap") or info.get("market_cap"))
    shares_date_raw = info.get("sharesOutstandingDate") or info.get("dateShortInterest")
    price_dt = _market_time_to_datetime(
        info.get("regularMarketTime") or info.get("currentPriceTimestamp")
    )
    shares_dt = _market_time_to_datetime(shares_date_raw)

    methodology = METHOD_UNAVAILABLE
    market_cap: Optional[float] = None
    quality = QUALITY_UNAVAILABLE
    note: Optional[str] = None

    if provider_cap is not None and provider_cap > 0:
        market_cap = provider_cap
        methodology = METHOD_PROVIDER
        # A provider-reported cap is the most trustworthy figure available.
        # Staleness is judged from the quote time when one exists.
        reference = price_dt or now
        age_days = (now - reference).days
        if age_days > STALE_AFTER_DAYS:
            quality = QUALITY_STALE
            note = (
                f"Provider-reported market cap last observed {reference.date().isoformat()} "
                "— older than the freshness threshold."
            )
        else:
            quality = QUALITY_VERIFIED
        if definition.additional_tickers:
            note = (
                (note + " " if note else "")
                + "Issuer has multiple share classes; the provider's figure is "
                "company-wide and its methodology is retained."
            )
    elif price is not None and shares is not None:
        market_cap = compute_market_cap(price, shares)
        if market_cap is not None:
            methodology = METHOD_COMPUTED
            quality = QUALITY_ESTIMATED
            note = (
                "Estimated from price × shares outstanding on one provider "
                "snapshot — not an officially reported figure."
            )
            if shares_dt is None:
                note += " Share-count as-of date unavailable from the source."
            if definition.additional_tickers:
                note += (
                    " Issuer has multiple share classes; a single-class share "
                    "count understates company-wide capitalisation."
                )
    else:
        # Keep the partial inputs so the UI can say what is missing, but leave
        # the cap absent rather than inventing one.
        note = "Provider returned no usable price/share inputs for a market cap."

    observation = price_dt or shares_dt or now
    return CompanyMarketData(
        company_id=definition.company_id,
        name=definition.name,
        ticker=definition.ticker,
        exchange=info.get("exchange"),
        sector=info.get("sector") or definition.sector,
        price=price,
        currency=info.get("currency"),
        shares_outstanding=shares,
        market_cap=market_cap,
        observation_timestamp=observation,
        price_source=source,
        shares_source=f"{source} (sharesOutstanding)" if shares is not None else None,
        data_quality=quality,
        market_cap_methodology=methodology,
        additional_tickers=definition.additional_tickers,
        note=note,
        source_document=info.get("sourceDocument"),
    )


def rank_companies(
    records: list[CompanyMarketData],
    previous_ranks: Optional[dict[str, int]] = None,
    previous_caps: Optional[dict[str, float]] = None,
) -> list[CompanyMarketData]:
    """Assign ranks from actual records (spec §11).

    Only records with a market cap participate. A company without current
    verified data keeps ``rank=None`` and stays in the list as UNAVAILABLE/STALE
    — it is never given an invented cap to fill a slot. ``previous_ranks`` maps
    company_id → previously observed rank so ``rank_change`` is real history.
    """
    previous_ranks = previous_ranks or {}
    previous_caps = previous_caps or {}
    ranked = sorted(
        [r for r in records if r.market_cap is not None],
        key=lambda r: r.market_cap or 0.0,
        reverse=True,
    )
    for position, record in enumerate(ranked, start=1):
        record.rank = position
        prior = previous_ranks.get(record.company_id)
        record.previous_rank = prior
        # Positive rank_change = moved up (smaller number is better).
        record.rank_change = (prior - position) if prior is not None else None
        prior_cap = previous_caps.get(record.company_id)
        record.previous_market_cap = prior_cap
        if prior_cap and prior_cap != 0 and record.market_cap is not None:
            record.market_cap_change = round(record.market_cap - prior_cap, 2)
            record.market_cap_change_pct = round(
                (record.market_cap / prior_cap - 1.0) * 100, 6
            )
    for record in records:
        if record.market_cap is None:
            record.rank = None
            record.previous_rank = previous_ranks.get(record.company_id)
            record.rank_change = None
    return records


def split_adjusted_price(price: Optional[float], split_ratio: Optional[float]) -> Optional[float]:
    """Restate a pre-split price in post-split terms (spec §10).

    ``split_ratio`` is new shares per old share, so a 2:1 split means a $200
    pre-split price becomes $100. Returning ``None`` for a missing/zero ratio
    keeps an unknown split from silently corrupting a price.
    """
    if price is None or split_ratio is None or split_ratio <= 0:
        return None
    return price / split_ratio


def split_adjusted_shares(shares: Optional[float], split_ratio: Optional[float]) -> Optional[float]:
    """Restate a pre-split share count in post-split terms (spec §10)."""
    if shares is None or split_ratio is None or split_ratio <= 0:
        return None
    return shares * split_ratio


def scenario_market_cap(
    reference_price: Optional[float],
    shares_outstanding: Optional[float],
    scenario_return: float,
) -> dict:
    """Hypothetical scenario arithmetic (spec §13).

    ``scenarioPrice = reference × (1 + r)`` and
    ``scenarioMarketCap = scenarioPrice × shares``. This is arithmetic under an
    assumed return — explicitly NOT a prediction or guarantee.
    """
    scenario_price = (
        round(reference_price * (1 + scenario_return), 6)
        if reference_price is not None
        else None
    )
    scenario_cap = (
        compute_market_cap(scenario_price, shares_outstanding)
        if scenario_price is not None
        else None
    )
    return {
        "reference_price": reference_price,
        "shares_outstanding": shares_outstanding,
        "scenario_return": scenario_return,
        "scenario_price": scenario_price,
        "scenario_market_cap": scenario_cap,
        "label": "HYPOTHETICAL_SCENARIO",
        "note": (
            "Hypothetical arithmetic under an assumed price change using the "
            "reference price and share count shown. It is not a prediction and "
            "not a guarantee, and it ignores corporate actions and dilution."
        ),
    }


def market_cap_race(
    current: list[CompanyMarketData],
    history: dict[str, list[dict]],
) -> dict:
    """Descriptive company comparison over a period (spec §12).

    Presents observed rankings, historical rankings where data exists, rank
    changes and market-cap changes. It deliberately produces no probability or
    forecast statement.
    """
    rows = []
    for record in current:
        history_rows = history.get(record.company_id, [])
        first = history_rows[0] if history_rows else None
        change = None
        change_pct = None
        if first and first.get("market_cap") and record.market_cap:
            change = round(record.market_cap - first["market_cap"], 2)
            change_pct = round((record.market_cap / first["market_cap"] - 1.0) * 100, 6)
        rows.append(
            {
                "company_id": record.company_id,
                "name": record.name,
                "ticker": record.ticker,
                "current_market_cap": record.market_cap,
                "current_rank": record.rank,
                "first_observed_market_cap": first["market_cap"] if first else None,
                "first_observed_rank": first.get("rank") if first else None,
                "market_cap_change": change,
                "market_cap_change_pct": change_pct,
                "history_points": len(history_rows),
                "data_quality": record.data_quality,
            }
        )
    return {
        "rows": rows,
        "note": (
            "Descriptive comparison of observed figures only. No probability or "
            "forecast is produced; a modelled forecast would be a separate, "
            "validated output."
        ),
    }
