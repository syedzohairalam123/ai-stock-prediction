"""Phase 23B — service layer (spec §2–§7, §15, §16).

One service that reuses the project's *existing* market-data stack:

* the shared :class:`~app.providers.manager.MarketDataManager` bound by the app
  shell (same providers, same cache, same upstream quota as every other chart),
* the existing database (``app.db``) for stored company observations and rank
  snapshots,
* the Phase 23A macro service for policy-decision event studies.

It never creates a second data provider and never fabricates a value: a fetch
that fails becomes an explicit UNAVAILABLE result carrying the real reason.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from ..providers.base import DataStatus, ProviderError
from ..db import session_scope
from . import analytics as analytics_mod
from .companies import (
    COMPANY_UNIVERSE,
    CompanyDefinition,
    CompanyMarketData,
    QUALITY_UNAVAILABLE,
    build_company_market_data,
    get_company,
    market_cap_race,
    rank_companies,
    scenario_market_cap,
)
from .db_models import (
    Company,
    CompanyMarketObservation,
    CompanySecurityMapping,
    CorporateActionEvent,
    MarketCapRankHistory,
    MarketCapSnapshot,
    SharesOutstandingObservation,
)
from .direction import (
    INSTRUMENTS,
    DailyObservation,
    Instrument,
    align_instruments,
    build_daily_observations,
    compute_direction_statistics,
    compute_rolling,
    latest_session,
    resolve_instrument,
)

logger = logging.getLogger("neural_market.market_intel.service")

#: How much history the dashboard/statistics default to.
DEFAULT_HISTORY_DAYS = 400

#: Extra calendar days fetched before the requested window so the FIRST session
#: in the window still has its real previous trading-session close.
_LOOKBACK_PADDING_DAYS = 20


def _to_datetime(value) -> Optional[datetime]:
    """Best-effort parse of a provider timestamp into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
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


def _classify_security(ticker: str) -> str:
    """Best-effort security-type label from the ticker's own convention.

    This only labels *how a listing is issued* (a class suffix or a known class
    symbol); it never infers company fundamentals. Unknown tickers are the
    honest default ``COMMON``.
    """
    upper = (ticker or "").upper()
    for suffix, label in (("-A", "CLASS_A"), (".A", "CLASS_A"), ("-B", "CLASS_B"),
                          (".B", "CLASS_B"), ("-C", "CLASS_C"), (".C", "CLASS_C")):
        if upper.endswith(suffix):
            return label
    if upper == "GOOGL":
        return "CLASS_A"
    if upper == "GOOG":
        return "CLASS_C"
    return "COMMON"


def _frame_to_rows(frame) -> list[dict]:
    """Flatten a provider OHLCV frame to plain dict rows (date + OHLCV)."""
    rows: list[dict] = []
    if frame is None:
        return rows
    for index, row in frame.iterrows():
        date_attr = getattr(index, "date", None)
        day = date_attr() if callable(date_attr) else index
        def pick(*names):
            for name in names:
                if name in row and row[name] is not None:
                    return row[name]
            return None
        rows.append(
            {
                "date": str(day)[:10],
                "open": pick("Open"),
                "high": pick("High"),
                "low": pick("Low"),
                "close": pick("Close"),
                "volume": pick("Volume"),
                "adjusted_close": pick("Adj Close", "AdjClose", "Adjusted Close"),
            }
        )
    return rows


class MarketIntelligenceService:
    """SPX/SPY direction analytics + corporate market-cap intelligence."""

    def __init__(self) -> None:
        # Bound by the app shell (see main.py) — never created here so there is
        # exactly one provider stack in the process.
        self._market_history: Optional[Callable[..., Any]] = None
        self._profile_fetcher: Optional[Callable[..., Any]] = None
        self._splits_fetcher: Optional[Callable[..., Any]] = None
        self._macro_service: Any = None
        # Minimum seconds between stored rank snapshots (avoids a row per poll).
        self._rank_snapshot_min_seconds = 3600
        self._company_registry_ready = False

    # ------------------------------------------------------------------ setup
    def configure(
        self,
        history_fetcher,
        profile_fetcher=None,
        macro_service=None,
        splits_fetcher=None,
    ) -> None:
        """Bind the shared fetchers.

        ``history_fetcher(ticker, start, end, interval) -> (frame, source, status)``,
        ``profile_fetcher(ticker) -> dict`` and
        ``splits_fetcher(ticker) -> (list, source, status)`` are the manager's own
        methods, and ``macro_service`` is the Phase 23A service reused for event
        studies. ``splits_fetcher`` is optional: without it, corporate actions
        remain recordable by hand but cannot be auto-ingested.
        """
        self._market_history = history_fetcher
        self._profile_fetcher = profile_fetcher
        self._macro_service = macro_service
        if splits_fetcher is not None:
            self._splits_fetcher = splits_fetcher

    # ------------------------------------------------------------- instruments
    def instruments(self) -> list[dict]:
        return [instrument.as_dict() for instrument in INSTRUMENTS.values()]

    def _instrument(self, key: str) -> Instrument:
        instrument = resolve_instrument(key)
        if instrument is None:
            raise ValueError(
                f"Unknown instrument '{key}'. Supported: {', '.join(INSTRUMENTS)}."
            )
        return instrument

    # ------------------------------------------------------- direction loading
    async def _load_observations(
        self,
        instrument: Instrument,
        days: int,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> dict:
        """Fetch real sessions and build direction observations (spec §2, §3).

        Returns a dict with ``observations``, ``source`` and ``status`` — or an
        explicit ``error`` when no provider could answer. ``observations`` is
        never padded with invented rows.
        """
        if self._market_history is None:
            return {
                "observations": [],
                "source": None,
                "status": DataStatus.UNAVAILABLE.value,
                "error": "Market-data source is not configured.",
            }
        end = end or datetime.now(timezone.utc).date()
        start = start or (end - timedelta(days=days + _LOOKBACK_PADDING_DAYS))
        try:
            frame, source, status = await self._market_history(
                instrument.symbol, start, end, "1d"
            )
        except ProviderError as exc:
            return {
                "observations": [],
                "source": None,
                "status": DataStatus.UNAVAILABLE.value,
                "error": str(exc),
            }
        except Exception as exc:  # provider surprises must not 500 the request
            logger.warning("history fetch failed for %s: %s", instrument.symbol, exc)
            return {
                "observations": [],
                "source": None,
                "status": DataStatus.UNAVAILABLE.value,
                "error": f"Market history unavailable: {exc}",
            }

        source_value = getattr(status, "value", status)
        fetched_at = datetime.now(timezone.utc)
        observations = build_daily_observations(
            _frame_to_rows(frame), instrument, source=source or "", source_timestamp=fetched_at
        )
        return {
            "observations": observations,
            "source": source,
            "status": source_value,
            "fetched_at": fetched_at.isoformat(),
            "error": None,
        }

    @staticmethod
    def _bounded_days(days: int, minimum: int = 30, maximum: int = 1825) -> int:
        return max(minimum, min(maximum, days))

    @staticmethod
    def _paginate(series: list[dict], limit: Optional[int], offset: int) -> list[dict]:
        """Tail-first pagination over an ascending series (spec §16).

        ``offset`` skips the newest records from the tail (page 0 is the newest
        page) and ``limit`` then caps the page size. Both default to the old
        behaviour, so every existing caller keeps working unchanged.
        """
        offset = max(0, int(offset or 0))
        if offset:
            end = len(series) - offset
            series = series[:end] if end > 0 else []
        if limit:
            series = series[-limit:]
        return series

    # ------------------------------------------------------------------ §2, §5
    async def get_instrument(
        self,
        key: str,
        days: int = DEFAULT_HISTORY_DAYS,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> dict:
        """Latest session plus the observation series for one instrument."""
        instrument = self._instrument(key)
        days = self._bounded_days(days)
        loaded = await self._load_observations(instrument, days)
        observations: list[DailyObservation] = loaded["observations"]
        series = [obs.as_dict() for obs in observations]
        series = self._paginate(series, limit, offset)
        return {
            "instrument": instrument.as_dict(),
            "source": loaded.get("source"),
            "data_status": loaded.get("status"),
            "fetched_at": loaded.get("fetched_at"),
            "error": loaded.get("error"),
            "latest": latest_session(observations) if observations else None,
            "series": series,
            "observation_count": len(observations),
            "page": {"limit": limit, "offset": max(0, int(offset or 0)), "returned": len(series)},
        }

    async def get_direction_history(
        self,
        key: str,
        days: int = DEFAULT_HISTORY_DAYS,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> dict:
        """Return history with its UP/DOWN/FLAT classification (spec §3, §6)."""
        payload = await self.get_instrument(key, days=days, limit=limit, offset=offset)
        payload["series"] = [row for row in payload["series"] if row.get("direction")]
        payload["observation_count"] = len(payload["series"])
        payload["note"] = (
            "Direction is computed from consecutive real trading-session closes. "
            "A missing session is absent, never a fabricated 0% return."
        )
        return payload

    async def get_statistics(self, key: str, days: int = DEFAULT_HISTORY_DAYS) -> dict:
        """Historical direction statistics with period + sample size (spec §4)."""
        instrument = self._instrument(key)
        days = self._bounded_days(days)
        loaded = await self._load_observations(instrument, days)
        observations: list[DailyObservation] = loaded["observations"]
        stats = compute_direction_statistics(observations)
        return {
            "instrument": instrument.as_dict(),
            "source": loaded.get("source"),
            "data_status": loaded.get("status"),
            "error": loaded.get("error"),
            "statistics": stats.__dict__,
            "note": (
                "Every figure is computed from the observed sessions shown; the "
                "observation period and sample size accompany each statistic."
            ),
        }

    async def get_rolling(
        self, key: str, days: int = DEFAULT_HISTORY_DAYS, window: int = 20
    ) -> dict:
        """Rolling return and annualised volatility (spec §4, §6)."""
        instrument = self._instrument(key)
        days = self._bounded_days(days)
        window = max(2, min(252, window))
        loaded = await self._load_observations(instrument, days)
        observations: list[DailyObservation] = loaded["observations"]
        points = compute_rolling(observations, window=window)
        return {
            "instrument": instrument.as_dict(),
            "source": loaded.get("source"),
            "data_status": loaded.get("status"),
            "error": loaded.get("error"),
            "window": window,
            "points": [p.__dict__ for p in points],
            "observation_count": len(observations),
        }

    async def get_comparison(
        self, days: int = DEFAULT_HISTORY_DAYS, limit: Optional[int] = None
    ) -> dict:
        """Session-aligned SPX vs SPY comparison (spec §6)."""
        days = self._bounded_days(days)
        spx = await self._load_observations(INSTRUMENTS["spx"], days)
        spy = await self._load_observations(INSTRUMENTS["spy"], days)
        aligned = align_instruments(spx["observations"], spy["observations"], "spx", "spy")

        # analytics §17 — vectorised NumPy/SciPy. Only session dates present in
        # BOTH series participate, so the correlation/volatility are computed on
        # genuinely overlapping observations, never on a zero-filled gap.
        both = [
            row
            for row in aligned
            if row.get("both_available")
            and row.get("spx_return_pct") is not None
            and row.get("spy_return_pct") is not None
        ]
        spx_returns = [row["spx_return_pct"] for row in both]
        spy_returns = [row["spy_return_pct"] for row in both]
        spx_closes = [row["spx_close"] for row in aligned if row.get("spx_close") is not None]
        spy_closes = [row["spy_close"] for row in aligned if row.get("spy_close") is not None]
        analytics_payload = {
            "overlapping_sessions": len(both),
            "return_correlation": analytics_mod.pearson_correlation(spx_returns, spy_returns),
            "spx_annualized_volatility_pct": analytics_mod.annualized_volatility(spx_returns),
            "spy_annualized_volatility_pct": analytics_mod.annualized_volatility(spy_returns),
            "spx_max_drawdown_pct": analytics_mod.max_drawdown(spx_closes),
            "spy_max_drawdown_pct": analytics_mod.max_drawdown(spy_closes),
        }

        if limit:
            aligned = aligned[-limit:]
        return {
            "instruments": [INSTRUMENTS["spx"].as_dict(), INSTRUMENTS["spy"].as_dict()],
            "spx_source": spx.get("source"),
            "spy_source": spy.get("source"),
            "spx_status": spx.get("status"),
            "spy_status": spy.get("status"),
            "aligned": aligned,
            "observation_count": len(aligned),
            "analytics": analytics_payload,
            "note": (
                "Alignment is on the exact trading date. A date missing from one "
                "series keeps the other side null — it is never treated as 0%. "
                "Correlation, volatility and drawdowns use only overlapping real "
                "sessions (NumPy/SciPy)."
            ),
        }

    # ------------------------------------------------------------- §5 dashboard
    async def get_dashboard(self, days: int = DEFAULT_HISTORY_DAYS) -> dict:
        """The SPX and SPY cards plus a compact statistics summary (spec §5)."""
        days = self._bounded_days(days)
        cards = []
        for key in ("spx", "spy"):
            instrument = INSTRUMENTS[key]
            loaded = await self._load_observations(instrument, days)
            observations: list[DailyObservation] = loaded["observations"]
            stats = compute_direction_statistics(observations)
            cards.append(
                {
                    "instrument": instrument.as_dict(),
                    "latest": latest_session(observations) if observations else None,
                    "statistics": stats.__dict__,
                    "source": loaded.get("source"),
                    "data_status": loaded.get("status"),
                    "error": loaded.get("error"),
                    "fetch_timestamp": loaded.get("fetched_at"),
                }
            )
        return {
            "cards": cards,
            "note": (
                "Values are the latest available trading-session closes, not live "
                "intraday quotes. The market may currently be closed."
            ),
        }

    # -------------------------------------------------------- company universe
    def _ensure_company_registry(self) -> None:
        """Upsert the watch universe into the ``companies`` table (spec §15)."""
        if self._company_registry_ready:
            return
        try:
            with session_scope() as db:
                existing = {row.company_id: row for row in db.query(Company).all()}
                for definition in COMPANY_UNIVERSE:
                    row = existing.get(definition.company_id)
                    if row is None:
                        db.add(
                            Company(
                                company_id=definition.company_id,
                                name=definition.name,
                                ticker=definition.ticker,
                                sector=definition.sector,
                                exchange=definition.exchange,
                                additional_tickers=",".join(definition.additional_tickers) or None,
                                active=True,
                            )
                        )
                    else:
                        row.name = definition.name
                        row.ticker = definition.ticker
                        row.sector = definition.sector
                        row.exchange = definition.exchange
                        row.additional_tickers = ",".join(definition.additional_tickers) or None

                # spec §15 — one row per listed security, so a multi-class
                # issuer is explicit rather than collapsed to one ticker.
                existing_maps = {
                    (row.company_id, row.ticker): row
                    for row in db.query(CompanySecurityMapping).all()
                }
                for definition in COMPANY_UNIVERSE:
                    for index, ticker in enumerate(definition.all_tickers):
                        mapping = existing_maps.get((definition.company_id, ticker))
                        if mapping is None:
                            db.add(
                                CompanySecurityMapping(
                                    company_id=definition.company_id,
                                    ticker=ticker,
                                    exchange=definition.exchange,
                                    security_type=_classify_security(ticker),
                                    is_primary=index == 0,
                                    source="watch-universe",
                                )
                            )
                        else:
                            mapping.exchange = definition.exchange
                            mapping.security_type = _classify_security(ticker)
                            mapping.is_primary = index == 0
            self._company_registry_ready = True
        except Exception as exc:  # a registry hiccup must not break the leaderboard
            logger.warning("company registry upsert failed: %s", exc)

    async def _profile(self, definition: CompanyDefinition) -> dict:
        """Fetch one company's provider payload, returning ``{}`` on failure."""
        if self._profile_fetcher is None:
            return {}
        try:
            return await self._profile_fetcher(definition.ticker) or {}
        except (ProviderError, Exception) as exc:  # noqa: BLE001 — degrade honestly
            logger.warning("profile fetch failed for %s: %s", definition.ticker, exc)
            return {}

    #: Max simultaneous company-profile requests (bounded so the upstream is not
    #: flooded; the provider manager's own cache still dedupes repeats).
    _PROFILE_CONCURRENCY = 8

    async def _fetch_company_records(self) -> list[CompanyMarketData]:
        """Build ``CompanyMarketData`` for the whole universe concurrently.

        Order is preserved and a failed/empty profile becomes an explicit
        UNAVAILABLE record — never an exception and never an invented value.
        """
        semaphore = asyncio.Semaphore(self._PROFILE_CONCURRENCY)

        async def fetch(definition: CompanyDefinition) -> tuple[CompanyDefinition, dict]:
            async with semaphore:
                return definition, await self._profile(definition)

        fetched = await asyncio.gather(*(fetch(d) for d in COMPANY_UNIVERSE))
        records: list[CompanyMarketData] = []
        for definition, info in fetched:
            source = info.get("source") if isinstance(info, dict) else None
            if not info:
                records.append(
                    CompanyMarketData(
                        company_id=definition.company_id,
                        name=definition.name,
                        ticker=definition.ticker,
                        exchange=definition.exchange,
                        sector=definition.sector,
                        price=None,
                        currency=None,
                        shares_outstanding=None,
                        market_cap=None,
                        observation_timestamp=None,
                        price_source=None,
                        shares_source=None,
                        data_quality=QUALITY_UNAVAILABLE,
                        additional_tickers=definition.additional_tickers,
                        note="Provider returned no data for this company.",
                    )
                )
                continue
            records.append(build_company_market_data(definition, info, source or "provider"))
        return records

    def _previous_ranks(self) -> tuple[dict[str, int], dict[str, float]]:
        """The most recently stored rank and market cap per company (spec §11)."""
        previous_ranks: dict[str, int] = {}
        previous_caps: dict[str, float] = {}
        try:
            with session_scope() as db:
                rows = (
                    db.query(MarketCapRankHistory)
                    .order_by(MarketCapRankHistory.observed_at.desc())
                    .all()
                )
                for row in rows:
                    if row.company_id not in previous_ranks:
                        previous_ranks[row.company_id] = row.rank
                        if row.market_cap is not None:
                            previous_caps[row.company_id] = row.market_cap
        except Exception as exc:
            logger.warning("previous-rank lookup failed: %s", exc)
        return previous_ranks, previous_caps

    @staticmethod
    def _record_from_row(row: CompanyMarketObservation) -> dict:
        return {
            "observed_at": row.observation_timestamp.isoformat() if row.observation_timestamp else None,
            "price": row.price,
            "currency": row.currency,
            "shares_outstanding": row.shares_outstanding,
            "market_cap": row.market_cap,
            "market_cap_methodology": row.market_cap_methodology,
            "data_quality": row.data_quality,
            "price_source": row.price_source,
            "shares_source": row.shares_source,
        }

    def _store_observations(self, records: list[CompanyMarketData]) -> None:
        """Append new observations, skipping ones identical to the last row."""
        try:
            with session_scope() as db:
                for record in records:
                    observed_at = record.observation_timestamp or datetime.now(timezone.utc)

                    # spec §15 — the share count gets its own append-only row with
                    # its own freshness check, so a stale share count can never
                    # hide behind a fresh quote (and the row is written even when
                    # the quote itself was unchanged).
                    if record.shares_outstanding is not None:
                        last_shares = (
                            db.query(SharesOutstandingObservation)
                            .filter(SharesOutstandingObservation.company_id == record.company_id)
                            .order_by(SharesOutstandingObservation.observed_at.desc())
                            .first()
                        )
                        if (
                            last_shares is None
                            or last_shares.shares_outstanding != record.shares_outstanding
                            or last_shares.data_quality != record.data_quality
                        ):
                            db.add(
                                SharesOutstandingObservation(
                                    company_id=record.company_id,
                                    ticker=record.ticker,
                                    observed_at=observed_at,
                                    shares_outstanding=record.shares_outstanding,
                                    source=record.shares_source or record.price_source,
                                    data_quality=record.data_quality,
                                    note=(
                                        "Share count as reported by the provider; the "
                                        "as-of date is the provider's own timestamp."
                                    ),
                                )
                            )

                    latest = (
                        db.query(CompanyMarketObservation)
                        .filter(CompanyMarketObservation.company_id == record.company_id)
                        .order_by(CompanyMarketObservation.observation_timestamp.desc())
                        .first()
                    )
                    new_cap = record.market_cap
                    old_cap = latest.market_cap if latest else None
                    fresh = (
                        latest is None
                        or old_cap != new_cap
                        or record.data_quality != latest.data_quality
                        or (
                            record.observation_timestamp
                            and latest.observation_timestamp
                            and abs(
                                (record.observation_timestamp - _to_datetime(latest.observation_timestamp)).total_seconds()
                            )
                            > 3600
                        )
                    )
                    if not fresh:
                        continue
                    db.add(
                        CompanyMarketObservation(
                            company_id=record.company_id,
                            ticker=record.ticker,
                            price=record.price,
                            currency=record.currency,
                            shares_outstanding=record.shares_outstanding,
                            market_cap=new_cap,
                            market_cap_methodology=record.market_cap_methodology,
                            price_source=record.price_source,
                            shares_source=record.shares_source,
                            data_quality=record.data_quality,
                            observation_timestamp=observed_at,
                            source_document=record.source_document,
                        )
                    )
                    # spec §15 — freeze the exact inputs + derived cap together,
                    # so a historical ranking can always be audited back to the
                    # price, share count, methodology and source it used.
                    db.add(
                        MarketCapSnapshot(
                            company_id=record.company_id,
                            ticker=record.ticker,
                            observed_at=observed_at,
                            price=record.price,
                            currency=record.currency,
                            shares_outstanding=record.shares_outstanding,
                            market_cap=new_cap,
                            market_cap_methodology=record.market_cap_methodology,
                            data_quality=record.data_quality,
                            rank=record.rank,
                            price_source=record.price_source,
                            shares_source=record.shares_source,
                            note=record.note,
                        )
                    )
        except Exception as exc:
            logger.warning("observation persistence failed: %s", exc)

    def _store_rank_snapshot(self, records: list[CompanyMarketData], source: Optional[str]) -> None:
        """Store a rank snapshot no more often than the configured interval."""
        ranked = [r for r in records if r.rank is not None]
        if not ranked:
            return
        try:
            now = datetime.now(timezone.utc)
            with session_scope() as db:
                newest = (
                    db.query(MarketCapRankHistory)
                    .order_by(MarketCapRankHistory.observed_at.desc())
                    .first()
                )
                if newest is not None and newest.observed_at is not None:
                    last = _to_datetime(newest.observed_at)
                    if last and (now - last).total_seconds() < self._rank_snapshot_min_seconds:
                        return
                for record in ranked:
                    db.add(
                        MarketCapRankHistory(
                            company_id=record.company_id,
                            ticker=record.ticker,
                            observed_at=record.observation_timestamp or now,
                            market_cap=record.market_cap,
                            rank=record.rank or 0,
                            data_quality=record.data_quality,
                            source=source,
                        )
                    )
        except Exception as exc:
            logger.warning("rank snapshot persistence failed: %s", exc)

    # ------------------------------------------------------------------- §11
    async def get_leaderboard(
        self, limit: Optional[int] = None, refresh: bool = True
    ) -> dict:
        """Dynamic market-cap leaderboard computed from real observations.

        Profiles are fetched concurrently (bounded by a small semaphore so the
        upstream is not hammered) — sequentially this was 37 round-trips and
        took minutes; per-company failures still degrade to UNAVAILABLE.
        """
        self._ensure_company_registry()
        records: list[CompanyMarketData] = await self._fetch_company_records()

        previous_ranks, previous_caps = self._previous_ranks()
        rank_companies(records, previous_ranks, previous_caps)
        ordered = sorted(
            records,
            key=lambda r: (r.rank is None, r.rank or 10**9, -(r.market_cap or 0.0)),
        )
        if limit:
            ordered = ordered[:limit]
        if refresh:
            self._store_observations(ordered)
            self._store_rank_snapshot(ordered, source=ordered[0].price_source if ordered else None)
        ranked_count = sum(1 for r in ordered if r.market_cap is not None)
        return {
            "companies": [r.as_dict() for r in ordered],
            "count": len(ordered),
            "ranked_count": ranked_count,
            "unavailable_count": len(ordered) - ranked_count,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Ranks are computed from the latest real observations. A company "
                "with no current data is left unranked and flagged — it is never "
                "given an invented market capitalisation."
            ),
        }

    def get_company_history(self, company_id: str, limit: int = 365, offset: int = 0) -> dict:
        """Stored market-cap observation history for one company (spec §14).

        ``limit``/``offset`` page over the stored rows, newest first (spec §16);
        the returned list is still chronological so a chart can plot it directly.
        """
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        limit = max(1, min(5000, limit))
        offset = max(0, int(offset or 0))
        with session_scope() as db:
            rows = (
                db.query(CompanyMarketObservation)
                .filter(CompanyMarketObservation.company_id == definition.company_id)
                .order_by(CompanyMarketObservation.observation_timestamp.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            points = [self._record_from_row(row) for row in reversed(rows)]
            rank_rows = (
                db.query(MarketCapRankHistory)
                .filter(MarketCapRankHistory.company_id == definition.company_id)
                .order_by(MarketCapRankHistory.observed_at.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            ranks = [
                {
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                    "rank": row.rank,
                    "market_cap": row.market_cap,
                    "source": row.source,
                    "data_quality": row.data_quality,
                }
                for row in reversed(rank_rows)
            ]
        return {
            "company_id": definition.company_id,
            "name": definition.name,
            "ticker": definition.ticker,
            "points": points,
            "ranks": ranks,
            "point_count": len(points),
            "page": {"limit": limit, "offset": offset, "returned": len(points)},
            "note": (
                "Only stored real observations are charted. Missing periods are "
                "absent — no historical value is fabricated to fill them."
            ),
        }

    def get_security_mappings(self, company_id: Optional[str] = None) -> dict:
        """Listed securities per company from ``company_security_mappings``.

        Exposes the registry spec §15 asks for so a caller can see exactly which
        tickers a company-wide market cap would aggregate. Unknown company ids
        raise, matching every other company lookup.
        """
        # Populate the declared universe on first use so the endpoint answers
        # even before a leaderboard refresh has run (the registry upsert is
        # idempotent and cheap).
        self._ensure_company_registry()
        definition = None
        if company_id:
            definition = get_company(company_id)
            if definition is None:
                raise ValueError(f"Unknown company '{company_id}'.")
        with session_scope() as db:
            query = db.query(CompanySecurityMapping)
            if definition is not None:
                query = query.filter(CompanySecurityMapping.company_id == definition.company_id)
            rows = query.order_by(
                CompanySecurityMapping.company_id.asc(),
                CompanySecurityMapping.is_primary.desc(),
            ).all()
            mappings = [
                {
                    "company_id": row.company_id,
                    "ticker": row.ticker,
                    "exchange": row.exchange,
                    "currency": row.currency,
                    "security_type": row.security_type,
                    "is_primary": bool(row.is_primary),
                    "source": row.source,
                }
                for row in rows
            ]
        return {
            "company_id": definition.company_id if definition is not None else None,
            "mappings": mappings,
            "count": len(mappings),
            "note": (
                "One row per listed security. A company with several classes is "
                "mapped explicitly rather than assumed to have a single ticker."
            ),
        }

    def get_market_cap_snapshots(self, company_id: str, limit: int = 365) -> dict:
        """Materialised market-cap snapshots with their frozen inputs (spec §15)."""
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        limit = max(1, min(5000, limit))
        with session_scope() as db:
            rows = (
                db.query(MarketCapSnapshot)
                .filter(MarketCapSnapshot.company_id == definition.company_id)
                .order_by(MarketCapSnapshot.observed_at.desc())
                .limit(limit)
                .all()
            )
            snapshots = [
                {
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                    "price": row.price,
                    "currency": row.currency,
                    "shares_outstanding": row.shares_outstanding,
                    "market_cap": row.market_cap,
                    "market_cap_methodology": row.market_cap_methodology,
                    "data_quality": row.data_quality,
                    "rank": row.rank,
                    "price_source": row.price_source,
                    "shares_source": row.shares_source,
                    "note": row.note,
                }
                for row in reversed(rows)
            ]
        return {
            "company_id": definition.company_id,
            "name": definition.name,
            "ticker": definition.ticker,
            "snapshots": snapshots,
            "count": len(snapshots),
            "note": "Each snapshot freezes the exact inputs and source it used.",
        }

    def get_shares_outstanding(self, company_id: str, limit: int = 365) -> dict:
        """Append-only share-count observations (spec §15).

        Kept separate from the quote so a market-cap comparison can show when
        the share count is older than the price rather than silently mixing the
        two.
        """
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        limit = max(1, min(5000, limit))
        with session_scope() as db:
            rows = (
                db.query(SharesOutstandingObservation)
                .filter(SharesOutstandingObservation.company_id == definition.company_id)
                .order_by(SharesOutstandingObservation.observed_at.desc())
                .limit(limit)
                .all()
            )
            observations = [
                {
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                    "shares_outstanding": row.shares_outstanding,
                    "source": row.source,
                    "data_quality": row.data_quality,
                    "note": row.note,
                }
                for row in reversed(rows)
            ]
        return {
            "company_id": definition.company_id,
            "name": definition.name,
            "ticker": definition.ticker,
            "observations": observations,
            "count": len(observations),
            "note": "Share counts are stored with their own as-of date and source.",
        }

    def get_rank_history(self, limit: int = 500) -> dict:
        """Stored rank snapshots across companies, grouped per ticker (spec §14).

        This is the cross-company view of the same real ``market_cap_rank_history``
        rows the per-company chart uses — observation date, market cap, rank and
        source — so a ranking timeline can be charted without fabricating any
        period that was never observed.
        """
        limit = max(1, min(5000, limit))
        # Build the payload INSIDE the session: the session commits on exit, so
        # reading row attributes afterwards would hit expired/detached instances.
        with session_scope() as db:
            rows = (
                db.query(MarketCapRankHistory)
                .order_by(MarketCapRankHistory.observed_at.asc())
                .limit(limit)
                .all()
            )
            grouped: dict[str, list[dict]] = {}
            for row in rows:
                grouped.setdefault(row.ticker, []).append(
                    {
                        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                        "market_cap": row.market_cap,
                        "rank": row.rank,
                        "source": row.source,
                        "data_quality": row.data_quality,
                    }
                )
            observation_count = len(rows)
        return {
            "series": [
                {"ticker": ticker, "points": points}
                for ticker, points in sorted(grouped.items())
            ],
            "observation_count": observation_count,
            "note": (
                "Only stored rank snapshots are charted. A company absent at an "
                "observation time is a gap, never a fabricated rank."
            ),
        }

    # --------------------------------------------------- §10 corporate actions
    async def refresh_corporate_actions(self, company_id: str) -> dict:
        """Ingest provider-reported stock splits as real corporate actions.

        This is the source-backed counterpart to manual recording: a split the
        provider reports is stored with its effective date and ratio, which is
        what lets a market-cap comparison across the split be flagged rather
        than presented as pure growth. Idempotent — re-running records nothing
        twice. Buybacks/issuance remain manual because the provider does not
        publish them as machine-readable events here.
        """
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        base = {
            "company_id": definition.company_id,
            "name": definition.name,
            "ticker": definition.ticker,
        }
        if self._splits_fetcher is None:
            return {
                **base,
                "source": None,
                "status": DataStatus.UNAVAILABLE.value,
                "reason": "No splits source is configured.",
                "splits_found": 0,
                "recorded": 0,
                "events": [],
            }
        try:
            splits, source, status = await self._splits_fetcher(definition.ticker)
        except ProviderError as exc:
            return {
                **base,
                "source": None,
                "status": DataStatus.UNAVAILABLE.value,
                "reason": str(exc),
                "splits_found": 0,
                "recorded": 0,
                "events": [],
            }
        except Exception as exc:  # provider surprises must not 500 the request
            logger.warning("splits fetch failed for %s: %s", definition.ticker, exc)
            return {
                **base,
                "source": None,
                "status": DataStatus.UNAVAILABLE.value,
                "reason": f"Splits unavailable: {exc}",
                "splits_found": 0,
                "recorded": 0,
                "events": [],
            }

        recorded = 0
        events = []
        for split in splits or []:
            day = split.get("date")
            if not day:
                continue
            result = self.record_corporate_action(
                definition.company_id,
                "SPLIT",
                day,
                ratio=split.get("ratio"),
                source=source or "provider",
                notes=(
                    "Auto-ingested from the provider's split feed; ratio is new "
                    "shares per old share."
                ),
            )
            if result.get("created"):
                recorded += 1
            events.append(result)
        return {
            **base,
            "source": source,
            "status": getattr(status, "value", status),
            "splits_found": len(events),
            "recorded": recorded,
            "events": events,
            "note": (
                "Only provider-reported splits are stored. A price/share "
                "comparison across a stored split is adjusted, not presented "
                "as growth."
            ),
        }

    # ------------------------------------------------------------------- §13
    async def get_scenario(self, company_id: str, scenario_return: float) -> dict:
        """Hypothetical scenario arithmetic for one company (spec §13)."""
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        if scenario_return <= -1:
            raise ValueError("scenario_return must be greater than -1 (-100%).")
        leaderboard = await self.get_leaderboard(refresh=False)
        record = next(
            (r for r in leaderboard["companies"] if r["company_id"] == definition.company_id),
            None,
        )
        if record is None:
            raise ValueError(f"No market data available for '{company_id}'.")
        reference_price = record.get("price")
        shares = record.get("shares_outstanding")
        result = scenario_market_cap(reference_price, shares, scenario_return)
        result.update(
            {
                "company_id": definition.company_id,
                "name": definition.name,
                "ticker": definition.ticker,
                "currency": record.get("currency"),
                "reference_price": reference_price,
                "shares_outstanding": shares,
                "reference_market_cap": record.get("market_cap"),
                "reference_data_quality": record.get("data_quality"),
                "reference_observation_timestamp": record.get("observation_timestamp"),
                "price_source": record.get("price_source"),
                "shares_source": record.get("shares_source"),
            }
        )
        return result

    # ------------------------------------------------------------------- §12
    async def get_race(self, period_days: int = 180) -> dict:
        """Descriptive market-cap race over the observed period (spec §12)."""
        leaderboard = await self.get_leaderboard(refresh=False)
        since = datetime.now(timezone.utc) - timedelta(days=max(1, min(3650, period_days)))
        history: dict[str, list[dict]] = {}
        with session_scope() as db:
            rows = (
                db.query(MarketCapRankHistory)
                .filter(MarketCapRankHistory.observed_at >= since)
                .order_by(MarketCapRankHistory.observed_at.asc())
                .all()
            )
            for row in rows:
                history.setdefault(row.company_id, []).append(
                    {
                        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                        "market_cap": row.market_cap,
                        "rank": row.rank,
                    }
                )
        records = [
            CompanyMarketData(
                company_id=row["company_id"],
                name=row["name"],
                ticker=row["ticker"],
                exchange=row.get("exchange"),
                sector=row.get("sector"),
                price=row.get("price"),
                currency=row.get("currency"),
                shares_outstanding=row.get("shares_outstanding"),
                market_cap=row.get("market_cap"),
                observation_timestamp=None,
                price_source=row.get("price_source"),
                shares_source=row.get("shares_source"),
                data_quality=row.get("data_quality", QUALITY_UNAVAILABLE),
                rank=row.get("rank"),
            )
            for row in leaderboard["companies"]
        ]
        payload = market_cap_race(records, history)
        payload["period_days"] = period_days
        payload["observation_start"] = since.isoformat()
        return payload

    # -------------------------------------------------------------------- §7
    async def get_event_study(
        self,
        bank_id: str,
        instrument_key: str = "spx",
        lookback_decisions: int = 4,
        windows: Optional[list[int]] = None,
    ) -> dict:
        """SPX/SPY event study around Phase 23A policy decisions (spec §7).

        Reuses the Phase 23A event-window engine with the instrument's *real
        provider symbol*, so the index level (``^GSPC``) and the ETF (``SPY``)
        are kept strictly separate. Output is observational, not causal.
        """
        instrument = self._instrument(instrument_key)
        windows = windows or [1, 3, 5, 10, 20]
        if self._macro_service is None:
            return {
                "bank_id": bank_id,
                "instrument": instrument.as_dict(),
                "results": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "reason": "Phase 23A macro service is not bound.",
            }
        analysis = await self._macro_service.event_window_analysis(
            bank_id,
            ticker=instrument.symbol,
            lookback_decisions=max(1, min(40, lookback_decisions)),
            windows=windows,
        )
        return {
            "bank_id": bank_id,
            "instrument": instrument.as_dict(),
            "return_formula": "close[i]/close[0] - 1 over each observation window",
            "windows": windows,
            "analysis_type": "OBSERVATIONAL",
            "results": analysis.get("results", []),
            "count": analysis.get("count", 0),
            "status": analysis.get("status"),
            "reason": analysis.get("reason"),
            "market_source": analysis.get("market_source"),
            "market_status": analysis.get("market_status"),
            "history_start": analysis.get("history_start"),
            "history_end": analysis.get("history_end"),
            "note": (
                "Historical observation only. A price move near a decision date is "
                "not evidence that the decision caused it."
            ),
        }

    # ------------------------------------------------------ §10 corporate actions
    def record_corporate_action(
        self,
        company_id: str,
        action_type: str,
        effective_date,
        ratio: Optional[float] = None,
        source: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Store a source-reported corporate action (spec §10, §15).

        Only actions a source actually reports are stored — nothing is inferred.
        A duplicate (same company + type + date) is idempotent rather than an
        error, so a repeated refresh cannot create phantom history.
        """
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        action = (action_type or "").strip().upper()
        if action not in {"SPLIT", "BUYBACK", "ISSUANCE", "OTHER"}:
            raise ValueError("action_type must be SPLIT, BUYBACK, ISSUANCE or OTHER.")
        when = _to_datetime(effective_date)
        if when is None:
            raise ValueError("effective_date must be an ISO date or timestamp.")
        with session_scope() as db:
            existing = (
                db.query(CorporateActionEvent)
                .filter(
                    CorporateActionEvent.company_id == definition.company_id,
                    CorporateActionEvent.action_type == action,
                    CorporateActionEvent.effective_date == when.replace(tzinfo=None),
                )
                .first()
            )
            if existing:
                return {
                    "id": existing.id,
                    "company_id": existing.company_id,
                    "action_type": existing.action_type,
                    "ratio": existing.ratio,
                    "effective_date": existing.effective_date.isoformat(),
                    "source": existing.source,
                    "notes": existing.notes,
                    "created": False,
                }
            row = CorporateActionEvent(
                company_id=definition.company_id,
                action_type=action,
                ratio=ratio,
                effective_date=when.replace(tzinfo=None),
                source=source,
                notes=notes,
            )
            db.add(row)
            db.flush()
            return {
                "id": row.id,
                "company_id": row.company_id,
                "action_type": row.action_type,
                "ratio": row.ratio,
                "effective_date": row.effective_date.isoformat(),
                "source": row.source,
                "notes": row.notes,
                "created": True,
            }

    def get_corporate_actions(self, company_id: str, limit: int = 100) -> dict:
        """Reported corporate actions for one company (spec §10, §14)."""
        definition = get_company(company_id)
        if definition is None:
            raise ValueError(f"Unknown company '{company_id}'.")
        limit = max(1, min(1000, limit))
        with session_scope() as db:
            rows = (
                db.query(CorporateActionEvent)
                .filter(CorporateActionEvent.company_id == definition.company_id)
                .order_by(CorporateActionEvent.effective_date.desc())
                .limit(limit)
                .all()
            )
            actions = [
                {
                    "id": row.id,
                    "company_id": row.company_id,
                    "action_type": row.action_type,
                    "ratio": row.ratio,
                    "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                    "source": row.source,
                    "notes": row.notes,
                }
                for row in rows
            ]
        return {
            "company_id": definition.company_id,
            "actions": actions,
            "count": len(actions),
            "note": (
                "Only source-reported actions are listed. A split/buyback/issuance "
                "makes a raw price or share comparison invalid, so a cap computed "
                "across it is marked ESTIMATED rather than presented as growth."
            ),
        }

    # ------------------------------------------------------------------ health
    def health(self) -> dict:
        return {
            "status": "ok",
            "market_data_configured": self._market_history is not None,
            "profile_configured": self._profile_fetcher is not None,
            "splits_configured": self._splits_fetcher is not None,
            "macro_service_configured": self._macro_service is not None,
            "instruments": list(INSTRUMENTS.keys()),
            "company_universe_size": len(COMPANY_UNIVERSE),
            "direction_engine": "MarketDirectionEngine",
            "analytics_backend": "numpy+scipy",
            "tables": [
                "companies",
                "company_security_mappings",
                "company_market_observations",
                "shares_outstanding_observations",
                "market_cap_snapshots",
                "market_cap_rank_history",
                "corporate_action_events",
            ],
            "services": [
                "IndexDataService",
                "MarketDirectionService",
                "CompanyDataService",
                "MarketCapService",
                "CorporateActionService",
                "MarketScenarioService",
            ],
        }


#: Process-wide instance, configured by the app shell (mirrors macro_service).
market_intel_service = MarketIntelligenceService()


def configure_market_intel(
    history_fetcher,
    profile_fetcher=None,
    macro_service=None,
    splits_fetcher=None,
) -> MarketIntelligenceService:
    market_intel_service.configure(
        history_fetcher, profile_fetcher, macro_service, splits_fetcher
    )
    return market_intel_service
