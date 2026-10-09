"""Phase 23B — named service facades (spec §15).

The spec suggests a service per responsibility (``IndexDataService``,
``MarketDirectionService``, ``CompanyDataService``, ``MarketCapService``,
``CorporateActionService``, ``MarketScenarioService``). The concrete work all
lives in the single :class:`~app.market_intel.service.MarketIntelligenceService`
— one provider stack, one cache, one database — and these classes are thin,
stateless facades over that instance so a caller can depend on the spec's
names without a second implementation appearing later.

They are importable directly, and the singleton is reachable through
:func:`get_market_intel_service`, so wiring stays in ``main.py`` unchanged.
"""
from __future__ import annotations

from typing import Any, Optional

from .direction import INSTRUMENTS, MarketDirectionEngine, resolve_instrument
from .service import MarketIntelligenceService, market_intel_service


def get_market_intel_service() -> MarketIntelligenceService:
    """The process-wide service the app shell configured (one provider stack)."""
    return market_intel_service


class _Facade:
    """Shared plumbing: resolve the service at call time, not import time.

    Resolving lazily keeps every facade correct after the app shell re-binds the
    singleton (which happens at startup, after import), exactly like the
    existing routes do.
    """

    def __init__(self, service: Optional[MarketIntelligenceService] = None) -> None:
        self._service = service

    @property
    def service(self) -> MarketIntelligenceService:
        return self._service or market_intel_service


class IndexDataService(_Facade):
    """SPX index / SPY ETF observations, quotes and dashboard (spec §2, §5)."""

    async def instruments(self) -> list[dict]:
        return self.service.instruments()

    async def dashboard(self, days: int = 400) -> dict:
        return await self.service.get_dashboard(days=days)

    async def quote(self, instrument: str, days: int = 400) -> dict:
        return await self.service.get_instrument(instrument, days=days, limit=1)

    async def history(
        self,
        instrument: str,
        days: int = 400,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> dict:
        return await self.service.get_instrument(
            instrument, days=days, limit=limit, offset=offset
        )

    async def comparison(self, days: int = 400, limit: Optional[int] = None) -> dict:
        return await self.service.get_comparison(days=days, limit=limit)


class MarketDirectionService(_Facade):
    """UP/DOWN/FLAT history and direction statistics (spec §3, §4, §6)."""

    def engine(self, instrument: str = "spx") -> MarketDirectionEngine:
        resolved = resolve_instrument(instrument)
        if resolved is None:
            raise ValueError(
                f"Unknown instrument '{instrument}'. Supported: {', '.join(INSTRUMENTS)}."
            )
        return MarketDirectionEngine(resolved)

    async def direction(
        self,
        instrument: str,
        days: int = 400,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> dict:
        return await self.service.get_direction_history(
            instrument, days=days, limit=limit, offset=offset
        )

    async def statistics(self, instrument: str, days: int = 400) -> dict:
        return await self.service.get_statistics(instrument, days=days)

    async def rolling(self, instrument: str, days: int = 400, window: int = 20) -> dict:
        return await self.service.get_rolling(instrument, days=days, window=window)


class CompanyDataService(_Facade):
    """Company registry, security mappings and stored observations (spec §8, §9, §14)."""

    async def leaderboard(self, limit: Optional[int] = None, refresh: bool = True) -> dict:
        return await self.service.get_leaderboard(limit=limit, refresh=refresh)

    def history(self, company_id: str, limit: int = 365, offset: int = 0) -> dict:
        return self.service.get_company_history(company_id, limit=limit, offset=offset)

    def security_mappings(self, company_id: Optional[str] = None) -> dict:
        return self.service.get_security_mappings(company_id)


class MarketCapService(_Facade):
    """Dynamic ranking, snapshots and race analytics (spec §11, §12, §14)."""

    async def leaderboard(self, limit: Optional[int] = None, refresh: bool = True) -> dict:
        return await self.service.get_leaderboard(limit=limit, refresh=refresh)

    async def race(self, period_days: int = 180) -> dict:
        return await self.service.get_race(period_days=period_days)

    def snapshots(self, company_id: str, limit: int = 365) -> dict:
        return self.service.get_market_cap_snapshots(company_id, limit=limit)


class CorporateActionService(_Facade):
    """Source-reported corporate actions affecting comparability (spec §10)."""

    def record(
        self,
        company_id: str,
        action_type: str,
        effective_date: Any,
        ratio: Optional[float] = None,
        source: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        return self.service.record_corporate_action(
            company_id, action_type, effective_date, ratio=ratio, source=source, notes=notes
        )

    def list(self, company_id: str, limit: int = 100) -> dict:
        return self.service.get_corporate_actions(company_id, limit=limit)


class MarketScenarioService(_Facade):
    """Hypothetical scenario arithmetic — not a prediction (spec §13)."""

    async def scenario(self, company_id: str, scenario_return: float) -> dict:
        return await self.service.get_scenario(company_id, scenario_return)


#: Pre-built facades so callers can ``from .facades import market_cap_service``.
index_data_service = IndexDataService()
market_direction_service = MarketDirectionService()
company_data_service = CompanyDataService()
market_cap_service = MarketCapService()
corporate_action_service = CorporateActionService()
market_scenario_service = MarketScenarioService()
