"""
Derivatives models for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module contains SQLAlchemy ORM models for derivatives data persistence.
All models are designed for non-monetary paper/simulation educational purposes.
"""

from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, Text, Index
from datetime import datetime
import uuid
from ...db import Base


class DerivativeInstrument(Base):
    """
    Derivative instrument model representing tradable perpetual futures contracts.
    
    This is a data model for educational analytics and paper simulation only.
    No real-money execution or trading is supported.
    """
    __tablename__ = "derivative_instruments"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    asset_class = Column(String, nullable=False, index=True)  # STOCKS, CRYPTO, INDICES, COMMODITIES
    underlying = Column(String, nullable=False)
    quote_currency = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    status = Column(String, default="ACTIVE")  # ACTIVE, SUSPENDED, DELISTED
    contract_type = Column(String, default="PERPETUAL")  # PERPETUAL, FUTURE, OPTION
    tick_size = Column(Float, nullable=False)
    lot_size = Column(Float, nullable=False)
    price_precision = Column(Integer, nullable=False)
    quantity_precision = Column(Integer, nullable=False)
    min_order_size = Column(Float, default=0.001)
    max_order_size = Column(Float, default=1000000.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_asset_class_status', 'asset_class', 'status'),
        Index('idx_exchange_symbol', 'exchange', 'symbol'),
    )


class DerivativeQuoteHistory(Base):
    """
    Historical quotes for derivative instruments.
    
    Stores historical price data for analytics and paper simulation.
    All data is sourced from legitimate market data providers.
    """
    __tablename__ = "derivative_quote_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    instrument_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    last_price = Column(Float, nullable=False)
    bid = Column(Float)
    ask = Column(Float)
    spread = Column(Float)
    mark_price = Column(Float)
    index_price = Column(Float)
    change_24h = Column(Float)
    change_percent_24h = Column(Float)
    high_24h = Column(Float)
    low_24h = Column(Float)
    volume_24h = Column(Float)
    open_interest = Column(Float)
    funding_rate = Column(Float)
    source = Column(String, nullable=False)
    data_mode = Column(String, default="LIVE")  # LIVE, DELAYED, HISTORICAL
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Indexes for time-series queries
    __table_args__ = (
        Index('idx_instrument_timestamp', 'instrument_id', 'timestamp'),
        Index('idx_timestamp', 'timestamp'),
    )


class FundingRateHistory(Base):
    """
    Historical funding rates for perpetual futures.
    
    Tracks funding rate changes over time for analytics and trend analysis.
    """
    __tablename__ = "funding_rate_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    instrument_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    funding_rate = Column(Float, nullable=False)
    predicted_funding_rate = Column(Float)
    next_funding_time = Column(DateTime)
    source = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_funding_instrument_timestamp', 'instrument_id', 'timestamp'),
    )


class OpenInterestHistory(Base):
    """
    Historical open interest data for derivative instruments.
    
    Tracks open interest changes over time for market sentiment analysis.
    """
    __tablename__ = "open_interest_history"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    instrument_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    open_interest = Column(Float, nullable=False)
    open_interest_value = Column(Float)  # Open interest in quote currency
    source = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_oi_instrument_timestamp', 'instrument_id', 'timestamp'),
    )


class PaperSimulation(Base):
    """
    Paper/simulation trade records for educational purposes.
    
    Stores hypothetical trading scenarios without real-money execution.
    Clearly labeled as PAPER SIMULATION.
    """
    __tablename__ = "paper_simulations"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    instrument_id = Column(String, nullable=False, index=True)
    scenario_name = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # LONG, SHORT
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    quantity = Column(Float, nullable=False)
    leverage = Column(Float, default=1.0)
    entry_timestamp = Column(DateTime, default=datetime.utcnow)
    exit_timestamp = Column(DateTime)
    gross_pnl = Column(Float)
    gross_pnl_percent = Column(Float)
    status = Column(String, default="ACTIVE")  # ACTIVE, CLOSED, CANCELLED
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_paper_user', 'user_id', 'status'),
        Index('idx_paper_instrument', 'instrument_id', 'status'),
    )
