"""Phase 23B — Market Direction Analytics & Corporate Market-Cap Intelligence.

Additive package. It reuses the existing market-data provider stack
(``app.providers.manager``), the existing database (``app.db``) and the Phase
23A policy data (``app.macro_intelligence``) — it does not create a second
market-data service.

Public surface (all additive):

* :class:`~app.market_intel.direction.MarketDirectionEngine` — the spec §3 engine.
* :class:`~app.market_intel.service.MarketIntelligenceService` — the concrete service.
* The named facades from :mod:`app.market_intel.facades` (IndexDataService,
  MarketDirectionService, CompanyDataService, MarketCapService,
  CorporateActionService, MarketScenarioService).
* The numpy/scipy analytics helpers from :mod:`app.market_intel.analytics`.
"""
from .facades import (
    CompanyDataService,
    CorporateActionService,
    IndexDataService,
    MarketCapService,
    MarketDirectionService,
    MarketScenarioService,
    company_data_service,
    corporate_action_service,
    get_market_intel_service,
    index_data_service,
    market_cap_service,
    market_direction_service,
    market_scenario_service,
)
from .direction import (
    DailyObservation,
    Instrument,
    MarketDirectionEngine,
    INSTRUMENTS,
    resolve_instrument,
)
from .service import MarketIntelligenceService, market_intel_service

__all__ = [
    "MarketDirectionEngine",
    "MarketIntelligenceService",
    "market_intel_service",
    "get_market_intel_service",
    "Instrument",
    "DailyObservation",
    "INSTRUMENTS",
    "resolve_instrument",
    "IndexDataService",
    "MarketDirectionService",
    "CompanyDataService",
    "MarketCapService",
    "CorporateActionService",
    "MarketScenarioService",
    "index_data_service",
    "market_direction_service",
    "company_data_service",
    "market_cap_service",
    "corporate_action_service",
    "market_scenario_service",
]
