"""
Phase 23A — Central Bank and Macroeconomic Intelligence Engine.

Provides real data integration for:
- Central bank meeting schedules (Federal Reserve, BOJ, ECB, etc.)
- Policy rate decisions with bps calculations
- Market-implied expectations from legitimate sources
- Macroeconomic time-series data with revision tracking
- Policy history and rate change analytics

All data is sourced from official publications or licensed providers.
No hardcoded values, no fabricated probabilities.
"""
from .models import (
    CentralBankInfo,
    PolicyMeetingInfo,
    PolicyDecisionInfo,
    PolicyExpectationInfo,
    MacroSeriesInfo,
    calculate_bps_change,
    determine_direction,
)
from .sources import (
    FederalReserveSource,
    BankOfJapanSource,
    FREDSource,
    BaseCentralBankSource,
)
from .service import MacroIntelligenceService
from .analytics import (
    PolicyRateAnalytics,
    MacroTrendAnalytics,
    EventWindowAnalysis,
)

__all__ = [
    "CentralBankInfo",
    "PolicyMeetingInfo",
    "PolicyDecisionInfo",
    "PolicyExpectationInfo",
    "MacroSeriesInfo",
    "calculate_bps_change",
    "determine_direction",
    "FederalReserveSource",
    "BankOfJapanSource",
    "FREDSource",
    "BaseCentralBankSource",
    "MacroIntelligenceService",
    "PolicyRateAnalytics",
    "MacroTrendAnalytics",
    "EventWindowAnalysis",
]
