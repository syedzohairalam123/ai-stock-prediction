"""
Phase 23A — Macro Intelligence Service layer.

Coordinates data fetching from sources, database operations, and provides
API-ready responses. Handles caching, error handling, and data validation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

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
)

logger = logging.getLogger("neural_market.macro_intelligence.service")


class MacroIntelligenceService:
    """Service for central bank and macro data operations."""

    def __init__(self):
        self.fred_api_key = settings.macro_fred_api_key or settings.fred_api_key
        self._sources: dict[str, BaseCentralBankSource] = {}
        self._fred_source: Optional[FREDSource] = None

    def _get_source(self, bank_id: str) -> Optional[BaseCentralBankSource]:
        """Get or create source instance for a central bank."""
        if bank_id not in self._sources:
            if bank_id == "FED":
                self._sources[bank_id] = FederalReserveSource(api_key=self.fred_api_key)
            elif bank_id == "BOJ":
                self._sources[bank_id] = BankOfJapanSource()
            else:
                logger.warning("No source configured for bank_id: %s", bank_id)
                return None
        return self._sources[bank_id]

    def _get_fred_source(self) -> Optional[FREDSource]:
        """Get or create FRED source."""
        if self._fred_source is None:
            if self.fred_api_key:
                self._fred_source = FREDSource(api_key=self.fred_api_key)
            else:
                logger.warning("FRED API key not configured")
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
        """Initialize default central banks in database."""
        default_banks = [
            CentralBankInfo(
                id="FED",
                name="Federal Reserve",
                country="United States",
                currency="USD",
                timezone="America/New_York",
                source="federal_reserve",
            ),
            CentralBankInfo(
                id="BOJ",
                name="Bank of Japan",
                country="Japan",
                currency="JPY",
                timezone="Asia/Tokyo",
                source="boj",
            ),
            # Future banks can be added here without redesign
            # CentralBankInfo(id="ECB", name="European Central Bank", country="Eurozone", currency="EUR", timezone="Europe/Brussels", source="ecb"),
            # CentralBankInfo(id="BOE", name="Bank of England", country="United Kingdom", currency="GBP", timezone="Europe/London", source="boe"),
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
                countdown = calculate_countdown(meeting.scheduled_at, now)

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
                    "scheduled_at": meeting.scheduled_at.isoformat(),
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


# Global service instance
macro_service = MacroIntelligenceService()
