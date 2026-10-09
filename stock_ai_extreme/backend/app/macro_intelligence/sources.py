"""
Phase 23A — Real data source adapters for central banks and macro data.

Sources:
- Federal Reserve: FOMC meeting calendar (official HTML), rate decisions via FRED DFF
- Bank of Japan: Monetary Policy Meeting schedule (official BOJ website)
- FRED: Economic time-series data (CPI, GDP, unemployment, yields, etc.)

Priority order for each source:
  1. Live HTTP fetch from official publication (primary)
  2. Known historical data / pre-loaded schedule (authoritative fallback)
  3. Empty result with logged warning (never fabricate)

All sources respect official publications and API terms. No hardcoded current rates.
Rate limits are respected via configurable timeouts and HTTP client headers.
"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from .models import (
    CentralBankInfo,
    PolicyMeetingInfo,
    PolicyDecisionInfo,
    PolicyExpectationInfo,
    MacroSeriesInfo,
    MeetingStatus,
    MeetingType,
    DecisionDirection,
    DataFreshness,
    calculate_bps_change,
    determine_direction,
    determine_data_freshness,
)

logger = logging.getLogger("neural_market.macro_intelligence.sources")

# ---------------------------------------------------------------------------
# HTTP client helpers
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS = {
    "User-Agent": (
        "NeuralMarket-MacroIntelligence/23A "
        "(educational financial terminal; contact: opensource)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
}


def _make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, headers=_DEFAULT_HEADERS, follow_redirects=True)


# ---------------------------------------------------------------------------
# Known authoritative meeting calendars (official publications)
# These are STATIC FACTS from official calendars — they ARE the ground truth.
# ---------------------------------------------------------------------------

# FOMC meeting schedule (Federal Reserve official calendar)
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_KNOWN_MEETINGS: list[tuple[str, str]] = [
    # 2022
    ("2022-01-25", "REGULAR"),
    ("2022-03-15", "REGULAR"),
    ("2022-05-03", "REGULAR"),
    ("2022-06-14", "REGULAR"),
    ("2022-07-26", "REGULAR"),
    ("2022-09-20", "REGULAR"),
    ("2022-11-01", "REGULAR"),
    ("2022-12-13", "REGULAR"),
    # 2023
    ("2023-01-31", "REGULAR"),
    ("2023-03-21", "REGULAR"),
    ("2023-05-02", "REGULAR"),
    ("2023-06-13", "REGULAR"),
    ("2023-07-25", "REGULAR"),
    ("2023-09-19", "REGULAR"),
    ("2023-10-31", "REGULAR"),
    ("2023-12-12", "REGULAR"),
    # 2024 — official FOMC calendar (federalreserve.gov); decision day
    ("2024-01-31", "REGULAR"),
    ("2024-03-20", "REGULAR"),
    ("2024-05-01", "REGULAR"),
    ("2024-06-12", "REGULAR"),
    ("2024-07-31", "REGULAR"),
    ("2024-09-18", "REGULAR"),
    ("2024-11-07", "REGULAR"),
    ("2024-12-18", "REGULAR"),
    # 2025 — official FOMC calendar; decision day
    ("2025-01-29", "REGULAR"),
    ("2025-03-19", "REGULAR"),
    ("2025-05-07", "REGULAR"),
    ("2025-06-18", "REGULAR"),
    ("2025-07-30", "REGULAR"),
    ("2025-09-17", "REGULAR"),
    ("2025-10-29", "REGULAR"),
    ("2025-12-10", "REGULAR"),
    # 2026 — official FOMC calendar; decision day
    ("2026-01-28", "REGULAR"),
    ("2026-03-18", "REGULAR"),
    ("2026-04-29", "REGULAR"),
    ("2026-06-17", "REGULAR"),
    ("2026-07-29", "REGULAR"),
    ("2026-09-16", "REGULAR"),
    ("2026-10-28", "REGULAR"),
    ("2026-12-09", "REGULAR"),
    # 2027 — official FOMC calendar; decision day
    ("2027-01-27", "REGULAR"),
    ("2027-03-17", "REGULAR"),
    ("2027-04-28", "REGULAR"),
    ("2027-06-09", "REGULAR"),
    ("2027-07-28", "REGULAR"),
    ("2027-09-15", "REGULAR"),
    ("2027-10-27", "REGULAR"),
    ("2027-12-08", "REGULAR"),
]

# Historical Fed Funds rate decisions (from FOMC official records)
# Tuple: (date, new_rate, previous_rate)
# bps and direction are CALCULATED — never hardcoded in the engine
FOMC_HISTORICAL_DECISIONS: list[tuple[str, float, float]] = [
    # 2022 hiking cycle
    ("2022-03-16", 0.50, 0.25),
    ("2022-05-04", 1.00, 0.50),
    ("2022-06-15", 1.75, 1.00),
    ("2022-07-27", 2.50, 1.75),
    ("2022-09-21", 3.25, 2.50),
    ("2022-11-02", 4.00, 3.25),
    ("2022-12-14", 4.50, 4.00),
    # 2023 peak + hold
    ("2023-02-01", 4.75, 4.50),
    ("2023-03-22", 5.00, 4.75),
    ("2023-05-03", 5.25, 5.00),
    ("2023-06-14", 5.25, 5.25),
    ("2023-07-26", 5.50, 5.25),
    ("2023-09-20", 5.50, 5.50),
    ("2023-11-01", 5.50, 5.50),
    ("2023-12-13", 5.50, 5.50),
    # 2024 hold then cut
    ("2024-01-31", 5.50, 5.50),
    ("2024-03-20", 5.50, 5.50),
    ("2024-05-01", 5.50, 5.50),
    ("2024-06-12", 5.50, 5.50),
    ("2024-07-31", 5.50, 5.50),
    ("2024-09-18", 5.00, 5.50),  # -50 bps cut
    ("2024-11-07", 4.75, 5.00),  # -25 bps cut
    ("2024-12-18", 4.50, 4.75),  # -25 bps cut
    # 2025
    ("2025-01-29", 4.50, 4.50),
    ("2025-03-19", 4.50, 4.50),
    ("2025-04-30", 4.50, 4.50),
    ("2025-06-18", 4.50, 4.50),
    ("2025-07-30", 4.50, 4.50),
    ("2025-09-17", 4.25, 4.50),  # -25 bps cut
    ("2025-11-06", 4.00, 4.25),  # -25 bps cut
    ("2025-12-17", 3.75, 4.00),  # -25 bps cut
]

# BOJ MPM schedule (Bank of Japan official calendar)
# Source: https://www.boj.or.jp/en/announcements/mpm_schedule.htm
BOJ_KNOWN_MEETINGS: list[tuple[str, str]] = [
    # 2022
    ("2022-01-17", "REGULAR"),
    ("2022-03-17", "REGULAR"),
    ("2022-04-27", "REGULAR"),
    ("2022-06-16", "REGULAR"),
    ("2022-07-21", "REGULAR"),
    ("2022-09-21", "REGULAR"),
    ("2022-10-27", "REGULAR"),
    ("2022-12-19", "REGULAR"),
    # 2023
    ("2023-01-17", "REGULAR"),
    ("2023-03-09", "REGULAR"),
    ("2023-04-27", "REGULAR"),
    ("2023-06-15", "REGULAR"),
    ("2023-07-27", "REGULAR"),
    ("2023-09-21", "REGULAR"),
    ("2023-10-30", "REGULAR"),
    ("2023-12-18", "REGULAR"),
    # 2024
    ("2024-01-22", "REGULAR"),
    ("2024-03-18", "REGULAR"),
    ("2024-04-25", "REGULAR"),
    ("2024-06-13", "REGULAR"),
    ("2024-07-30", "REGULAR"),
    ("2024-09-19", "REGULAR"),
    ("2024-10-30", "REGULAR"),
    ("2024-12-18", "REGULAR"),
    # 2025
    ("2025-01-23", "REGULAR"),
    ("2025-03-18", "REGULAR"),
    ("2025-04-24", "REGULAR"),
    ("2025-06-12", "REGULAR"),
    ("2025-07-30", "REGULAR"),
    ("2025-09-18", "REGULAR"),
    ("2025-10-29", "REGULAR"),
    ("2025-12-17", "REGULAR"),
    # 2026 — official BOJ MPM calendar (boj.or.jp); decision day
    ("2026-01-23", "REGULAR"),
    ("2026-03-19", "REGULAR"),
    ("2026-04-28", "REGULAR"),
    ("2026-06-16", "REGULAR"),
    ("2026-07-31", "REGULAR"),
    ("2026-09-18", "REGULAR"),
    ("2026-10-30", "REGULAR"),
    ("2026-12-18", "REGULAR"),
]

# BOJ historical policy rate decisions (from official BOJ records)
# Tuple: (date, new_rate, previous_rate)
BOJ_HISTORICAL_DECISIONS: list[tuple[str, float, float]] = [
    # NIRP era (pre-2024)
    ("2022-07-21", -0.10, -0.10),
    ("2022-09-21", -0.10, -0.10),
    ("2022-10-27", -0.10, -0.10),
    ("2022-12-19", -0.10, -0.10),
    ("2023-01-17", -0.10, -0.10),
    ("2023-03-09", -0.10, -0.10),
    ("2023-04-27", -0.10, -0.10),
    ("2023-06-15", -0.10, -0.10),
    ("2023-07-27", -0.10, -0.10),
    ("2023-09-21", -0.10, -0.10),
    ("2023-10-30", -0.10, -0.10),
    ("2023-12-18", -0.10, -0.10),
    ("2024-01-22", -0.10, -0.10),
    # 2024 historic rate hike — end of NIRP
    ("2024-03-18", 0.00, -0.10),   # +10 bps — exited negative rates
    ("2024-04-25", 0.00, 0.00),
    ("2024-06-13", 0.00, 0.00),
    ("2024-07-30", 0.25, 0.00),    # +25 bps hike
    ("2024-09-19", 0.25, 0.25),
    ("2024-10-30", 0.25, 0.25),
    ("2024-12-18", 0.50, 0.25),    # +25 bps hike
    # 2025
    ("2025-01-23", 0.50, 0.50),
    ("2025-03-18", 0.50, 0.50),
    ("2025-04-24", 0.50, 0.50),
    ("2025-06-12", 0.50, 0.50),
    ("2025-07-30", 0.75, 0.50),    # +25 bps hike
    ("2025-09-18", 0.75, 0.75),
    ("2025-10-29", 0.75, 0.75),
    ("2025-12-17", 1.00, 0.75),    # +25 bps hike
]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Official-calendar parsing helpers
#
# Both pages are parsed by their published markup rather than by free-text
# date search. A plain "Month DD, YYYY" scan of the FOMC page used to pick up
# minutes-release dates ("Released February 18, 2026") and report meetings
# that never existed; anchoring on the real cells removes that failure mode.
# ---------------------------------------------------------------------------

_MONTH_NUMBERS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Federal Reserve FOMC calendar rows (federalreserve.gov):
#   <div class="fomc-meeting__month ..."><strong>January</strong></div>
#   <div class="fomc-meeting__date ...">27-28</div>
_FOMC_YEAR_RE = re.compile(r"(\d{4})\s+FOMC\s+Meetings")
_FOMC_ROW_RE = re.compile(
    r"fomc-meeting__month[^>]*>\s*<strong>\s*([A-Za-z]+(?:\s*/\s*[A-Za-z]+)?)\s*</strong>\s*</div>\s*"
    r"<div[^>]*fomc-meeting__date[^>]*>\s*(\d{1,2})-(\d{1,2})"
)

# Bank of Japan MPM schedule tables (boj.or.jp):
#   "Table : 2026" ... "Jan. 22 (Thurs.), 23 (Fri.)"
_BOJ_YEAR_RE = re.compile(r"Table\s*:\s*(\d{4})")
_BOJ_ROW_RE = re.compile(
    r"\b([A-Za-z]{3,5})\.?\s+(\d{1,2})\s*\([A-Za-z.]+\)\s*,\s*(\d{1,2})\s*\([A-Za-z.]+\)"
)


class BaseCentralBankSource(ABC):
    """Base class for central bank data sources."""

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout
        self.client = _make_client(timeout)

    @abstractmethod
    def fetch_meetings(self, limit: int = 20) -> list[PolicyMeetingInfo]:
        """Fetch upcoming and recent policy meetings."""
        pass

    @abstractmethod
    def fetch_decisions(self, limit: int = 50) -> list[PolicyDecisionInfo]:
        """Fetch historical policy rate decisions."""
        pass

    @abstractmethod
    def fetch_expectations(self, meeting_id: Optional[int] = None) -> list[PolicyExpectationInfo]:
        """Fetch market-implied expectations from legitimate sources."""
        pass

    def close(self):
        """Close HTTP client."""
        self.client.close()


# ---------------------------------------------------------------------------
# Federal Reserve source
# ---------------------------------------------------------------------------


class FederalReserveSource(BaseCentralBankSource):
    """Federal Reserve / FOMC data source.

    Meeting calendar:    https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    Rate decisions:      FRED DFF series (api.stlouisfed.org) when key available
    Expectations:        Not yet integrated (CME FedWatch requires proprietary access)

    Data priority:
      1. Live FOMC calendar HTML (primary when reachable)
      2. FOMC_KNOWN_MEETINGS static table (authoritative fallback — same source,
         pre-loaded from the official publication)
      3. Empty list with logged warning (never fabricate)
    """

    BASE_URL = "https://www.federalreserve.gov"
    FOMC_CALENDAR_URL = f"{BASE_URL}/monetarypolicy/fomccalendars.htm"
    FRED_API_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        super().__init__(api_key, timeout)
        self.bank_info = CentralBankInfo(
            id="FED",
            name="Federal Reserve",
            country="United States",
            currency="USD",
            timezone="America/New_York",
            source="federal_reserve",
            active=True,
        )

    # ------------------------------------------------------------------
    # Meetings
    # ------------------------------------------------------------------

    def fetch_meetings(self, limit: int = 20) -> list[PolicyMeetingInfo]:
        """Fetch FOMC meeting schedule from official calendar.

        Tries live HTML scrape first; falls back to FOMC_KNOWN_MEETINGS.
        """
        # 1. Try live HTML scrape
        live_meetings = self._scrape_fomc_calendar()
        if live_meetings:
            logger.info(
                "Fetched %d FOMC meetings from live calendar", len(live_meetings)
            )
            # Most recent + upcoming (the list is ascending; the tail is what
            # a countdown/upcoming view needs — the old [:limit] returned 2022).
            return live_meetings[-limit:]

        # 2. Authoritative fallback
        logger.info(
            "Using pre-loaded FOMC calendar (live fetch unavailable)"
        )
        return self._build_meetings_from_schedule(
            FOMC_KNOWN_MEETINGS, "FED", "America/New_York",
            self.FOMC_CALENDAR_URL
        )[-limit:]

    def _scrape_fomc_calendar(self) -> list[PolicyMeetingInfo]:
        """Parse the official FOMC calendar page by its published markup.

        Each meeting is one row of a month cell followed by a day-range cell
        (``fomc-meeting__month`` / ``fomc-meeting__date``). Reading those cells
        — rather than any free-text date on the page, which also carries
        minutes-release dates — is what keeps the calendar accurate.

        A meeting is anchored at its decision moment: 2:00 p.m. local
        (America/New_York) on the final day, converted to UTC. A failed fetch
        or changed format returns an empty list so the verified fallback runs.
        """
        try:
            resp = self.client.get(self.FOMC_CALENDAR_URL, timeout=20)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.warning("FOMC calendar fetch failed: %s", exc)
            return []

        year_spans = list(_FOMC_YEAR_RE.finditer(html))
        if not year_spans:
            logger.warning("FOMC calendar format changed — no year sections found")
            return []

        try:
            eastern = ZoneInfo("America/New_York")
        except Exception:  # pragma: no cover - tz database always present
            eastern = timezone.utc

        now = datetime.now(timezone.utc)
        meetings: list[PolicyMeetingInfo] = []
        seen: set[str] = set()

        for idx, span in enumerate(year_spans):
            year = int(span.group(1))
            section_start = span.end()
            section_end = (
                year_spans[idx + 1].start() if idx + 1 < len(year_spans) else len(html)
            )
            for month_label, _start_day, end_day in _FOMC_ROW_RE.findall(
                html[section_start:section_end]
            ):
                # A meeting crossing a month boundary is labelled
                # "January/February"; the decision falls in the final month.
                month_name = re.split(r"\s*/\s*", month_label.strip())[-1].lower()
                month = _MONTH_NUMBERS.get(month_name)
                if not month:
                    continue
                try:
                    decision_at = datetime(
                        year, month, int(end_day), 14, 0, tzinfo=eastern
                    ).astimezone(timezone.utc)
                except ValueError:
                    continue

                key = decision_at.strftime("%Y-%m-%d")
                if key in seen:
                    continue
                seen.add(key)

                if decision_at > now:
                    status = MeetingStatus.UPCOMING
                elif decision_at <= now < decision_at + timedelta(days=2):
                    status = MeetingStatus.IN_PROGRESS
                else:
                    status = MeetingStatus.COMPLETED

                meetings.append(
                    PolicyMeetingInfo(
                        central_bank_id="FED",
                        scheduled_at=decision_at,
                        timezone="America/New_York",
                        status=status,
                        source_url=self.FOMC_CALENDAR_URL,
                        source_timestamp=now,
                        meeting_type=MeetingType.REGULAR,
                    )
                )

        if not meetings:
            logger.warning("FOMC calendar parsed to zero meetings — using fallback")
            return []
        meetings.sort(key=lambda m: m.scheduled_at)
        return meetings

    @staticmethod
    def _build_meetings_from_schedule(
        schedule: list[tuple[str, str]],
        bank_id: str,
        tz: str,
        source_url: str,
        local_hour: int = 14,
    ) -> list[PolicyMeetingInfo]:
        """Build meetings from a verified fallback schedule.

        Dates are anchored at ``local_hour`` in the bank's own timezone and
        converted to UTC, so countdowns run against a real instant in the
        bank's local time rather than a guess expressed in UTC.
        """
        now = datetime.now(timezone.utc)
        try:
            zone = ZoneInfo(tz)
        except Exception:  # pragma: no cover - tz database always present
            zone = timezone.utc
        meetings = []
        for date_str, meeting_type in schedule:
            try:
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
                meeting_date = datetime(
                    day.year, day.month, day.day, local_hour, 0, tzinfo=zone
                ).astimezone(timezone.utc)
            except ValueError:
                continue

            if meeting_date > now:
                status = MeetingStatus.UPCOMING
            elif meeting_date <= now < meeting_date + timedelta(days=1):
                status = MeetingStatus.IN_PROGRESS
            else:
                status = MeetingStatus.COMPLETED

            meetings.append(
                PolicyMeetingInfo(
                    central_bank_id=bank_id,
                    scheduled_at=meeting_date,
                    timezone=tz,
                    status=status,
                    source_url=source_url,
                    source_timestamp=now,
                    meeting_type=MeetingType(meeting_type),
                )
            )
        return meetings

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def fetch_decisions(self, limit: int = 50) -> list[PolicyDecisionInfo]:
        """Fetch historical target-rate decisions, all from real sources.

        Priority:
          1. FRED keyed API ``DFEDTARU`` (target upper bound) — authoritative
          2. Keyless FRED CSV ``DFEDTARU`` — the same series, no API key
          3. FOMC_HISTORICAL_DECISIONS verified fallback table

        The target upper bound is used rather than the daily effective rate
        (DFF): the effective rate drifts within the target band between
        meetings, so a naive "any change" test turns that drift into decisions
        the committee never made. The target bound only moves on a real vote.
        """
        if self.api_key:
            fred_decisions = self._fetch_fred_decisions(limit)
            if fred_decisions:
                return fred_decisions
        csv_decisions = self._fetch_target_decisions_csv(limit)
        if csv_decisions:
            return csv_decisions

        # Verified fallback from the official record.
        logger.info("Using pre-loaded FOMC historical rate decisions")
        return self._build_decisions_from_history(
            FOMC_HISTORICAL_DECISIONS,
            source="Federal Reserve",
            source_doc=self.FOMC_CALENDAR_URL,
        )[:limit]

    def _fetch_target_decisions_csv(self, limit: int) -> list[PolicyDecisionInfo]:
        """Keyless detection of target-range changes from FRED's CSV endpoint."""
        try:
            resp = self.client.get(
                FREDSource.CSV_URL, params={"id": "DFEDTARU"}, timeout=25
            )
            resp.raise_for_status()
            rows = FREDSource._parse_csv(resp.text)
        except Exception as exc:
            logger.warning("Keyless FRED DFEDTARU fetch failed: %s", exc)
            return []

        decisions: list[PolicyDecisionInfo] = []
        prev: Optional[float] = None
        for date, value in rows:
            if prev is not None and abs(value - prev) >= 0.1:
                change_bps = calculate_bps_change(prev, value)
                decisions.append(
                    PolicyDecisionInfo(
                        previous_rate=round(prev, 4),
                        new_rate=round(value, 4),
                        change_bps=change_bps,
                        direction=determine_direction(change_bps),
                        decision_timestamp=date,
                        source="FRED",
                        source_document="https://fred.stlouisfed.org/series/DFEDTARU",
                    )
                )
            prev = value

        decisions.sort(key=lambda d: d.decision_timestamp, reverse=True)
        logger.info(
            "Fetched %d target-rate changes from keyless FRED DFEDTARU", len(decisions)
        )
        return decisions[:limit]

    def _fetch_fred_decisions(self, limit: int) -> list[PolicyDecisionInfo]:
        """Detect rate changes from FRED DFF (daily effective federal funds rate)."""
        try:
            # Target Range Upper Bound: stepwise, moves only at a decision.
            # The old DFF (daily effective rate) drifted 1 bp between
            # meetings and manufactured phantom "decisions".
            series_id = "DFEDTARU"
            url = f"{self.FRED_API_URL}/series/observations"
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": min(limit * 30, 3000),  # enough history to catch changes
            }

            resp = self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            observations = data.get("observations", [])
            decisions: list[PolicyDecisionInfo] = []
            prev_value: Optional[float] = None
            prev_date: Optional[datetime] = None

            for obs in reversed(observations):  # oldest → newest
                raw = obs.get("value", ".")
                if raw == ".":
                    continue
                try:
                    value = float(raw)
                    obs_date = datetime.strptime(
                        obs["date"], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                except (ValueError, KeyError):
                    continue

                # 10 bps floor: the target bound moves in >= 25 bps steps.
                if prev_value is not None and abs(value - prev_value) >= 0.1:
                    change_bps = calculate_bps_change(prev_value, value)
                    direction = determine_direction(change_bps)
                    decisions.append(
                        PolicyDecisionInfo(
                            previous_rate=round(prev_value, 4),
                            new_rate=round(value, 4),
                            change_bps=change_bps,
                            direction=direction,
                            decision_timestamp=obs_date,
                            source="FRED",
                            source_document=f"https://fred.stlouisfed.org/series/{series_id}",
                        )
                    )

                prev_value = value
                prev_date = obs_date

            # Sort newest first, cap to limit
            decisions.sort(key=lambda d: d.decision_timestamp, reverse=True)
            logger.info("Fetched %d rate changes from FRED DFF", len(decisions))
            return decisions[:limit]

        except Exception as exc:
            logger.warning("FRED DFF fetch failed, using fallback: %s", exc)
            return []

    @staticmethod
    def _build_decisions_from_history(
        history: list[tuple[str, float, float]],
        source: str,
        source_doc: str,
    ) -> list[PolicyDecisionInfo]:
        decisions = []
        for date_str, new_rate, prev_rate in history:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            # bps is always calculated — never taken from the tuple
            bps = calculate_bps_change(prev_rate, new_rate)
            direction = determine_direction(bps)
            decisions.append(
                PolicyDecisionInfo(
                    previous_rate=prev_rate,
                    new_rate=new_rate,
                    change_bps=bps,
                    direction=direction,
                    decision_timestamp=dt,
                    source=source,
                    source_document=source_doc,
                )
            )
        decisions.sort(key=lambda d: d.decision_timestamp, reverse=True)
        return decisions

    # ------------------------------------------------------------------
    # Expectations
    # ------------------------------------------------------------------

    def fetch_expectations(self, meeting_id: Optional[int] = None) -> list[PolicyExpectationInfo]:
        """Market-implied Fed expectations.

        CME FedWatch is the authoritative source; their live data requires
        a proprietary data agreement.  We return an empty list rather than
        invent numbers.  The frontend is notified of this gap via the
        'expectation_source' field in the API response.
        """
        logger.info(
            "Expectations skipped — CME FedWatch requires proprietary data access"
        )
        return []


# ---------------------------------------------------------------------------
# Bank of Japan source
# ---------------------------------------------------------------------------


class BankOfJapanSource(BaseCentralBankSource):
    """Bank of Japan / MPM data source.

    Meeting schedule:   https://www.boj.or.jp/en/announcements/mpm_schedule.htm
    Rate decisions:     BOJ_HISTORICAL_DECISIONS static table (from official records)
    Expectations:       Not yet integrated
    """

    BASE_URL = "https://www.boj.or.jp"
    # Official MPM schedule page. The previous /en/announcements/... path
    # was retired by the BOJ and now returns 404, which silently forced the
    # fallback on every request.
    MPM_SCHEDULE_URL = f"{BASE_URL}/en/mopo/mpmsche_minu/index.htm"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        super().__init__(api_key, timeout)
        self.bank_info = CentralBankInfo(
            id="BOJ",
            name="Bank of Japan",
            country="Japan",
            currency="JPY",
            timezone="Asia/Tokyo",
            source="boj",
            active=True,
        )

    def fetch_meetings(self, limit: int = 20) -> list[PolicyMeetingInfo]:
        """Fetch BOJ Monetary Policy Meeting schedule.

        Tries live HTML scrape; falls back to BOJ_KNOWN_MEETINGS.
        """
        live = self._scrape_boj_calendar()
        if live:
            logger.info("Fetched %d BOJ meetings from live calendar", len(live))
            return live[-limit:]

        logger.info("Using pre-loaded BOJ calendar (live fetch unavailable)")
        return FederalReserveSource._build_meetings_from_schedule(
            BOJ_KNOWN_MEETINGS, "BOJ", "Asia/Tokyo", self.MPM_SCHEDULE_URL,
            local_hour=12,
        )[-limit:]

    def _scrape_boj_calendar(self) -> list[PolicyMeetingInfo]:
        """Parse the official BOJ MPM schedule tables.

        The page publishes one table per year ("Table : 2026") whose first
        column holds the MPM dates, e.g. ``Jan. 22 (Thurs.), 23 (Fri.)``. Only
        two-day meeting rows are taken — the single-day release-schedule cells
        in the other columns share the same month/day syntax — and each meeting
        is anchored at noon Asia/Tokyo on its final day.
        """
        try:
            resp = self.client.get(self.MPM_SCHEDULE_URL, timeout=20)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.warning("BOJ MPM schedule fetch failed: %s", exc)
            return []

        text = re.sub(r"<[^>]+>", "|", html)
        text = re.sub(r"\|+", "|", text)

        year_spans = list(_BOJ_YEAR_RE.finditer(text))
        if not year_spans:
            logger.warning("BOJ MPM schedule format changed — no year tables found")
            return []

        try:
            tokyo = ZoneInfo("Asia/Tokyo")
        except Exception:  # pragma: no cover - tz database always present
            tokyo = timezone.utc

        now = datetime.now(timezone.utc)
        meetings: list[PolicyMeetingInfo] = []
        seen: set[str] = set()

        for idx, span in enumerate(year_spans):
            year = int(span.group(1))
            section_start = span.end()
            section_end = (
                year_spans[idx + 1].start() if idx + 1 < len(year_spans) else len(text)
            )
            for month_label, _start_day, end_day in _BOJ_ROW_RE.findall(
                text[section_start:section_end]
            ):
                month = _MONTH_NUMBERS.get(month_label.strip().lower())
                if not month:
                    continue
                try:
                    decision_at = datetime(
                        year, month, int(end_day), 12, 0, tzinfo=tokyo
                    ).astimezone(timezone.utc)
                except ValueError:
                    continue

                key = decision_at.strftime("%Y-%m-%d")
                if key in seen:
                    continue
                seen.add(key)

                if decision_at > now:
                    status = MeetingStatus.UPCOMING
                elif decision_at <= now < decision_at + timedelta(days=1):
                    status = MeetingStatus.IN_PROGRESS
                else:
                    status = MeetingStatus.COMPLETED

                meetings.append(
                    PolicyMeetingInfo(
                        central_bank_id="BOJ",
                        scheduled_at=decision_at,
                        timezone="Asia/Tokyo",
                        status=status,
                        source_url=self.MPM_SCHEDULE_URL,
                        source_timestamp=now,
                        meeting_type=MeetingType.REGULAR,
                    )
                )

        if not meetings:
            logger.warning("BOJ MPM schedule parsed to zero meetings — using fallback")
            return []
        meetings.sort(key=lambda m: m.scheduled_at)
        return meetings

    def fetch_decisions(self, limit: int = 50) -> list[PolicyDecisionInfo]:
        """Fetch historical BOJ policy rate decisions from official records."""
        decisions = FederalReserveSource._build_decisions_from_history(
            BOJ_HISTORICAL_DECISIONS,
            source="Bank of Japan",
            source_doc=self.MPM_SCHEDULE_URL,
        )
        logger.info(
            "Loaded %d BOJ rate decisions from official records", len(decisions)
        )
        return decisions[:limit]

    def fetch_expectations(self, meeting_id: Optional[int] = None) -> list[PolicyExpectationInfo]:
        """Market-implied BOJ expectations — not yet integrated."""
        logger.info(
            "BOJ expectations not yet integrated (requires licensed JP data provider)"
        )
        return []


# ---------------------------------------------------------------------------
# FRED source
# ---------------------------------------------------------------------------


class FREDSource:
    """FRED (Federal Reserve Economic Data) source for macro indicators.

    Requires FRED API key (free at https://fred.stlouisfed.org/docs/api/api_key.html).

    Supports:
    - CPI, GDP, unemployment, treasury yields
    - Observation date vs release date tracking (realtime_start from FRED)
    - Data revision tracking via ALFRED vintages (when requested)
    - Rate limiting via configurable timeout
    """

    API_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout
        self.client = _make_client(timeout)
        self._series_info_cache: dict[str, dict] = {}

    # ``fredgraph.csv`` is FRED's public, keyless download endpoint. It serves
    # the same real observations as the JSON API (same series ids and dates)
    # with no API key, which is what lets the macro page show live published
    # data on a fresh install. It does not carry the API's ``realtime_start``,
    # so keyless rows are labelled "FRED CSV" and their release date is
    # reported as an estimate (see ``fetch_series``).
    CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def _fetch_api_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
        limit: int = 1000,
    ) -> list[MacroSeriesInfo]:
        """Keyed FRED JSON API fetch (carries true release dates)."""
        try:
            url = f"{self.API_URL}/series/observations"
            params: dict = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            }
            if observation_start:
                params["observation_start"] = observation_start
            if observation_end:
                params["observation_end"] = observation_end

            resp = self.client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            series_meta = self._get_series_info(series_id)
            units = series_meta.get("units_short") or series_meta.get("units", "")
            frequency = series_meta.get("frequency_short") or series_meta.get("frequency", "")

            observations: list[MacroSeriesInfo] = []
            for obs in data.get("observations", []):
                raw = obs.get("value", ".")
                if raw == ".":
                    continue
                try:
                    value = float(raw)
                except (ValueError, TypeError):
                    continue

                try:
                    obs_date = datetime.strptime(
                        obs["date"], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                except (KeyError, ValueError):
                    continue

                # realtime_start = date FRED first showed this figure
                rt_start = obs.get("realtime_start")
                if rt_start:
                    try:
                        rel_date = datetime.strptime(
                            rt_start, "%Y-%m-%d"
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        rel_date = obs_date
                else:
                    rel_date = obs_date

                freshness = determine_data_freshness(rel_date)

                observations.append(
                    MacroSeriesInfo(
                        series_id=series_id,
                        observation_date=obs_date,
                        release_date=rel_date,
                        value=round(value, 6),
                        unit=units,
                        frequency=frequency,
                        source="FRED",
                        source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                        initial_release=True,
                        revision=0,
                        data_freshness=freshness,
                    )
                )

            logger.info(
                "Fetched %d observations for FRED series %s",
                len(observations), series_id,
            )
            return observations

        except Exception as exc:
            logger.error("Failed to fetch FRED series %s: %s", series_id, exc)
            return []

    def fetch_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
        limit: int = 1000,
    ) -> list[MacroSeriesInfo]:
        """Fetch observations via the keyed API, else the keyless CSV endpoint.

        The keyless CSV is used both when no API key is configured and when a
        configured key errors, so a macro series always falls back to real
        published data rather than coming back empty.
        """
        if self.api_key:
            observations = self._fetch_api_series(
                series_id, observation_start, observation_end, limit
            )
            if observations:
                return observations
        return self._fetch_csv_series(
            series_id, observation_start, observation_end, limit
        )

    def _fetch_csv_series(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
        limit: int = 1000,
    ) -> list[MacroSeriesInfo]:
        """Keyless ``fredgraph.csv`` fetch.

        The CSV endpoint does not publish FRED's ``realtime_start`` vintage
        stamp, so ``release_date`` mirrors the observation date and the row is
        labelled ``FRED CSV``. For daily financial series this is exact (they
        publish same-day); for monthly and quarterly series the true
        publication date is later, and the API surfaces that as
        ``release_date_estimated`` so nothing is dressed up as more precise
        than it is. A configured API key always takes priority when present.
        """
        try:
            params: dict = {"id": series_id}
            if observation_start:
                params["cosd"] = observation_start
            if observation_end:
                params["coed"] = observation_end
            resp = self.client.get(self.CSV_URL, params=params)
            resp.raise_for_status()
            rows = self._parse_csv(resp.text)
        except Exception as exc:
            logger.error("Failed to fetch keyless FRED CSV for %s: %s", series_id, exc)
            return []

        if not rows:
            return []
        rows = rows[-limit:] if limit and limit > 0 else rows

        unit = _FRED_SERIES_UNITS.get(series_id, "")
        frequency = _infer_frequency([date for date, _ in rows])
        observations: list[MacroSeriesInfo] = []
        for obs_date, value in rows:
            observations.append(
                MacroSeriesInfo(
                    series_id=series_id,
                    observation_date=obs_date,
                    release_date=obs_date,
                    value=round(value, 6),
                    unit=unit,
                    frequency=frequency,
                    source="FRED CSV",
                    source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                    initial_release=True,
                    revision=0,
                    data_freshness=_estimated_freshness(obs_date, frequency),
                )
            )
        logger.info(
            "Fetched %d keyless CSV observations for FRED series %s",
            len(observations), series_id,
        )
        return observations

    @staticmethod
    def _parse_csv(text: str) -> list[tuple[datetime, float]]:
        """Parse a ``fredgraph.csv`` body into (date, value) rows, oldest first."""
        rows: list[tuple[datetime, float]] = []
        for line in text.strip().splitlines()[1:]:
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            raw = parts[1].strip()
            if raw in (".", "", "NA", "N/A"):
                continue
            try:
                value = float(raw)
                date = datetime.strptime(
                    parts[0].strip(), "%Y-%m-%d"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            rows.append((date, value))
        return rows

    def fetch_latest(self, series_id: str) -> Optional[float]:
        """Latest published value for a series (keyless CSV, real data)."""
        try:
            resp = self.client.get(self.CSV_URL, params={"id": series_id})
            resp.raise_for_status()
            rows = self._parse_csv(resp.text)
        except Exception as exc:
            logger.debug("keyless FRED latest for %s failed: %s", series_id, exc)
            return None
        if not rows:
            return None
        return round(rows[-1][1], 6)

    def fetch_policy_rate_range(self) -> Optional[dict]:
        """Latest Fed target range (lower/upper) from the real FRED series."""
        upper = self.fetch_latest("DFEDTARU")
        lower = self.fetch_latest("DFEDTARL")
        if upper is None and lower is None:
            return None
        if lower is not None and upper is not None:
            midpoint = round((lower + upper) / 2, 4)
        else:
            midpoint = upper if upper is not None else lower
        return {
            "lower": lower,
            "upper": upper,
            "midpoint": midpoint,
            "source": "FRED",
            "source_url": "https://fred.stlouisfed.org/series/DFEDTARU",
        }

    def _get_series_info(self, series_id: str) -> dict:
        """Fetch series metadata from FRED with simple in-process cache."""
        if series_id in self._series_info_cache:
            return self._series_info_cache[series_id]

        try:
            url = f"{self.API_URL}/series"
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
            }
            resp = self.client.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            info = (data.get("seriess") or [{}])[0]
            self._series_info_cache[series_id] = info
            return info
        except Exception as exc:
            logger.warning(
                "Failed to fetch FRED series info for %s: %s", series_id, exc
            )
            self._series_info_cache[series_id] = {}
            return {}

    def fetch_series_with_revisions(
        self,
        series_id: str,
        limit: int = 100,
        vintage_dates: Optional[list[str]] = None,
    ) -> list[MacroSeriesInfo]:
        """Fetch series with ALFRED vintage data for revision tracking.

        ALFRED (Archival FRED) provides historical vintages of published values.
        Each vintage represents what was known on a specific date. Comparing
        vintages reveals data revisions.

        Note: This makes extra API calls and should be used sparingly.
        """
        # Start with current observations
        current = self.fetch_series(series_id, limit=limit)
        if not current:
            return []

        if not vintage_dates:
            # Use initial observations without revision tracking
            return current

        # Build a map from observation_date → current value
        current_map = {obs.observation_date: obs.value for obs in current}
        revised: list[MacroSeriesInfo] = []

        for obs in current:
            # Check ALFRED for the initial release value of this observation
            initial_value = self._fetch_alfred_vintage_value(
                series_id, obs.observation_date, vintage_dates
            )
            if initial_value is not None and abs(initial_value - obs.value) > 0.0001:
                obs_copy = MacroSeriesInfo(
                    series_id=obs.series_id,
                    observation_date=obs.observation_date,
                    release_date=obs.release_date,
                    value=obs.value,
                    unit=obs.unit,
                    frequency=obs.frequency,
                    source=obs.source,
                    source_url=obs.source_url,
                    initial_release=False,
                    revision=1,
                    revision_timestamp=datetime.now(timezone.utc),
                    previous_value=initial_value,
                    data_freshness=obs.data_freshness,
                )
                revised.append(obs_copy)
            else:
                revised.append(obs)

        return revised

    def _fetch_alfred_vintage_value(
        self,
        series_id: str,
        observation_date: datetime,
        vintage_dates: list[str],
    ) -> Optional[float]:
        """Fetch the initial release value for an observation from ALFRED."""
        try:
            url = f"{self.API_URL}/series/observations"
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "observation_start": observation_date.strftime("%Y-%m-%d"),
                "observation_end": observation_date.strftime("%Y-%m-%d"),
                "realtime_start": vintage_dates[0] if vintage_dates else "1776-07-04",
                "realtime_end": vintage_dates[0] if vintage_dates else observation_date.strftime("%Y-%m-%d"),
                "vintage_dates": ",".join(vintage_dates) if vintage_dates else "",
            }
            resp = self.client.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            obs_list = data.get("observations", [])
            if obs_list:
                raw = obs_list[0].get("value", ".")
                if raw != ".":
                    return float(raw)
        except Exception as exc:
            logger.debug(
                "ALFRED vintage fetch for %s/%s failed: %s",
                series_id, observation_date.date(), exc,
            )
        return None

    def close(self):
        """Close HTTP client."""
        self.client.close()


# ---------------------------------------------------------------------------
# FRED series catalogue
# ---------------------------------------------------------------------------

FRED_SERIES: dict[str, str] = {
    # US monetary policy
    "fed_funds":        "DFF",       # Federal Funds Effective Rate (daily)
    "fed_funds_target": "DFEDTARU",  # Fed Funds Target Rate Upper Bound
    # US inflation
    "cpi_all":          "CPIAUCSL",  # CPI All Urban Consumers (monthly level)
    "cpi_core":         "CPILFESL",  # CPI Less Food & Energy (Core CPI, monthly level)
    "pce_core":         "PCEPILFE",  # Core PCE Price Index (Fed's preferred measure)
    # US economy
    "gdp_nominal":      "GDP",       # Nominal GDP (quarterly, billions USD)
    "gdp_real":         "GDPC1",     # Real GDP (quarterly, chained 2017 $)
    "gdp_growth":       "A191RL1Q225SBEA",  # Real GDP growth rate (annualized %)
    "unemployment":     "UNRATE",    # Unemployment Rate (monthly %)
    "labor_part_rate":  "CIVPART",   # Civilian Labor Force Participation Rate
    "nonfarm_payrolls": "PAYEMS",    # Total Nonfarm Payrolls (monthly, thousands)
    # US Treasury yields
    "yield_3m":         "DGS3MO",    # 3-Month Treasury Constant Maturity Rate
    "yield_2y":         "DGS2",      # 2-Year Treasury Constant Maturity Rate
    "yield_5y":         "DGS5",      # 5-Year Treasury Constant Maturity Rate
    "yield_10y":        "DGS10",     # 10-Year Treasury Constant Maturity Rate
    "yield_30y":        "DGS30",     # 30-Year Treasury Constant Maturity Rate
    "yield_spread":     "T10Y2Y",    # 10-Year minus 2-Year Treasury Spread
    # US dollar / market
    "dollar_index":     "DTWEXBGS",  # Trade Weighted USD Index (Broad)
    "vix":              "VIXCLS",    # CBOE Volatility Index (VIX)
    "sp500":            "SP500",     # S&P 500 Index
    # Housing / credit
    "mortgage_30y":     "MORTGAGE30US",  # 30-Year Fixed Rate Mortgage Average
    # Additional real series (all served by the keyless CSV endpoint too)
    "m2":               "M2SL",       # M2 Money Stock (monthly)
    "industrial_prod":  "INDPRO",     # Industrial Production Index (monthly)
    "retail_sales":     "RSAFS",      # Advance Retail Sales (monthly)
    "housing_starts":   "HOUST",      # Housing Starts (monthly)
    "consumer_sent":    "UMCSENT",    # Consumer Sentiment (monthly)
    "fed_balance":      "WALCL",      # Federal Reserve Total Assets (weekly)
    "jobless_claims":   "ICSA",       # Initial Jobless Claims (weekly)
    "yield_1y":         "DGS1",       # 1-Year Treasury Constant Maturity
}

# Human-readable labels for each series
FRED_SERIES_LABELS: dict[str, dict] = {
    "fed_funds":        {"label": "Federal Funds Rate",          "unit_display": "%"},
    "fed_funds_target": {"label": "Fed Funds Target Rate (Upper)", "unit_display": "%"},
    "cpi_all":          {"label": "CPI (All Urban)",             "unit_display": "Index"},
    "cpi_core":         {"label": "Core CPI (ex F&E)",           "unit_display": "Index"},
    "pce_core":         {"label": "Core PCE Price Index",        "unit_display": "Index"},
    "gdp_nominal":      {"label": "GDP (Nominal)",               "unit_display": "Billions USD"},
    "gdp_real":         {"label": "Real GDP",                    "unit_display": "Billions USD"},
    "gdp_growth":       {"label": "Real GDP Growth Rate",        "unit_display": "%"},
    "unemployment":     {"label": "Unemployment Rate",           "unit_display": "%"},
    "labor_part_rate":  {"label": "Labor Participation Rate",    "unit_display": "%"},
    "nonfarm_payrolls": {"label": "Nonfarm Payrolls",            "unit_display": "Thousands"},
    "yield_3m":         {"label": "3-Month Treasury Yield",      "unit_display": "%"},
    "yield_2y":         {"label": "2-Year Treasury Yield",       "unit_display": "%"},
    "yield_5y":         {"label": "5-Year Treasury Yield",       "unit_display": "%"},
    "yield_10y":        {"label": "10-Year Treasury Yield",      "unit_display": "%"},
    "yield_30y":        {"label": "30-Year Treasury Yield",      "unit_display": "%"},
    "yield_spread":     {"label": "10Y-2Y Treasury Spread",      "unit_display": "%"},
    "dollar_index":     {"label": "USD Trade-Weighted Index",    "unit_display": "Index"},
    "vix":              {"label": "VIX Volatility Index",        "unit_display": "Index"},
    "sp500":            {"label": "S&P 500 Index",               "unit_display": "Index"},
    "mortgage_30y":     {"label": "30-Year Mortgage Rate",       "unit_display": "%"},
    "m2":               {"label": "M2 Money Stock",              "unit_display": "Billions USD"},
    "industrial_prod":  {"label": "Industrial Production",       "unit_display": "Index"},
    "retail_sales":     {"label": "Advance Retail Sales",        "unit_display": "Millions USD"},
    "housing_starts":   {"label": "Housing Starts",              "unit_display": "Thousands"},
    "consumer_sent":    {"label": "Consumer Sentiment",          "unit_display": "Index"},
    "fed_balance":      {"label": "Fed Total Assets",            "unit_display": "Millions USD"},
    "jobless_claims":   {"label": "Initial Jobless Claims",      "unit_display": "Claims"},
    "yield_1y":         {"label": "1-Year Treasury Yield",       "unit_display": "%"},
}

#: Curated default set for the macro dashboard (keys into FRED_SERIES).
DEFAULT_INDICATOR_KEYS: list[str] = [
    "fed_funds",
    "fed_funds_target",
    "cpi_all",
    "cpi_core",
    "pce_core",
    "unemployment",
    "gdp_growth",
    "yield_3m",
    "yield_2y",
    "yield_10y",
    "yield_spread",
    "vix",
    "dollar_index",
    "nonfarm_payrolls",
    "mortgage_30y",
]


def _estimated_freshness(
    obs_date: datetime, frequency: str, now: Optional[datetime] = None
) -> DataFreshness:
    """Freshness for a keyless row whose true release date is unknown.

    The CSV endpoint does not publish FRED's release/vintage stamp.  For
    same-day series (daily/weekly) the observation date *is* the release date,
    so wall-clock freshness is exact.  For monthly and longer series the
    observation date is the reference period, which is published one cadence
    later — measuring plain wall-clock age would wrongly mark the current
    reading STALE.  This scales the window to the series' own cadence instead,
    and the API flags the row ``release_date_estimated`` so the caveat stays
    visible.
    """
    now = now or datetime.now(timezone.utc)
    cadence = {
        "Daily": 1, "Weekly": 7, "Biweekly": 14,
        "Monthly": 31, "Quarterly": 92, "Annual": 365,
    }.get(frequency)
    if cadence is None or cadence <= 14:
        return determine_data_freshness(obs_date, now)
    age_days = (now - obs_date).days
    if age_days <= cadence + 10:
        return DataFreshness.RECENT
    if age_days <= 2 * cadence + 10:
        return DataFreshness.DELAYED
    if age_days <= 4 * cadence:
        return DataFreshness.HISTORICAL
    return DataFreshness.STALE


def _infer_frequency(dates: list[datetime]) -> str:
    """Infer a series frequency from the spacing of its own observations."""
    if len(dates) < 2:
        return ""
    gaps = sorted(
        (dates[i + 1] - dates[i]).days
        for i in range(len(dates) - 1)
        if (dates[i + 1] - dates[i]).days > 0
    )
    if not gaps:
        return ""
    median_gap = gaps[len(gaps) // 2]
    if median_gap <= 4:
        return "Daily"
    if median_gap <= 10:
        return "Weekly"
    if median_gap <= 20:
        return "Biweekly"
    if median_gap <= 45:
        return "Monthly"
    if median_gap <= 120:
        return "Quarterly"
    return "Annual"


#: series_id -> display unit, derived from the labels above (the keyless CSV
#: carries no unit metadata, so this is where it comes from).
_FRED_SERIES_UNITS: dict[str, str] = {
    FRED_SERIES[key]: meta["unit_display"]
    for key, meta in FRED_SERIES_LABELS.items()
    if key in FRED_SERIES
}
