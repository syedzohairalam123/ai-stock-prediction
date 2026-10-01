"""
Service facade + API envelope (spec §61).

:class:`CryptoService` is the single object the router talks to. It owns the
provider manager and the four sub-services, and it is configured once from
``app.main`` with the same pattern the esports module uses
(:func:`configure_crypto`).

The :func:`envelope` helper produces the uniform response contract — ``data``,
``meta``, ``requestId``, ``errors`` — so no provider-specific JSON is ever
exposed directly to a client (spec §61).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.crypto import categories as categories_mod
from app.crypto import quality as quality_mod
from app.crypto import repositories as repo
from app.crypto.config import crypto_settings
from app.crypto.providers.base import CryptoMarketProvider
from app.crypto.providers.binance_provider import BinanceSpotProvider
from app.crypto.providers.coingecko_provider import CoinGeckoProvider
from app.crypto.providers.manager import CryptoMarketManager
from app.crypto.schemas import ApiEnvelope, DataStatus, QualityLabel, ResponseMeta
from app.crypto.services.forecast import ForecastService
from app.crypto.services.market import MarketService
from app.crypto.services.targets import TargetService
from app.crypto.symbols import symbol_service
from app.crypto.timeframes import capabilities, list_timeframes

logger = logging.getLogger("neural_market.crypto.service")


def envelope(
    data: Any,
    *,
    source: Optional[str] = None,
    data_status: Optional[DataStatus] = None,
    quality: Optional[QualityLabel] = None,
    age_ms: Optional[int] = None,
    timeframe: Optional[str] = None,
    notes: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap a payload in the standard v1 crypto envelope."""
    meta = ResponseMeta(
        generated_at=datetime.now(timezone.utc),
        source=source,
        data_status=data_status,
        quality=quality,
        age_ms=age_ms,
        timeframe=timeframe,
        notes=notes or [],
    )
    return ApiEnvelope(
        data=data,
        meta=meta,
        request_id=request_id or str(uuid.uuid4()),
        errors=errors or [],
    ).to_dict()


class CryptoService:
    """Composition root for the crypto intelligence module."""

    def __init__(self, manager: Optional[CryptoMarketManager] = None) -> None:
        self.manager = manager or build_manager()
        self.market = MarketService(self.manager)
        self.forecast = ForecastService(self.manager, self.market)
        self.targets = TargetService(self.manager, self.market)

    # ---------------------------------------------------------------- reference
    def assets(self) -> Dict[str, Any]:
        return {
            "assets": symbol_service.list_assets(),
            "count": len(symbol_service.list_assets()),
            "industries": symbol_service.by_industry(),
            "note": "Curated catalogue. Symbols are mapped per provider, never assumed identical.",
            "origin": "SOURCE",
        }

    def timeframes(self) -> Dict[str, Any]:
        provider = crypto_settings.primary_provider
        return {
            "default": "5m",
            "timeframes": list_timeframes(),
            "capabilities": capabilities(provider),
            "capability_provider": provider,
            "note": (
                "A timeframe is either native to the provider or aggregated from a real lower "
                "interval. It is never fabricated."
            ),
            "origin": "DERIVED",
        }

    async def sources(self) -> Dict[str, Any]:
        health = await self.manager.health()
        sources = []
        for provider in self.manager.providers:
            entry: Dict[str, Any] = {
                "provider": provider.name,
                "role": "market-data",
                "native_intervals": sorted(provider.native_intervals),
                "streaming": provider.supports_streaming(),
                "base_url": getattr(provider, "rest_url", None) or getattr(provider, "base_url", None),
            }
            if hasattr(provider, "stats"):
                entry["stats"] = provider.stats()  # type: ignore[attr-defined]
            sources.append(entry)
        return {
            "sources": sources,
            "health": [h.to_dict() for h in health],
            "stats": self.manager.stats(),
            "note": "Only configured public keyless providers are listed; no credential is exposed.",
        }

    def categories(self) -> List[Dict[str, Any]]:
        return categories_mod.list_categories()

    async def pre_session(self) -> Dict[str, Any]:
        return await categories_mod.pre_session_view(self.manager)

    async def institutions(self, symbol: str) -> Dict[str, Any]:
        return await categories_mod.institutions_view(self.manager, symbol)

    async def industry(self) -> Dict[str, Any]:
        return await categories_mod.industry_view(self.manager)

    def currency_pairs(self) -> Dict[str, Any]:
        return {
            "base_currency": "USD",
            "quote_asset": "USDT",
            "note": (
                "USDT is the quote leg for the configured spot provider. It is a real traded "
                "pair, not a currency conversion."
            ),
        }

    # ------------------------------------------------------------------- health
    async def health(self) -> Dict[str, Any]:
        health = self.manager.health_snapshot()
        availability = [
            {
                "provider": entry["provider"],
                "status": (
                    "AVAILABLE"
                    if entry.get("available") is True
                    else ("DOWN" if entry.get("available") is False else "UNKNOWN")
                ),
                "detail": entry.get("detail"),
                "latency_ms": entry.get("latency_ms"),
            }
            for entry in health
        ]
        return {"status": "ok", "providers": availability, "count": len(availability)}

    async def probe_health(self, *, persist: bool = True) -> List[Dict[str, Any]]:
        """Real provider probes; optionally recorded for the observability table."""
        results = await self.manager.health(probe=True)
        payload = [result.to_dict() for result in results]
        if persist:
            for entry in payload:
                try:
                    repo.record_provider_health(
                        entry["provider"],
                        available=bool(entry["available"]),
                        status=entry["status"],
                        latency_ms=entry.get("latency_ms"),
                        detail=entry.get("detail"),
                    )
                except Exception as exc:  # pragma: no cover - observability is best-effort
                    logger.debug("provider health persist failed: %s", exc)
        return payload

    def persistence_status(self) -> Dict[str, Any]:
        return {
            "counts": repo.persistence_counts(),
            "note": "Row counts of what has actually been persisted; no synthetic rows are created.",
        }

    def observability(self) -> Dict[str, Any]:
        """Cheap status snapshot used by the ops panel (spec §104)."""
        return {
            "cache_entries": self.manager.cache.size(),
            "providers": self.manager.stats()["providers"],
            "health": self.manager.health_snapshot(),
            "timeframes": len(list_timeframes()),
            "assets": len(symbol_service.list_assets()),
            "value_origins": quality_mod.VALUE_ORIGIN_TABLE,
        }

    async def close(self) -> None:
        await self.manager.close()


def build_manager() -> CryptoMarketManager:
    """
    Build the manager from settings.

    Only public keyless providers are configured, and only when the module is
    enabled: no API key is required for the app to start (spec §53 — failover is
    used only between sources that are genuinely configured).
    """
    provider_name = (crypto_settings.primary_provider or "binance").lower()
    providers: List[CryptoMarketProvider] = []
    if provider_name == "binance":
        providers.append(BinanceSpotProvider())
    providers.append(CoinGeckoProvider())
    return CryptoMarketManager(providers)


#: Process-wide singleton, configured from app.main.
crypto_service = CryptoService()


def configure_crypto(service: Optional[CryptoService] = None) -> CryptoService:
    """Bind the singleton (called from app.main with an explicit manager)."""
    global crypto_service
    if service is not None:
        crypto_service = service
    return crypto_service
