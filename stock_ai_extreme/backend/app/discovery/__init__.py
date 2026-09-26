"""
Phase 19 — Advanced Market Discovery / New & Trending Engine.

A *discovery* layer on top of data the application already collects from real
sources. It does not fetch prices of its own and it never invents a popularity
number. Everything it ranks is a measurement somebody actually took:

    * quotes / profiles   -> Phase 2 provider manager (yfinance, …)
    * forecast events     -> Polymarket public Gamma API (createdAt, volume)
    * news topics         -> Phase 17 topic engine (real mention counts)
    * interest signals    -> real events this app recorded (views, searches,
                             watchlist additions) — never simulated

Design rules for the whole package (spec §17):

    1. A metric no source can supply stays ``None`` and is reported as
       ``N/A`` — never defaulted to 0 or a placeholder.
    2. The trend score aggregates only the signals that are actually
       available for an entity; the weights used and the signals that were
       missing are returned with every score (no hidden constants).
    3. Every constant that shapes a score lives in ``config.DiscoverySettings``
       (env prefix ``DISCOVERY_``), not inline in business logic.
"""

from .config import discovery_settings, DiscoverySettings
from .trend_engine import TrendEngine
from .routes import router as discovery_router

__all__ = [
    "DiscoverySettings",
    "discovery_settings",
    "TrendEngine",
    "discovery_router",
]
