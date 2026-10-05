"""
Phase 23A — Data models and calculation logic for macro intelligence.

Contains pure Python dataclasses and calculation functions. No database
or network calls — everything here is testable with synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class MeetingStatus(str, Enum):
    """Policy meeting status."""
    UPCOMING = "UPCOMING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class MeetingType(str, Enum):
    """Policy meeting type."""
    REGULAR = "REGULAR"
    EMERGENCY = "EMERGENCY"
    UNSCHEDULED = "UNSCHEDULED"


class DecisionDirection(str, Enum):
    """Policy decision direction."""
    HIKE = "HIKE"
    CUT = "CUT"
    UNCHANGED = "UNCHANGED"


class DataFreshness(str, Enum):
    """Data freshness status."""
    LIVE = "LIVE"
    RECENT = "RECENT"
    DELAYED = "DELAYED"
    HISTORICAL = "HISTORICAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class CentralBankInfo:
    """Central bank metadata."""
    id: str  # e.g., "FED", "BOJ", "ECB"
    name: str  # e.g., "Federal Reserve", "Bank of Japan"
    country: str  # e.g., "United States", "Japan"
    currency: str  # e.g., "USD", "JPY"
    timezone: str  # e.g., "America/New_York", "Asia/Tokyo"
    source: str  # Data source identifier
    active: bool = True


@dataclass
class PolicyMeetingInfo:
    """Policy meeting information."""
    id: Optional[int] = None
    central_bank_id: str = ""
    scheduled_at: Optional[datetime] = None
    timezone: str = "UTC"
    status: MeetingStatus = MeetingStatus.UNKNOWN
    source_url: Optional[str] = None
    source_timestamp: Optional[datetime] = None
    meeting_type: MeetingType = MeetingType.REGULAR
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class PolicyDecisionInfo:
    """Policy decision information."""
    id: Optional[int] = None
    meeting_id: Optional[int] = None
    previous_rate: float = 0.0
    new_rate: float = 0.0
    change_bps: int = 0
    direction: DecisionDirection = DecisionDirection.UNCHANGED
    decision_timestamp: Optional[datetime] = None
    source: str = ""
    source_document: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class PolicyExpectationInfo:
    """Market-implied policy expectation from legitimate source."""
    id: Optional[int] = None
    meeting_id: Optional[int] = None
    source: str = ""  # e.g., "CME FedWatch", "Bloomberg"
    observed_at: Optional[datetime] = None
    expected_outcome: Optional[str] = None  # HIKE, CUT, UNCHANGED
    expected_rate_min: Optional[float] = None
    expected_rate_max: Optional[float] = None
    probability_hike: Optional[float] = None
    probability_cut: Optional[float] = None
    probability_unchanged: Optional[float] = None
    methodology: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class MacroSeriesInfo:
    """Macroeconomic time-series data point."""
    id: Optional[int] = None
    series_id: str = ""  # e.g., "CPIAUCSL", "UNRATE"
    observation_date: Optional[datetime] = None  # Economic activity date
    release_date: Optional[datetime] = None  # Publication date
    value: float = 0.0
    unit: str = ""  # e.g., "Percent", "Index"
    frequency: str = ""  # DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL
    source: str = ""  # e.g., "FRED", "BLS", "BEA"
    source_url: Optional[str] = None
    initial_release: bool = True
    revision: int = 0
    revision_timestamp: Optional[datetime] = None
    previous_value: Optional[float] = None
    data_freshness: DataFreshness = DataFreshness.HISTORICAL
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class CountdownInfo:
    """Meeting countdown information."""
    days: int = 0
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    total_seconds: int = 0
    is_past: bool = False


@dataclass
class RateHistoryPoint:
    """Historical policy rate data point."""
    date: datetime
    rate: float
    change_bps: int
    direction: DecisionDirection
    source: str


@dataclass
class MacroTrendResult:
    """Macro trend analysis result."""
    series_id: str
    trend: str  # "increasing", "decreasing", "stable", "volatile"
    latest_value: float
    previous_value: float
    change_pct: float
    rolling_avg_3m: Optional[float] = None
    rolling_avg_6m: Optional[float] = None
    rolling_avg_12m: Optional[float] = None


@dataclass
class EventWindowResult:
    """Market reaction around policy decision."""
    decision_date: datetime
    pre_event_avg: Optional[float] = None
    post_event_avg: Optional[float] = None
    change_1d: Optional[float] = None
    change_3d: Optional[float] = None
    change_5d: Optional[float] = None
    change_10d: Optional[float] = None
    change_20d: Optional[float] = None
    market_ticker: Optional[str] = None


# ---------------------------------------------------------------------------
# Calculation functions (pure, testable)
# ---------------------------------------------------------------------------


def calculate_bps_change(previous_rate: float, new_rate: float) -> int:
    """Calculate basis point change between rates.

    Formula: (new_rate - previous_rate) * 100

    Never hardcodes bps values — always calculated from actual rates.
    """
    return int(round((new_rate - previous_rate) * 100))


def determine_direction(change_bps: int) -> DecisionDirection:
    """Determine decision direction from bps change."""
    if change_bps > 0:
        return DecisionDirection.HIKE
    elif change_bps < 0:
        return DecisionDirection.CUT
    return DecisionDirection.UNCHANGED


def calculate_countdown(meeting_time: datetime, now: Optional[datetime] = None) -> CountdownInfo:
    """Calculate countdown to meeting from current time.

    Uses UTC for consistency. Returns CountdownInfo with detailed breakdown.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    delta = meeting_time - now
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return CountdownInfo(
            days=0, hours=0, minutes=0, seconds=0,
            total_seconds=total_seconds, is_past=True
        )

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    return CountdownInfo(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
        total_seconds=total_seconds, is_past=False
    )


def determine_data_freshness(
    release_date: datetime,
    now: Optional[datetime] = None,
    live_threshold_hours: int = 6,
    recent_threshold_hours: int = 72,
    stale_threshold_days: int = 7
) -> DataFreshness:
    """Determine data freshness based on release date.

    Thresholds:
    - LIVE: within live_threshold_hours
    - RECENT: within recent_threshold_hours
    - DELAYED: older than recent but within stale_threshold_days
    - HISTORICAL: older than stale_threshold_days
    - STALE: very old data (should be refreshed)
    - UNAVAILABLE: missing release date
    """
    if release_date is None:
        return DataFreshness.UNAVAILABLE

    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure both datetimes are timezone-aware
    if release_date.tzinfo is None:
        release_date = release_date.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta_hours = (now - release_date).total_seconds() / 3600

    if delta_hours <= live_threshold_hours:
        return DataFreshness.LIVE
    elif delta_hours <= recent_threshold_hours:
        return DataFreshness.RECENT
    elif delta_hours <= (stale_threshold_days * 24):
        return DataFreshness.DELAYED
    elif delta_hours <= (stale_threshold_days * 24 * 2):
        return DataFreshness.HISTORICAL
    else:
        return DataFreshness.STALE


def format_bps(change_bps: int) -> str:
    """Format bps change for display."""
    if change_bps > 0:
        return f"+{change_bps} bps"
    elif change_bps < 0:
        return f"{change_bps} bps"
    return "0 bps"
