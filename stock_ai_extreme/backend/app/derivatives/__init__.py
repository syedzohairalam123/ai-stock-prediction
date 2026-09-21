"""
Derivatives module for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides professional real-data perpetual-futures market analytics with a 
non-monetary paper/simulation environment for educational purposes.

Features:
- Real market data from legitimate providers (YFinance, Binance)
- Asset categories: STOCKS, CRYPTO, INDICES, COMMODITIES
- Live quotes with data quality validation
- Market depth / order book visualization
- Funding rate analytics
- Open interest analytics
- Market microstructure metrics
- Paper/simulation trading scenarios
- Historical replay functionality
- Advanced statistical analytics
- Risk visualization metrics
- WebSocket real-time streaming
- Comprehensive error handling

IMPORTANT: This is for analytics and educational simulation only.
NO real-money execution, deposits, withdrawals, or trading is supported.
"""

from .routes import router as derivatives_router

__all__ = ["derivatives_router"]
