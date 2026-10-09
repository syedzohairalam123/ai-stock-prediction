"""
Phase 23A — Macro Intelligence Service layer.

Coordinates data fetching from sources, database operations, and provides
API-ready responses. Handles caching, error handling, and data validation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..db import session_scope
from ..models import (
    CentralBank as CentralBankModel,
    PolicyMeeting as PolicyMeetingModel,
    PolicyDecision as PolicyDecisionModel,
    PolicyExpectation as PolicyExpectationModel,
    MacroSeries as MacroSeriesModel,
)
from .models import (
    CentralBankInfo,
    PolicyMeetingInfo,
    PolicyDecisionInfo,
    PolicyExpectationInfo,
    MacroSeriesInfo,
    CountdownInfo,
    RateHistoryPoint,
    MeetingStatus,
    DecisionDirection,
    calculate_bps_change,
    determine_direction,
    calculate_countdown,
)
from .sources import (
    BaseCentralBankSource,
    FederalReserveSource,
    BankOfJapanSource,
    FREDSource,
    FRED_SERIES,
    FRED_SERIES_LABELS,
    DEFAULT_INDICATOR_KEYS,
)
from .analytics import analyze_event_window

logger = logging.getLogger("neural_market.macro_intelligence.service")

# ---------------------------------------------------------------------------
# Central-bank source registry
#
# A bank is served because a source adapter is registered for its id — not
# because of any branch inside the service. Adding the ECB, Bank of England,
# Bank of Canada, RBA or SNB later is therefore a registration plus that bank's
# metadata row (spec §3), never a change to the engine: the fetch/normalise/
# store/API path is shared by every registered bank.
#
# Each factory takes the configured FRED API key (``None`` when unset) and
# returns a source adapter. Adapters that do not need a key simply ignore it.
# ---------------------------------------------------------------------------

CentralBankSourceFactory = Callable[[Optional[str]], BaseCentralBankSource]

CENTRAL_BANK_SOURCE_FACTORIES: dict[str, CentralBankSourceFactory] = {
    "FED": lambda key: FederalReserveSource(api_key=key),
    "BOJ": lambda key: BankOfJapanSource(),
}


def register_central_bank_source(
    bank_id: str, factory: CentralBankSourceFactory
) -> None:
    """Register (or replace) a source adapter factory for a central bank.

    Public so future-bank support is explicitly additive; the engines call
    ``available_source_banks()``/``_get_source()`` and never enumerate banks
    themselves.
    """
    CENTRAL_BANK_SOURCE_FACTORIES[bank_id.upper()] = factory


def available_source_banks() -> list[str]:
    """Ids for which a real source adapter is registered, sorted."""
    return sorted(CENTRAL_BANK_SOURCE_FACTORIES)


#: Institution metadata for the banks the engine ships with (spec §3).
#: Adding a future bank is one entry here plus one source registration above;
#: nothing in the service, routes or models hardcodes a bank id.
CENTRAL_BANK_CATALOGUE: dict[str, dict[str, str]] = {
    "FED": {
        "name": "Federal Reserve",
        "country": "United States",
        "currency": "USD",
        "timezone": "America/New_York",
        "source": "federal_reserve",
    },
    "BOJ": {
        "name": "Bank of Japan",
        "country": "Japan",
        "currency": "JPY",
        "timezone": "Asia/Tokyo",
        "source": "boj",
    },
}


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return a UTC-aware datetime.

    SQLite (and the SQLAlchemy ``DateTime`` columns here) round-trips
    timezone-aware values as *naive* ones. Every timestamp was written as
    UTC, so a naive value read back is UTC — this restores the tzinfo before
    any subtraction against ``datetime.now(timezone.utc)``, which would
    otherwise raise "can't subtract offset-naive and offset-aware datetimes".
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MacroIntelligenceService:
    """Service for central bank and macro data operations."""

    def __init__(self):
        self.fred_api_key = settings.macro_fred_api_key or settings.fred_api_key
        self._sources: dict[str, BaseCentralBankSource] = {}
        self._fred_source: Optional[FREDSource] = None
        # Optional async market-history fetcher bound by the app shell so the
        # event-window analytics reuse the SAME real provider path as every
        # other chart in the terminal (no second data service is created).
        self._market_history = None

    def configure_market_data(self, history_fetcher) -> None:
        """Bind ``async fn(ticker, start, end, interval) -> (frame, source, status)``."""
        self._market_history = history_fetcher

    def _get_source(self, bank_id: str) -> Optional[BaseCentralBankSource]:
        """Get or create the registered source adapter for a central bank.

        Resolution goes through ``CENTRAL_BANK_SOURCE_FACTORIES`` so a new bank
        needs only a registration — no engine branch. An unknown bank returns
        ``None`` and the callers degrade honestly (empty result, never data
        invented for a bank the engine cannot actually read).
        """
        bank_id = bank_id.upper()
        if bank_id not in self._sources:
            factory = CENTRAL_BANK_SOURCE_FACTORIES.get(bank_id)
            if factory is None:
                logger.warning(
                    "No source adapter registered for bank_id: %s "
                    "(registered: %s)",
                    bank_id,
                    ", ".join(available_source_banks()) or "none",
                )
                return None
            self._sources[bank_id] = factory(self.fred_api_key)
        return self._sources[bank_id]

    def _get_fred_source(self) -> FREDSource:
        """Get or create the FRED source.

        Works with or without an API key: with a key it uses FRED's JSON API
        (true release dates), without one it falls back to the public keyless
        CSV endpoint, so real macro data is available on a fresh install too.
        """
        if self._fred_source is None:
            self._fred_source = FREDSource(api_key=self.fred_api_key or "")
        return self._fred_source

    # -----------------------------------------------------------------------
    # Central Bank operations
    # -----------------------------------------------------------------------

    def list_central_banks(self) -> list[dict]:
        """List all configured central banks."""
        with session_scope() as db:
            banks = db.query(CentralBankModel).filter(CentralBankModel.active == True).all()
            return [
                {
                    "id": bank.id,
                    "name": bank.name,
                    "country": bank.country,
                    "currency": bank.currency,
                    "timezone": bank.timezone,
                    "source": bank.source,
                }
                for bank in banks
            ]

    def get_central_bank(self, bank_id: str) -> Optional[dict]:
        """Get central bank details by ID."""
        with session_scope() as db:
            bank = db.query(CentralBankModel).filter(
                CentralBankModel.id == bank_id,
                CentralBankModel.active == True
            ).first()
            if not bank:
                return None
            return {
                "id": bank.id,
                "name": bank.name,
                "country": bank.country,
                "currency": bank.currency,
                "timezone": bank.timezone,
                "source": bank.source,
            }

    def initialize_central_banks(self):
        """Initialize the catalogue's central banks in the database.

        Driven by ``CENTRAL_BANK_CATALOGUE`` (spec §3), so a future bank is a
        data entry rather than code. Existing rows are left untouched.
        """
        default_banks = [
            CentralBankInfo(
                id=bank_id,
                name=meta["name"],
                country=meta["country"],
                currency=meta["currency"],
                timezone=meta["timezone"],
                source=meta["source"],
            )
            for bank_id, meta in CENTRAL_BANK_CATALOGUE.items()
        ]

        with session_scope() as db:
            for bank_info in default_banks:
                existing = db.query(CentralBankModel).filter(CentralBankModel.id == bank_info.id).first()
                if not existing:
                    bank = CentralBankModel(
                        id=bank_info.id,
                        name=bank_info.name,
                        country=bank_info.country,
                        currency=bank_info.currency,
                        timezone=bank_info.timezone,
                        source=bank_info.source,
                        active=True,
                    )
                    db.add(bank)
                    logger.info("Initialized central bank: %s", bank_info.id)

    # -----------------------------------------------------------------------
    # Policy Meeting operations
    # -----------------------------------------------------------------------

    def fetch_and_store_meetings(self, bank_id: str, limit: int = 20) -> list[dict]:
        """Fetch meetings from source and store in database."""
        source = self._get_source(bank_id)
        if not source:
            logger.warning("No source available for bank_id: %s", bank_id)
            return []

        try:
            meetings_info = source.fetch_meetings(limit=limit)

            with session_scope() as db:
                stored_meetings = []
                for meeting_info in meetings_info:
                    # Check if meeting already exists
                    existing = db.query(PolicyMeetingModel).filter(
                        PolicyMeetingModel.central_bank_id == bank_id,
                        PolicyMeetingModel.scheduled_at == meeting_info.scheduled_at
                    ).first()

                    if existing:
                        # Update existing meeting
                        existing.status = meeting_info.status.value
                        existing.source_url = meeting_info.source_url
                        existing.updated_at = datetime.now(timezone.utc)
                        meeting_id = existing.id
                    else:
                        # Create new meeting
                        meeting = PolicyMeetingModel(
                            central_bank_id=bank_id,
                            scheduled_at=meeting_info.scheduled_at,
                            timezone=meeting_info.timezone,
                            status=meeting_info.status.value,
                            source_url=meeting_info.source_url,
                            source_timestamp=meeting_info.source_timestamp,
                            meeting_type=meeting_info.meeting_type.value,
                        )
                        db.add(meeting)
                        db.flush()
                        meeting_id = meeting.id

                    stored_meetings.append({
                        "id": meeting_id,
                        "central_bank_id": bank_id,
                        "scheduled_at": meeting_info.scheduled_at.isoformat() if meeting_info.scheduled_at else None,
                        "timezone": meeting_info.timezone,
                        "status": meeting_info.status.value,
                        "meeting_type": meeting_info.meeting_type.value,
                        "source_url": meeting_info.source_url,
                    })

                logger.info("Fetched and stored %d meetings for %s", len(stored_meetings), bank_id)
                return stored_meetings

        except Exception as e:
            logger.error("Failed to fetch meetings for %s: %s", bank_id, e)
            return []

    def get_upcoming_meetings(self, bank_id: Optional[str] = None, limit: int = 10) -> list[dict]:
        """Get upcoming policy meetings with countdown."""
        with session_scope() as db:
            query = db.query(PolicyMeetingModel).filter(
                PolicyMeetingModel.status.in_(["UPCOMING", "IN_PROGRESS"])
            )

            if bank_id:
                query = query.filter(PolicyMeetingModel.central_bank_id == bank_id)

            meetings = query.order_by(PolicyMeetingModel.scheduled_at).limit(limit).all()

            result = []
            now = datetime.now(timezone.utc)

            for meeting in meetings:
                scheduled_at = _as_utc(meeting.scheduled_at)
                countdown = calculate_countdown(scheduled_at, now)

                # Get latest decision for this bank
                latest_decision = db.query(PolicyDecisionModel).join(
                    PolicyMeetingModel,
                    PolicyDecisionModel.meeting_id == PolicyMeetingModel.id
                ).filter(
                    PolicyMeetingModel.central_bank_id == meeting.central_bank_id
                ).order_by(PolicyDecisionModel.decision_timestamp.desc()).first()

                current_rate = latest_decision.new_rate if latest_decision else None
                previous_direction = latest_decision.direction if latest_decision else None

                result.append({
                    "id": meeting.id,
                    "central_bank_id": meeting.central_bank_id,
                    "scheduled_at": scheduled_at.isoformat(),
                    "timezone": meeting.timezone,
                    "status": meeting.status,
                    "meeting_type": meeting.meeting_type,
                    "countdown": {
                        "days": countdown.days,
                        "hours": countdown.hours,
                        "minutes": countdown.minutes,
                        "seconds": countdown.seconds,
                        "total_seconds": countdown.total_seconds,
                        "is_past": countdown.is_past,
                    },
                    "current_policy_rate": current_rate,
                    "previous_decision": previous_direction,
                    "source_url": meeting.source_url,
                    # When the source itself was captured (§8 "Last Updated").
                    "source_timestamp": (
                        _as_utc(meeting.source_timestamp).isoformat()
                        if meeting.source_timestamp else None
                    ),
                })

            return result

    # -----------------------------------------------------------------------
    # Policy Decision operations
    # -----------------------------------------------------------------------

    def fetch_and_store_decisions(self, bank_id: str, limit: int = 50) -> list[dict]:
        """Fetch policy decisions from source and store in database."""
        source = self._get_source(bank_id)
        if not source:
            logger.warning("No source available for bank_id: %s", bank_id)
            return []

        try:
            decisions_info = source.fetch_decisions(limit=limit)

            with session_scope() as db:
                stored_decisions = []
                for decision_info in decisions_info:
                    # Find or create meeting for this decision
                    meeting = db.query(PolicyMeetingModel).filter(
                        PolicyMeetingModel.central_bank_id == bank_id,
                        PolicyMeetingModel.scheduled_at == decision_info.decision_timestamp
                    ).first()

                    if not meeting:
                        meeting = PolicyMeetingModel(
                            central_bank_id=bank_id,
                            scheduled_at=decision_info.decision_timestamp,
                            timezone="UTC",
                            status="COMPLETED",
                            meeting_type="REGULAR",
                        )
                        db.add(meeting)
                        db.flush()

                    # Check if decision already exists
                    existing = db.query(PolicyDecisionModel).filter(
                        PolicyDecisionModel.meeting_id == meeting.id
                    ).first()

                    if not existing:
                        decision = PolicyDecisionModel(
                            meeting_id=meeting.id,
                            previous_rate=decision_info.previous_rate,
                            new_rate=decision_info.new_rate,
                            change_bps=decision_info.change_bps,
                            direction=decision_info.direction.value,
                            decision_timestamp=decision_info.decision_timestamp,
                            source=decision_info.source,
                            source_document=decision_info.source_document,
                            notes=decision_info.notes,
                        )
                        db.add(decision)
                        db.flush()
                        decision_id = decision.id
                    else:
                        decision_id = existing.id

                    stored_decisions.append({
                        "id": decision_id,
                        "meeting_id": meeting.id,
                        "previous_rate": decision_info.previous_rate,
                        "new_rate": decision_info.new_rate,
                        "change_bps": decision_info.change_bps,
                        "direction": decision_info.direction.value,
                        "decision_timestamp": decision_info.decision_timestamp.isoformat(),
                        "source": decision_info.source,
                    })

                logger.info("Fetched and stored %d decisions for %s", len(stored_decisions), bank_id)
                return stored_decisions

        except Exception as e:
            logger.error("Failed to fetch decisions for %s: %s", bank_id, e)
            return []

    def get_policy_history(self, bank_id: str, limit: int = 50) -> list[dict]:
        """Get historical policy rate decisions for a central bank."""
        with session_scope() as db:
            decisions = db.query(PolicyDecisionModel).join(
                PolicyMeetingModel,
                PolicyDecisionModel.meeting_id == PolicyMeetingModel.id
            ).filter(
                PolicyMeetingModel.central_bank_id == bank_id
            ).order_by(PolicyDecisionModel.decision_timestamp.desc()).limit(limit).all()

            return [
                {
                    "id": d.id,
                    "meeting_id": d.meeting_id,
                    "previous_rate": d.previous_rate,
                    "new_rate": d.new_rate,
                    "change_bps": d.change_bps,
                    "direction": d.direction,
                    "decision_timestamp": d.decision_timestamp.isoformat(),
                    "source": d.source,
                    "source_document": d.source_document,
                }
                for d in decisions
            ]

    # -----------------------------------------------------------------------
    # Policy Expectation operations
    # -----------------------------------------------------------------------

    def fetch_and_store_expectations(self, bank_id: str, meeting_id: Optional[int] = None) -> list[dict]:
        """Fetch market expectations from legitimate sources."""
        source = self._get_source(bank_id)
        if not source:
            logger.warning("No source available for bank_id: %s", bank_id)
            return []

        try:
            expectations_info = source.fetch_expectations(meeting_id)

            with session_scope() as db:
                stored_expectations = []
                for exp_info in expectations_info:
                    expectation = PolicyExpectationModel(
                        meeting_id=exp_info.meeting_id,
                        source=exp_info.source,
                        observed_at=exp_info.observed_at,
                        expected_outcome=exp_info.expected_outcome,
                        expected_rate_min=exp_info.expected_rate_min,
                        expected_rate_max=exp_info.expected_rate_max,
                        probability_hike=exp_info.probability_hike,
                        probability_cut=exp_info.probability_cut,
                        probability_unchanged=exp_info.probability_unchanged,
                        methodology=exp_info.methodology,
                    )
                    db.add(expectation)
                    db.flush()

                    stored_expectations.append({
                        "id": expectation.id,
                        "meeting_id": expectation.meeting_id,
                        "source": expectation.source,
                        "observed_at": expectation.observed_at.isoformat(),
                        "expected_outcome": expectation.expected_outcome,
                        "expected_rate_min": expectation.expected_rate_min,
                        "expected_rate_max": expectation.expected_rate_max,
                        "probability_hike": expectation.probability_hike,
                        "probability_cut": expectation.probability_cut,
                        "probability_unchanged": expectation.probability_unchanged,
                        "methodology": expectation.methodology,
                    })

                logger.info("Fetched and stored %d expectations for %s", len(stored_expectations), bank_id)
                return stored_expectations

        except Exception as e:
            logger.error("Failed to fetch expectations for %s: %s", bank_id, e)
            return []

    def get_expectation_history(self, bank_id: str, limit: int = 50) -> dict:
        """Stored, sourced expectation snapshots for one bank (spec §7).

        Every row is a snapshot a legitimate source actually published, kept
        append-only so the change in expectations over time stays visible.
        Where no configured source publishes machine-readable probabilities
        (CME FedWatch requires a data agreement) the response says exactly
        that instead of fabricating a number (spec §2).
        """
        with session_scope() as db:
            rows = (
                db.query(PolicyExpectationModel, PolicyMeetingModel)
                .join(
                    PolicyMeetingModel,
                    PolicyExpectationModel.meeting_id == PolicyMeetingModel.id,
                )
                .filter(PolicyMeetingModel.central_bank_id == bank_id)
                .order_by(PolicyExpectationModel.observed_at.desc())
                .limit(limit)
                .all()
            )
            snapshots = []
            for exp, meeting in rows:
                probabilities = {
                    "hike": exp.probability_hike,
                    "cut": exp.probability_cut,
                    "unchanged": exp.probability_unchanged,
                }
                provided = [v for v in probabilities.values() if v is not None]
                total = round(sum(provided), 6) if provided else None
                probability_note = None
                if total is not None:
                    if 99.0 <= total <= 101.0:
                        probability_note = (
                            "Source-reported probabilities sum to ~100% within rounding tolerance."
                        )
                    else:
                        probability_note = (
                            "Source reports a partial distribution; the remainder belongs to "
                            "the source's own methodology and is not filled in here."
                        )
                snapshots.append(
                    {
                        "id": exp.id,
                        "meeting_id": exp.meeting_id,
                        "central_bank_id": meeting.central_bank_id,
                        "meeting_scheduled_at": (
                            _as_utc(meeting.scheduled_at).isoformat()
                            if meeting.scheduled_at else None
                        ),
                        "source": exp.source,
                        "observed_at": (
                            _as_utc(exp.observed_at).isoformat()
                            if exp.observed_at else None
                        ),
                        "expected_outcome": exp.expected_outcome,
                        "expected_rate_min": exp.expected_rate_min,
                        "expected_rate_max": exp.expected_rate_max,
                        "probabilities": {k: v for k, v in probabilities.items() if v is not None},
                        "probability_total": total,
                        "probability_note": probability_note,
                        "methodology": exp.methodology,
                        "source_url": getattr(exp, "source_url", None),
                        "data_quality": "SOURCE-REPORTED",
                    }
                )

        if not snapshots:
            return {
                "central_bank_id": bank_id,
                "snapshots": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "expectation_source": None,
                "statement": "Market-implied expectations unavailable.",
                "note": (
                    "No configured source publishes machine-readable market-implied policy "
                    "probabilities on the keyless tier, so no expectation row is stored or "
                    "shown rather than inventing one."
                ),
            }

        sources = sorted({s["source"] for s in snapshots if s["source"]})
        return {
            "central_bank_id": bank_id,
            "snapshots": snapshots,
            "count": len(snapshots),
            "status": "LIVE",
            "expectation_source": sources,
            "statement": "Sourced expectation snapshots (oldest → newest history preserved).",
            "note": (
                "Market expectations are not the central bank's official decision; they are "
                "what a named source implied at a named timestamp."
            ),
        }

    async def event_window_analysis(
        self,
        bank_id: str,
        ticker: str = "^GSPC",
        lookback_decisions: int = 4,
        windows: Optional[list[int]] = None,
    ) -> dict:
        """Market observations around completed policy decisions (spec §10).

        One real market-history request covers every analysed decision, then
        each decision is measured against the closes around it. Results are
        historical observations only — the engine never claims a price move
        was caused by the decision.
        """
        windows = windows or [1, 3, 5, 10, 20]
        decisions = self.get_policy_history(bank_id, limit=lookback_decisions)
        if not decisions:
            return {
                "central_bank_id": bank_id,
                "ticker": ticker,
                "results": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "reason": "No stored policy decisions to analyze yet — refresh the policy history first.",
            }
        if self._market_history is None:
            return {
                "central_bank_id": bank_id,
                "ticker": ticker,
                "results": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "reason": "Market-data source not configured for event-window analysis.",
            }

        decision_dates = []
        for row in decisions:
            try:
                decision_dates.append(datetime.fromisoformat(row["decision_timestamp"]))
            except (TypeError, ValueError):
                continue
        if not decision_dates:
            return {
                "central_bank_id": bank_id,
                "ticker": ticker,
                "results": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "reason": "Stored decisions have no usable timestamps.",
            }

        start = (min(decision_dates) - timedelta(days=60)).date()
        end = datetime.now(timezone.utc).date()
        try:
            frame, market_source, market_status = await self._market_history(ticker, start, end, "1d")
        except Exception as exc:
            return {
                "central_bank_id": bank_id,
                "ticker": ticker,
                "results": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "reason": f"Market history unavailable: {exc}",
                "market_source": None,
            }

        market_data = []
        for idx, row in frame.iterrows():
            date_attr = getattr(idx, "date", None)
            day = date_attr() if callable(date_attr) else idx
            market_data.append({"date": str(day)[:10], "close": float(row["Close"])})

        if not market_data:
            return {
                "central_bank_id": bank_id,
                "ticker": ticker,
                "results": [],
                "count": 0,
                "status": "UNAVAILABLE",
                "reason": "Market history returned no usable rows.",
                "market_source": market_source,
            }

        results = []
        for row in decisions:
            decision_dt = datetime.fromisoformat(row["decision_timestamp"])
            analysis = analyze_event_window(market_data, decision_dt, windows=windows)
            results.append(
                {
                    "decision_timestamp": row["decision_timestamp"],
                    "direction": row["direction"],
                    "change_bps": row["change_bps"],
                    "previous_rate": row["previous_rate"],
                    "new_rate": row["new_rate"],
                    "source_document": row.get("source_document"),
                    "market_ticker": ticker,
                    "pre_event_avg": analysis.pre_event_avg,
                    "post_event_avg": analysis.post_event_avg,
                    "change_1d": analysis.change_1d,
                    "change_3d": analysis.change_3d,
                    "change_5d": analysis.change_5d,
                    "change_10d": analysis.change_10d,
                    "change_20d": analysis.change_20d,
                    "pre_volatility": analysis.pre_volatility,
                    "post_volatility": analysis.post_volatility,
                    # Phase 23B spec §7 — market sessions each window spans.
                    "decision_session": analysis.decision_session,
                    "pre_session": analysis.pre_session,
                    "window_end_sessions": analysis.window_end_sessions,
                }
            )

        return {
            "central_bank_id": bank_id,
            "ticker": ticker,
            "windows": windows,
            "results": results,
            "count": len(results),
            "status": "LIVE",
            "market_source": market_source,
            "market_status": market_status,
            "history_start": start.isoformat(),
            "history_end": end.isoformat(),
            "note": (
                "Historical observation only. A price move near a decision date is not "
                "evidence that the decision caused it."
            ),
        }

    # -----------------------------------------------------------------------
    # Macro Series operations
    # -----------------------------------------------------------------------

    def fetch_and_store_macro_series(self, series_id: str, limit: int = 1000) -> list[dict]:
        """Fetch macro series from FRED and store in database."""
        fred_source = self._get_fred_source()
        if not fred_source:
            logger.warning("FRED source not available")
            return []

        try:
            series_data = fred_source.fetch_series(series_id, limit=limit)

            with session_scope() as db:
                stored = []
                for series_info in series_data:
                    # Check if observation already exists
                    existing = db.query(MacroSeriesModel).filter(
                        MacroSeriesModel.series_id == series_id,
                        MacroSeriesModel.observation_date == series_info.observation_date
                    ).first()

                    if existing:
                        # Update if this is a revision
                        if not existing.initial_release and series_info.value != existing.value:
                            existing.previous_value = existing.value
                            existing.value = series_info.value
                            existing.revision += 1
                            existing.revision_timestamp = datetime.now(timezone.utc)
                            existing.data_freshness = series_info.data_freshness.value
                            existing.updated_at = datetime.now(timezone.utc)
                            obs_id = existing.id
                        else:
                            obs_id = existing.id
                    else:
                        # Create new observation
                        observation = MacroSeriesModel(
                            series_id=series_id,
                            observation_date=series_info.observation_date,
                            release_date=series_info.release_date,
                            value=series_info.value,
                            unit=series_info.unit,
                            frequency=series_info.frequency,
                            source=series_info.source,
                            source_url=series_info.source_url,
                            initial_release=series_info.initial_release,
                            revision=series_info.revision,
                            revision_timestamp=series_info.revision_timestamp,
                            previous_value=series_info.previous_value,
                            data_freshness=series_info.data_freshness.value,
                        )
                        db.add(observation)
                        db.flush()
                        obs_id = observation.id

                    stored.append({
                        "id": obs_id,
                        "series_id": series_id,
                        "observation_date": series_info.observation_date.isoformat(),
                        "release_date": series_info.release_date.isoformat(),
                        "value": series_info.value,
                        "unit": series_info.unit,
                        "frequency": series_info.frequency,
                        "source": series_info.source,
                        "data_freshness": series_info.data_freshness.value,
                    })

                logger.info("Fetched and stored %d observations for series %s", len(stored), series_id)
                return stored

        except Exception as e:
            logger.error("Failed to fetch macro series %s: %s", series_id, e)
            return []

    def get_macro_series(self, series_id: str, limit: int = 500) -> list[dict]:
        """Get macro series data from database."""
        with session_scope() as db:
            observations = db.query(MacroSeriesModel).filter(
                MacroSeriesModel.series_id == series_id
            ).order_by(MacroSeriesModel.observation_date.desc()).limit(limit).all()

            return [
                {
                    "id": obs.id,
                    "series_id": obs.series_id,
                    "observation_date": obs.observation_date.isoformat(),
                    "release_date": obs.release_date.isoformat(),
                    "value": obs.value,
                    "unit": obs.unit,
                    "frequency": obs.frequency,
                    "source": obs.source,
                    "source_url": obs.source_url,
                    "initial_release": obs.initial_release,
                    "revision": obs.revision,
                    "revision_timestamp": obs.revision_timestamp.isoformat() if obs.revision_timestamp else None,
                    "previous_value": obs.previous_value,
                    "data_freshness": obs.data_freshness,
                }
                for obs in observations
            ]

    def get_available_series(self) -> list[dict]:
        """Get list of available macro series."""
        return [
            {"key": key, "series_id": series_id, "description": key.replace("_", " ").title()}
            for key, series_id in FRED_SERIES.items()
        ]

    def is_known_series(self, series_id: str) -> bool:
        """True when ``series_id`` is one of the engine's curated FRED series."""
        return series_id in FRED_SERIES.values()


    # -----------------------------------------------------------------------
    # Macro indicator dashboard
    # -----------------------------------------------------------------------

    def get_macro_indicators(self, keys: Optional[list[str]] = None) -> list[dict]:
        """Latest stored observation per curated macro indicator.

        Reads only rows already retrieved from a real source; a series with no
        stored observations is omitted rather than zero-filled.
        """
        selected = keys or DEFAULT_INDICATOR_KEYS
        seen_ids: set[str] = set()
        indicators: list[dict] = []
        for key in selected:
            series_id = FRED_SERIES.get(key)
            if not series_id or series_id in seen_ids:
                continue
            seen_ids.add(series_id)
            observations = self.get_macro_series(series_id, limit=2)
            if not observations:
                continue
            latest = observations[0]
            previous = observations[1] if len(observations) > 1 else None
            change = None
            change_pct = None
            if previous and previous.get("value") not in (None, 0):
                change = round(latest["value"] - previous["value"], 6)
                change_pct = round(change / abs(previous["value"]) * 100, 4)
            indicators.append({
                "key": key,
                "series_id": series_id,
                "label": FRED_SERIES_LABELS.get(key, {}).get(
                    "label", key.replace("_", " ").title()
                ),
                "value": latest["value"],
                "unit": latest["unit"],
                "frequency": latest["frequency"],
                "observation_date": latest["observation_date"],
                "release_date": latest["release_date"],
                "source": latest["source"],
                "source_url": latest.get("source_url"),
                "data_freshness": latest["data_freshness"],
                "previous_value": previous["value"] if previous else None,
                "change": change,
                "change_pct": change_pct,
                "revision": latest.get("revision", 0),
                # The keyless CSV endpoint cannot report FRED's true
                # publication/vintage date, so it is flagged rather than
                # presented as exact.
                "release_date_estimated": latest.get("source") == "FRED CSV",
            })
        return indicators

    def refresh_macro_indicators(
        self, keys: Optional[list[str]] = None, limit: int = 120
    ) -> int:
        """Fetch and store the curated indicator set from FRED.

        Each series is an independent source call, so they are fetched
        concurrently and one failing series cannot block the rest.
        """
        from concurrent.futures import ThreadPoolExecutor

        selected = keys or DEFAULT_INDICATOR_KEYS
        series_ids = [FRED_SERIES[k] for k in selected if k in FRED_SERIES]
        if not series_ids:
            return 0

        def _one(series_id: str) -> int:
            return len(self.fetch_and_store_macro_series(series_id, limit=limit))

        stored = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            for count in pool.map(_one, series_ids):
                stored += count
        return stored

    # -----------------------------------------------------------------------
    # Policy rate range (Fed target bounds)
    # -----------------------------------------------------------------------

    def get_policy_rate_range(self, bank_id: str) -> dict:
        """Latest verified policy setting, with both range bounds labelled.

        For the Fed this is the FOMC target range (lower/upper) from the real
        FRED series; for a bank setting a single rate it collapses to one
        value. Returns UNAVAILABLE rather than a guess when the source is
        unreachable and no stored decision exists.
        """
        if bank_id == "FED":
            rng = self._get_fred_source().fetch_policy_rate_range()
            if rng:
                return {
                    "central_bank_id": "FED",
                    "is_range": rng["lower"] is not None and rng["upper"] is not None,
                    "lower": rng["lower"],
                    "upper": rng["upper"],
                    "midpoint": rng["midpoint"],
                    "label": "Federal Funds Target Range",
                    "source": rng["source"],
                    "source_url": rng["source_url"],
                    "status": "LIVE",
                }

        decisions = self.get_policy_history(bank_id, limit=1)
        if decisions:
            rate = decisions[0]["new_rate"]
            return {
                "central_bank_id": bank_id,
                "is_range": False,
                "lower": rate,
                "upper": rate,
                "midpoint": rate,
                "label": "Policy Rate",
                "source": decisions[0].get("source"),
                "source_url": decisions[0].get("source_document"),
                "status": "RECENT",
            }
        return {
            "central_bank_id": bank_id,
            "is_range": False,
            "lower": None,
            "upper": None,
            "midpoint": None,
            "label": "Policy Rate",
            "source": None,
            "source_url": None,
            "status": "UNAVAILABLE",
        }

    # -----------------------------------------------------------------------
    # Sourced market-implied expectations (real prediction-market prices)
    # -----------------------------------------------------------------------

    async def refresh_sourced_expectations(
        self, bank_id: str, meeting_id: Optional[int] = None
    ) -> list[dict]:
        """Fetch real market-implied expectations, store append-only snapshots.

        Snapshots are deduped on (meeting, source, observed_at) so a refresh
        landing on the same market tick does not duplicate, while a new tick
        is preserved as history.
        """
        from .expectations import fetch_policy_expectations

        try:
            sourced = await fetch_policy_expectations(bank_id, timeout=20.0)
        except Exception as exc:
            logger.warning("Sourced expectations fetch failed for %s: %s", bank_id, exc)
            return []
        if not sourced:
            return []

        stored: list[dict] = []
        with session_scope() as db:
            for item in sourced:
                meeting = None
                if meeting_id is not None:
                    meeting = db.query(PolicyMeetingModel).filter(
                        PolicyMeetingModel.id == meeting_id,
                        PolicyMeetingModel.central_bank_id == bank_id,
                    ).first()
                if meeting is None:
                    meeting = self._resolve_meeting_for_day(
                        db, bank_id, item.meeting_scheduled_at
                    )
                if meeting is None:
                    meeting = PolicyMeetingModel(
                        central_bank_id=bank_id,
                        scheduled_at=item.meeting_scheduled_at,
                        timezone="UTC",
                        status="UPCOMING",
                        meeting_type="REGULAR",
                        source_url=item.source_url,
                    )
                    db.add(meeting)
                    db.flush()

                existing = db.query(PolicyExpectationModel).filter(
                    PolicyExpectationModel.meeting_id == meeting.id,
                    PolicyExpectationModel.source == item.source,
                    PolicyExpectationModel.observed_at == item.observed_at,
                ).first()
                if existing:
                    continue

                row = PolicyExpectationModel(
                    meeting_id=meeting.id,
                    source=item.source,
                    observed_at=item.observed_at,
                    expected_outcome=item.expected_outcome,
                    probability_hike=item.probability_hike,
                    probability_cut=item.probability_cut,
                    probability_unchanged=item.probability_unchanged,
                    methodology=item.methodology,
                    source_url=item.source_url,
                )
                db.add(row)
                db.flush()
                stored.append({
                    "id": row.id,
                    "meeting_id": meeting.id,
                    "source": row.source,
                    "observed_at": row.observed_at.isoformat(),
                    "expected_outcome": row.expected_outcome,
                    "probability_hike": row.probability_hike,
                    "probability_cut": row.probability_cut,
                    "probability_unchanged": row.probability_unchanged,
                    "methodology": row.methodology,
                    "source_url": item.source_url,
                    "event_title": item.event_title,
                })
        logger.info(
            "Stored %d sourced expectation snapshot(s) for %s", len(stored), bank_id
        )
        return stored

    @staticmethod
    def _resolve_meeting_for_day(db: Session, bank_id: str, when: datetime):
        """Stored meeting nearest ``when`` for the bank (15-day window)."""
        day = when.replace(hour=0, minute=0, second=0, microsecond=0)
        candidates = (
            db.query(PolicyMeetingModel)
            .filter(
                PolicyMeetingModel.central_bank_id == bank_id,
                PolicyMeetingModel.scheduled_at >= day - timedelta(days=15),
                PolicyMeetingModel.scheduled_at <= day + timedelta(days=15),
            )
            .all()
        )
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda meeting: abs((_as_utc(meeting.scheduled_at) - when).total_seconds()),
        )

    # -----------------------------------------------------------------------
    # One-shot refresh for the UI
    # -----------------------------------------------------------------------

    def refresh_all(self, bank_id: str, series_limit: int = 120) -> dict:
        """Refresh every real feed this page shows for one bank.

        Official meetings, policy decisions and the curated macro indicator
        set (each with per-source failure isolation). Sourced expectations are
        refreshed separately by the async route.
        """
        meetings = self.fetch_and_store_meetings(bank_id, limit=20)
        decisions = self.fetch_and_store_decisions(bank_id, limit=50)
        indicators = self.refresh_macro_indicators(limit=series_limit)
        return {
            "central_bank_id": bank_id,
            "meetings_stored": len(meetings),
            "decisions_stored": len(decisions),
            "indicator_observations_stored": indicators,
        }


# Global service instance
macro_service = MacroIntelligenceService()
