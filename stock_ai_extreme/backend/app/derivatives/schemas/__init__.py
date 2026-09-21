"""
Derivatives schemas for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module contains Pydantic schemas for request/response validation.
All schemas are designed for non-monetary paper/simulation educational purposes.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class AssetClass(str, Enum):
    """Asset class categories for derivative instruments."""
    STOCKS = "STOCKS"
    CRYPTO = "CRYPTO"
    INDICES = "INDICES"
    COMMODITIES = "COMMODITIES"


class ContractType(str, Enum):
    """Types of derivative contracts."""
    PERPETUAL = "PERPETUAL"
    FUTURE = "FUTURE"
    OPTION = "OPTION"


class InstrumentStatus(str, Enum):
    """Status of derivative instruments."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class DataFreshness(str, Enum):
    """Data freshness states for market data."""
    LIVE = "LIVE"
    RECENT = "RECENT"
    DELAYED = "DELAYED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class DerivativeInstrument(BaseModel):
    """
    Derivative instrument schema.
    
    Represents a tradable perpetual futures contract for educational analytics.
    """
    id: str
    symbol: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    asset_class: AssetClass
    underlying: str = Field(..., min_length=1, max_length=50)
    quote_currency: str = Field(..., min_length=1, max_length=10)
    exchange: str = Field(..., min_length=1, max_length=50)
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    contract_type: ContractType = ContractType.PERPETUAL
    tick_size: float = Field(..., gt=0)
    lot_size: float = Field(..., gt=0)
    price_precision: int = Field(..., ge=0, le=8)
    quantity_precision: int = Field(..., ge=0, le=8)
    min_order_size: float = Field(default=0.001, gt=0)
    max_order_size: float = Field(default=1000000.0, gt=0)
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class DerivativeQuote(BaseModel):
    """
    Live quote schema for derivative instruments.
    
    Contains real market data from legitimate providers.
    All numeric fields remain numeric internally.
    """
    instrument_id: str
    timestamp: datetime
    last_price: float = Field(..., gt=0)
    bid: Optional[float] = Field(None, gt=0)
    ask: Optional[float] = Field(None, gt=0)
    spread: Optional[float] = Field(None, ge=0)
    mark_price: Optional[float] = Field(None, gt=0)
    index_price: Optional[float] = Field(None, gt=0)
    change_24h: Optional[float] = None
    change_percent_24h: Optional[float] = None
    high_24h: Optional[float] = Field(None, gt=0)
    low_24h: Optional[float] = Field(None, gt=0)
    volume_24h: Optional[float] = Field(None, ge=0)
    open_interest: Optional[float] = Field(None, ge=0)
    funding_rate: Optional[float] = None
    source: str = Field(..., min_length=1)
    data_mode: DataFreshness = DataFreshness.LIVE
    
    @field_validator('spread')
    @classmethod
    def validate_spread(cls, v, info):
        if v is not None and 'ask' in info.data and 'bid' in info.data:
            if info.data['ask'] and info.data['bid']:
                if v != info.data['ask'] - info.data['bid']:
                    # Allow small floating point differences
                    if abs(v - (info.data['ask'] - info.data['bid'])) > 0.0001:
                        raise ValueError('Spread must equal ask - bid')
        return v
    
    class Config:
        from_attributes = True


class MarketDepthLevel(BaseModel):
    """Single level in the order book."""
    price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    cumulative_quantity: Optional[float] = Field(None, ge=0)


class MarketDepth(BaseModel):
    """
    Order book / market depth data.
    
    Read-only visualization of bids and asks.
    """
    instrument_id: str
    timestamp: datetime
    bids: List[MarketDepthLevel] = Field(default_factory=list)
    asks: List[MarketDepthLevel] = Field(default_factory=list)
    source: str
    data_mode: DataFreshness = DataFreshness.LIVE
    
    @field_validator('bids', 'asks')
    @classmethod
    def validate_order_book(cls, v):
        # Ensure prices are sorted correctly
        if v:
            prices = [level.price for level in v]
            if not all(prices[i] >= prices[i+1] for i in range(len(prices)-1)):
                raise ValueError('Order book must be sorted by price')
        return v


class FundingData(BaseModel):
    """
    Funding rate data for perpetual futures.
    
    Contains current and historical funding information.
    """
    instrument_id: str
    current_funding_rate: Optional[float] = None
    predicted_funding_rate: Optional[float] = None
    next_funding_time: Optional[datetime] = None
    last_funding_rate: Optional[float] = None
    funding_interval_hours: Optional[int] = Field(None, ge=1)
    historical_rates: List[dict] = Field(default_factory=list)
    source: str
    data_mode: DataFreshness = DataFreshness.LIVE


class OpenInterestData(BaseModel):
    """
    Open interest data for derivative instruments.
    
    Tracks current and historical open interest.
    """
    instrument_id: str
    current_open_interest: Optional[float] = Field(None, ge=0)
    open_interest_value: Optional[float] = Field(None, ge=0)
    open_interest_change_24h: Optional[float] = None
    open_interest_change_percent_24h: Optional[float] = None
    historical_oi: List[dict] = Field(default_factory=list)
    source: str
    data_mode: DataFreshness = DataFreshness.LIVE


class MarketMicrostructure(BaseModel):
    """
    Market microstructure metrics.
    
    Calculated metrics from order book and quote data.
    """
    instrument_id: str
    timestamp: datetime
    bid_ask_spread: Optional[float] = Field(None, ge=0)
    mid_price: Optional[float] = Field(None, gt=0)
    spread_percent: Optional[float] = Field(None, ge=0)
    bid_depth: Optional[float] = Field(None, ge=0)
    ask_depth: Optional[float] = Field(None, ge=0)
    depth_imbalance: Optional[float] = None  # -1 to 1, negative = ask-heavy
    volume_imbalance: Optional[float] = None
    price_to_mark_diff: Optional[float] = None
    liquidity_score: Optional[float] = Field(None, ge=0, le=1)


class PaperSimulationScenario(BaseModel):
    """
    Paper/simulation scenario for educational purposes.
    
    Hypothetical trading scenario without real-money execution.
    """
    id: Optional[str] = None
    user_id: str
    instrument_id: str
    scenario_name: str = Field(..., min_length=1, max_length=100)
    direction: str = Field(..., pattern="^(LONG|SHORT)$")
    entry_price: float = Field(..., gt=0)
    exit_price: Optional[float] = Field(None, gt=0)
    quantity: float = Field(..., gt=0)
    leverage: float = Field(default=1.0, gt=0)
    entry_timestamp: datetime = Field(default_factory=datetime.utcnow)
    exit_timestamp: Optional[datetime] = None
    gross_pnl: Optional[float] = None
    gross_pnl_percent: Optional[float] = None
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|CLOSED|CANCELLED)$")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class PaperSimulationRequest(BaseModel):
    """Request to create a paper simulation scenario."""
    instrument_id: str
    scenario_name: str = Field(..., min_length=1, max_length=100)
    direction: str = Field(..., pattern="^(LONG|SHORT)$")
    entry_price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    leverage: float = Field(default=1.0, gt=0, le=100)
    notes: Optional[str] = None


class PaperSimulationUpdate(BaseModel):
    """Request to update a paper simulation scenario."""
    exit_price: Optional[float] = Field(None, gt=0)
    status: Optional[str] = Field(None, pattern="^(ACTIVE|CLOSED|CANCELLED)$")
    notes: Optional[str] = None


class HistoricalReplayRequest(BaseModel):
    """Request for historical replay simulation."""
    instrument_id: str
    start_date: datetime
    end_date: datetime
    entry_price: float = Field(..., gt=0)
    direction: str = Field(..., pattern="^(LONG|SHORT)$")
    quantity: float = Field(..., gt=0)
    leverage: float = Field(default=1.0, gt=0, le=100)


class HistoricalReplayResult(BaseModel):
    """Result of historical replay simulation."""
    instrument_id: str
    entry_reference: float
    exit_reference: float
    price_movement: float
    hypothetical_result: float
    hypothetical_result_percent: float
    max_drawdown: float
    max_profit: float
    data_points: int
    disclaimer: str = "Paper simulation only - not investment advice"


class AdvancedAnalytics(BaseModel):
    """
    Advanced analytics using statistical methods.
    
    Calculated metrics using NumPy, Pandas, SciPy.
    """
    instrument_id: str
    timestamp: datetime
    volatility: Optional[float] = Field(None, ge=0)
    returns_mean: Optional[float] = None
    returns_std: Optional[float] = Field(None, ge=0)
    rolling_volatility_7d: Optional[float] = Field(None, ge=0)
    rolling_volatility_30d: Optional[float] = Field(None, ge=0)
    moving_average_7d: Optional[float] = Field(None, gt=0)
    moving_average_30d: Optional[float] = Field(None, gt=0)
    max_drawdown: Optional[float] = Field(None, le=0)
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    z_score: Optional[float] = None
    volume_anomaly_score: Optional[float] = Field(None, ge=0, le=1)
    price_momentum: Optional[float] = None
    rsi: Optional[float] = Field(None, ge=0, le=100)
    bollinger_upper: Optional[float] = Field(None, gt=0)
    bollinger_lower: Optional[float] = Field(None, gt=0)
    bollinger_middle: Optional[float] = Field(None, gt=0)


class RiskMetrics(BaseModel):
    """
    Risk visualization metrics for educational purposes.
    
    Display risk metrics without guaranteed profit claims.
    """
    instrument_id: str
    timestamp: datetime
    historical_volatility: Optional[float] = Field(None, ge=0)
    max_historical_drawdown: Optional[float] = Field(None, le=0)
    recent_price_range: Optional[float] = Field(None, gt=0)
    value_at_risk_95: Optional[float] = Field(None, le=0)
    expected_shortfall_95: Optional[float] = Field(None, le=0)
    data_quality_score: Optional[float] = Field(None, ge=0, le=1)
    liquidity_indicator: Optional[float] = Field(None, ge=0, le=1)
    market_stress_indicator: Optional[float] = Field(None, ge=0, le=1)
    correlation_benchmark: Optional[float] = Field(None, ge=-1, le=1)
    beta: Optional[float] = None
    disclaimer: str = "Educational risk metrics - not investment advice"


class InstrumentListResponse(BaseModel):
    """Response for instrument list endpoint."""
    instruments: List[DerivativeInstrument]
    total: int
    asset_class: AssetClass


class QuoteResponse(BaseModel):
    """Response for quote endpoint."""
    quote: DerivativeQuote
    microstructure: Optional[MarketMicrostructure] = None


class DataQualityReport(BaseModel):
    """Data quality validation report."""
    instrument_id: str
    timestamp: datetime
    source: str
    schema_valid: bool
    type_valid: bool
    timestamp_valid: bool
    normalized: bool
    freshness: DataFreshness
    quality_score: float = Field(..., ge=0, le=1)
    issues: List[str] = Field(default_factory=list)
