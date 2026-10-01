"""
Typed contracts for the crypto intelligence module.

Every candle is validated on the way in (non-negative prices/volume and the
structural high>=max(open,close) / low<=min(open,close) invariant), so a
malformed provider record is rejected at the boundary instead of propagating
into analytics (spec §5, §93).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------
class DataStatus(str, Enum):
    """Freshness/mode label attached to every dataset (spec §54)."""

    LIVE = "LIVE"
    RECENT = "RECENT"
    DELAYED = "DELAYED"
    STALE = "STALE"
    HISTORICAL = "HISTORICAL"
    UNAVAILABLE = "UNAVAILABLE"


class QualityLabel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


class TrendDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    SIDEWAYS = "SIDEWAYS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class TargetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REACHED = "REACHED"
    MISSED = "MISSED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ValueOrigin(str, Enum):
    """Where a visible number comes from (spec §99). Never hidden."""

    SOURCE = "SOURCE"
    CALCULATED = "CALCULATED"
    MODELLED = "MODELLED"
    DERIVED = "DERIVED"
    UNAVAILABLE = "UNAVAILABLE"


# ---------------------------------------------------------------------------
# market data
# ---------------------------------------------------------------------------
class Candle(BaseModel):
    """A normalized OHLCV candle with the structural invariants enforced."""

    timestamp: datetime
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    close: float = Field(..., ge=0)
    volume: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> "Candle":
        if self.high < max(self.open, self.close):
            raise ValueError("high must be >= max(open, close)")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= min(open, close)")
        return self

    @property
    def epoch_ms(self) -> int:
        return int(self.timestamp.timestamp() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "epoch_ms": self.epoch_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class MarketTick(BaseModel):
    """One normalized live tick (spec §10)."""

    symbol: str
    price: float = Field(..., ge=0)
    bid: Optional[float] = Field(default=None, ge=0)
    ask: Optional[float] = Field(default=None, ge=0)
    volume: Optional[float] = Field(default=None, ge=0)
    timestamp: datetime
    source_timestamp: Optional[datetime] = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "received_at": self.received_at.isoformat(),
            "source": self.source,
        }


class DataGapReport(BaseModel):
    """Completeness audit for a candle series (spec §7)."""

    timeframe: str
    expected_intervals: int
    received_intervals: int
    missing_intervals: int
    duplicate_intervals: int
    out_of_order: int
    largest_gap_seconds: float
    completeness: float = Field(..., ge=0, le=1)
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# analytics
# ---------------------------------------------------------------------------
class MicroTrendResult(BaseModel):
    direction: TrendDirection
    strength: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    timeframe: str
    recent_return: Optional[float] = None
    volatility_regime: Optional[VolatilityRegime] = None
    factors: Dict[str, Any] = Field(default_factory=dict)
    sample_size: int = 0
    data_status: DataStatus = DataStatus.UNAVAILABLE
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload["direction"] = self.direction.value
        payload["volatility_regime"] = self.volatility_regime.value if self.volatility_regime else None
        payload["data_status"] = self.data_status.value
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


class VolatilitySnapshot(BaseModel):
    timeframe: str
    realized_volatility: Optional[float] = None      # annualised, from log returns
    rolling_std: Optional[float] = None
    atr: Optional[float] = None
    atr_percent: Optional[float] = None              # ATR as % of close
    range_volatility: Optional[float] = None         # mean (high-low)/close
    volatility_percentile: Optional[float] = Field(default=None, ge=0, le=100)
    regime: VolatilityRegime = VolatilityRegime.INSUFFICIENT_DATA
    window: int = 0
    sample_size: int = 0
    data_status: DataStatus = DataStatus.UNAVAILABLE
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload["regime"] = self.regime.value
        payload["data_status"] = self.data_status.value
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


# ---------------------------------------------------------------------------
# forecasting
# ---------------------------------------------------------------------------
class ForecastMetrics(BaseModel):
    mae: Optional[float] = None
    rmse: Optional[float] = None
    mape: Optional[float] = None
    directional_accuracy: Optional[float] = Field(default=None, ge=0, le=1)
    observations: int = 0


class CryptoForecast(BaseModel):
    """A versioned, reproducible modelled forecast (spec §28/§29)."""

    id: str
    symbol: str
    timeframe: str
    horizon: int
    generated_at: datetime
    prediction: float
    last_close: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    model_name: str
    model_version: str
    feature_version: str
    training_window: int
    training_end_time: Optional[datetime] = None
    metrics: ForecastMetrics
    baseline_metrics: ForecastMetrics
    beats_baseline: bool
    data_source: str
    data_quality: QualityLabel
    label: str = "MODELLED FORECAST"
    origin: ValueOrigin = ValueOrigin.MODELLED
    limitations: List[str] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload["generated_at"] = self.generated_at.isoformat()
        payload["training_end_time"] = (
            self.training_end_time.isoformat() if self.training_end_time else None
        )
        payload["data_quality"] = self.data_quality.value
        payload["origin"] = self.origin.value
        return payload


class ForecastEvaluation(BaseModel):
    """A stored forecast scored against the outcome that actually happened."""

    forecast_id: str
    symbol: str
    timeframe: str
    predicted: float
    actual: Optional[float]
    error: Optional[float]
    absolute_error: Optional[float]
    directional_correct: Optional[bool]
    evaluated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload["evaluated_at"] = self.evaluated_at.isoformat()
        return payload


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------
class PriceTarget(BaseModel):
    id: str
    symbol: str
    target_price: float = Field(..., gt=0)
    direction: str  # "above" | "below"
    target_date: Optional[datetime] = None
    created_at: datetime
    source: str
    methodology: str
    status: TargetStatus
    first_reached_at: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload["status"] = self.status.value
        payload["created_at"] = self.created_at.isoformat()
        payload["target_date"] = self.target_date.isoformat() if self.target_date else None
        payload["first_reached_at"] = self.first_reached_at.isoformat() if self.first_reached_at else None
        return payload


# ---------------------------------------------------------------------------
# API envelope (spec §61)
# ---------------------------------------------------------------------------
class ResponseMeta(BaseModel):
    generated_at: datetime
    source: Optional[str] = None
    data_status: Optional[DataStatus] = None
    quality: Optional[QualityLabel] = None
    age_ms: Optional[int] = None
    timeframe: Optional[str] = None
    notes: List[str] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = self.model_dump()
        payload["generated_at"] = self.generated_at.isoformat()
        payload["data_status"] = self.data_status.value if self.data_status else None
        payload["quality"] = self.quality.value if self.quality else None
        return payload


class ApiEnvelope(BaseModel):
    """Consistent wrapper for every v1 crypto response."""

    data: Any
    meta: ResponseMeta
    request_id: str
    errors: List[str] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data": self.data,
            "meta": self.meta.to_dict(),
            "requestId": self.request_id,
            "errors": self.errors,
        }
