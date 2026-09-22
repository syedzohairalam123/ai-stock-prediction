"""
Provider package for Phase 18 (spec §13).

``build_default_providers`` is the single place a new source gets wired in.
The engine consumes the interface, never the implementations, so providers
can be toggled or replaced without touching aggregation code.
"""
from __future__ import annotations

from typing import List

from .base import PoliticalDataProvider, ProviderFetch, ProviderResult, provider_reports
from .gdelt_provider import GdeltProvider
from .medsl_provider import MedslProvider
from .openfec_provider import OpenFECProvider
from .polymarket_provider import PolymarketProvider
from .population_provider import PopulationProvider


def build_default_providers() -> List[PoliticalDataProvider]:
    """The Phase 18 source registry — every one public and keyless-friendly."""
    return [
        OpenFECProvider(),
        PolymarketProvider(),
        MedslProvider(),
        GdeltProvider(),
    ]


__all__ = [
    "PoliticalDataProvider",
    "ProviderFetch",
    "ProviderResult",
    "provider_reports",
    "GdeltProvider",
    "MedslProvider",
    "OpenFECProvider",
    "PolymarketProvider",
    "PopulationProvider",
    "build_default_providers",
]
