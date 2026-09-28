"""
Phase 21 — HTTP surface for the analytics layer.

Thin by design: parse → validate → call `service` → serialize. Every endpoint
answers with the data's own provenance (`data.source`, `data.status`) and the
same JSON-safe convention as the rest of the app: a statistic the sample cannot
support is `null` with a stated `reason`, never a number invented to fill a
slot. Nothing here can place an order or move money — read-only statistics.
"""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..logging_config import get_logger
from ..security import validate_ticker
from .config import quant_settings
from .service import (
    beta_analytics,
    bootstrap_analytics,
    config_snapshot,
    event_study_analytics,
    instrument_analytics,
    rolling_beta_analytics,
    stationarity_analytics,
    tail_risk_analytics,
)

logger = get_logger("neural_market.quant.routes")

quant_router = APIRouter(prefix="/api/quant", tags=["quant"])


class _ValidatedTicker(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def _clean(cls, value: str) -> str:
        try:
            return validate_ticker(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


class BootstrapRequest(BaseModel):
    values: list[float] = Field(min_length=3, max_length=10000)
    seed: Optional[int] = None

    @field_validator("values")
    @classmethod
    def _finite(cls, values: list[float]) -> list[float]:
        cleaned = [v for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
        if len(cleaned) < 3:
            raise HTTPException(status_code=422, detail="at least 3 finite values are required")
        return cleaned


class EventStudyRequest(BaseModel):
    ticker: str
    benchmark: Optional[str] = None
    eventIndices: list[int] = Field(min_length=1, max_length=200)
    labels: Optional[list[str]] = None
    lookbackDays: Optional[int] = Field(default=None, ge=60, le=3650)
    estimationWindow: Optional[int] = Field(default=None, ge=20, le=600)
    gapWindow: Optional[int] = Field(default=None, ge=0, le=60)
    offsets: Optional[list[int]] = Field(default=None, max_length=40)

    @field_validator("ticker", "benchmark")
    @classmethod
    def _clean_tickers(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            return validate_ticker(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@quant_router.get("/config")
async def quant_config() -> dict:
    """Publish the exact thresholds the engines use (no hidden constants)."""
    return config_snapshot()


@quant_router.get("/instruments/{ticker}/analytics")
async def instrument_analytics_route(
    ticker: str,
    kind: Optional[str] = Query(default=None, description="Optional instrument-kind hint"),
    lookbackDays: Optional[int] = Query(default=None, ge=60, le=3650),
) -> dict:
    """Full statistical picture of one instrument from real daily bars."""
    clean = _ValidatedTicker(ticker=ticker).ticker
    try:
        return await instrument_analytics(clean, kind=kind, lookback_days=lookbackDays)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("instrument analytics failed for %s: %s", clean, exc)
        raise HTTPException(status_code=502, detail=f"analytics unavailable: {exc}") from exc


@quant_router.get("/instruments/{ticker}/beta")
async def beta_route(
    ticker: str,
    benchmark: Optional[str] = Query(default=None),
    window: int = Query(default=60, ge=10, le=252),
    lookbackDays: Optional[int] = Query(default=None, ge=60, le=3650),
) -> dict:
    """Market-model beta with Newey-West HAC inference + rolling beta."""
    clean = _ValidatedTicker(ticker=ticker).ticker
    benchmark = _ValidatedTicker(ticker=benchmark).ticker if benchmark else None
    try:
        return await beta_analytics(clean, benchmark, lookback_days=lookbackDays, window=window)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("beta analytics failed for %s: %s", clean, exc)
        raise HTTPException(status_code=502, detail=f"beta unavailable: {exc}") from exc


@quant_router.get("/instruments/{ticker}/rolling-beta")
async def rolling_beta_route(
    ticker: str,
    benchmark: Optional[str] = Query(default=None),
    window: int = Query(default=60, ge=10, le=252),
    lookbackDays: Optional[int] = Query(default=None, ge=60, le=3650),
) -> dict:
    clean = _ValidatedTicker(ticker=ticker).ticker
    benchmark = _ValidatedTicker(ticker=benchmark).ticker if benchmark else None
    try:
        return await rolling_beta_analytics(clean, benchmark, window=window, lookback_days=lookbackDays)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("rolling beta failed for %s: %s", clean, exc)
        raise HTTPException(status_code=502, detail=f"rolling beta unavailable: {exc}") from exc


@quant_router.get("/instruments/{ticker}/stationarity")
async def stationarity_route(
    ticker: str,
    lookbackDays: Optional[int] = Query(default=None, ge=60, le=3650),
) -> dict:
    """ADF/KPSS on levels and returns, variance ratios, Hurst, regime hint."""
    clean = _ValidatedTicker(ticker=ticker).ticker
    try:
        return await stationarity_analytics(clean, lookback_days=lookbackDays)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("stationarity failed for %s: %s", clean, exc)
        raise HTTPException(status_code=502, detail=f"stationarity unavailable: {exc}") from exc


@quant_router.get("/instruments/{ticker}/tail-risk")
async def tail_risk_route(
    ticker: str,
    horizon: int = Query(default=1, ge=1, le=60),
    lookbackDays: Optional[int] = Query(default=None, ge=60, le=3650),
) -> dict:
    """VaR/CVaR by historic / parametric / Student-t / Cornish-Fisher / MC."""
    clean = _ValidatedTicker(ticker=ticker).ticker
    try:
        return await tail_risk_analytics(clean, lookback_days=lookbackDays, horizon=horizon)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("tail risk failed for %s: %s", clean, exc)
        raise HTTPException(status_code=502, detail=f"tail risk unavailable: {exc}") from exc


@quant_router.post("/event-study")
async def event_study_route(body: EventStudyRequest) -> dict:
    """Market-model event study with Patell test + bootstrap CI on real bars."""
    try:
        return await event_study_analytics(
            body.ticker,
            body.eventIndices,
            labels=body.labels,
            benchmark=body.benchmark,
            lookback_days=body.lookbackDays,
            estimation_window=body.estimationWindow,
            gap_window=body.gapWindow,
            offsets=body.offsets,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("event study failed for %s: %s", body.ticker, exc)
        raise HTTPException(status_code=502, detail=f"event study unavailable: {exc}") from exc


@quant_router.post("/bootstrap")
async def bootstrap_route(body: BootstrapRequest) -> dict:
    """Percentile-bootstrap CI for the mean of an arbitrary sample."""
    try:
        return await bootstrap_analytics(body.values, seed=body.seed)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
