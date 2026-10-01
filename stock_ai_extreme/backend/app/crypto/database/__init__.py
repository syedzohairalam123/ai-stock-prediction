"""Persistence models for the crypto intelligence module."""

from __future__ import annotations

from app.crypto.database.models import (
    CryptoAsset,
    CryptoCandle,
    CryptoCategory,
    CryptoDataSource,
    CryptoForecast,
    CryptoForecastEvaluation,
    CryptoProviderHealth,
    CryptoQuote,
    CryptoTarget,
    CryptoTargetEvent,
)

__all__ = [
    "CryptoAsset",
    "CryptoCandle",
    "CryptoCategory",
    "CryptoDataSource",
    "CryptoForecast",
    "CryptoForecastEvaluation",
    "CryptoProviderHealth",
    "CryptoQuote",
    "CryptoTarget",
    "CryptoTargetEvent",
]
