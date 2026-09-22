"""
Derivatives routes for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides FastAPI routes for derivatives market data and analytics.
All routes are for educational analytics and paper simulation - no real-money execution.
"""

from datetime import date, datetime, timedelta
import asyncio
from typing import List, Optional
from uuid import uuid4
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field
import logging

from .models import Base
from .schemas import (
    AssetClass, DerivativeInstrument, DerivativeQuote, MarketDepth, FundingData,
    OpenInterestData, MarketMicrostructure, PaperSimulationScenario, PaperSimulationRequest,
    HistoricalReplayRequest, HistoricalReplayResult,
    AdvancedAnalytics, RiskMetrics, InstrumentListResponse, QuoteResponse
)
from .providers import DerivativesDataManager, YFinanceDerivativesProvider, BinanceDerivativesProvider
from .services import (
    MarketMicrostructureService, FundingAnalyticsService, OpenInterestAnalyticsService,
    PaperSimulationService, DerivativesAnalyticsService, RiskMetricsService
)
from .websocket import derivatives_ws_manager
from .config import derivatives_settings

logger = logging.getLogger("neural_market.derivatives.routes")

router = APIRouter(prefix="/api/derivatives", tags=["derivatives"])

# Initialize data manager with providers
providers_list = []
if derivatives_settings.enable_yfinance_provider:
    providers_list.append(YFinanceDerivativesProvider(max_retries=3, timeout=30))
if derivatives_settings.enable_binance_provider:
    providers_list.append(BinanceDerivativesProvider(max_retries=3, timeout=30))

derivatives_manager = DerivativesDataManager(
    providers=providers_list,
    quote_cache_ttl=derivatives_settings.quote_cache_ttl_seconds,
    history_cache_ttl=derivatives_settings.history_cache_ttl_seconds,
    funding_cache_ttl=derivatives_settings.funding_cache_ttl_seconds,
    oi_cache_ttl=derivatives_settings.oi_cache_ttl_seconds,
    depth_cache_ttl=derivatives_settings.depth_cache_ttl_seconds
)

# Phase 16 paper scenarios are intentionally process-local and non-monetary.
# They never represent exchange orders, balances, settlement, or custody.
paper_scenarios = {}
quote_stream_tasks = {}


async def stream_instrument_quotes(instrument_id: str):
    """Poll the legitimate provider and broadcast normalized quote snapshots."""
    try:
        while derivatives_ws_manager.get_instrument_subscribers(instrument_id):
            quote = await derivatives_manager.get_quote(instrument_id)
            if quote.status.value == "UNAVAILABLE" or quote.last_price <= 0:
                await derivatives_ws_manager.broadcast_to_instrument(instrument_id, {
                    "type": "unavailable",
                    "instrument_id": instrument_id,
                    "source": quote.source,
                    "data_mode": quote.status.value,
                    "timestamp": quote.timestamp.isoformat(),
                    "message": "Provider did not supply a valid live quote.",
                })
            else:
                await derivatives_ws_manager.broadcast_to_instrument(instrument_id, {
                    "type": "quote",
                    "quote": quote.to_dict(),
                })
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Derivative quote stream stopped for %s: %s", instrument_id, exc)
    finally:
        quote_stream_tasks.pop(instrument_id, None)


# =============================================================================
# Instrument Endpoints
# =============================================================================

@router.get("/instruments", response_model=InstrumentListResponse)
async def get_instruments(asset_class: Optional[AssetClass] = None):
    """
    Get available derivative instruments.
    
    Returns instruments filtered by asset class if specified.
    All instruments are for educational analytics only.
    """
    try:
        instruments = await derivatives_manager.get_instruments(
            asset_class=asset_class.value if asset_class else None
        )
        
        return InstrumentListResponse(
            instruments=instruments,
            total=len(instruments),
            asset_class=asset_class or AssetClass.CRYPTO
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/instruments/{instrument_id}", response_model=DerivativeInstrument)
async def get_instrument(instrument_id: str):
    """Get details for a specific instrument."""
    try:
        instruments = await derivatives_manager.get_instruments()
        instrument = next((inst for inst in instruments if inst["id"] == instrument_id), None)
        
        if not instrument:
            raise HTTPException(status_code=404, detail=f"Instrument {instrument_id} not found")
        
        return DerivativeInstrument(**instrument)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Quote Endpoints
# =============================================================================

@router.get("/quotes/{instrument_id}", response_model=QuoteResponse)
async def get_quote(instrument_id: str):
    """
    Get current quote for an instrument.
    
    Returns real market data from legitimate providers.
    """
    try:
        quote = await derivatives_manager.get_quote(instrument_id)
        if quote.status.value == "UNAVAILABLE" or quote.last_price <= 0:
            raise HTTPException(status_code=503, detail="Live derivative quote is unavailable; no price was fabricated.")
        
        # Calculate microstructure metrics
        microstructure = None
        try:
            depth = await derivatives_manager.get_market_depth(instrument_id, depth=10)
            microstructure = MarketMicrostructureService.calculate_microstructure(quote, depth)
        except Exception:
            # Depth not available, calculate without it
            microstructure = MarketMicrostructureService.calculate_microstructure(quote, None)
        
        return QuoteResponse(
            quote=quote,
            microstructure=microstructure
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quotes/{instrument_id}/depth", response_model=MarketDepth)
async def get_market_depth(instrument_id: str, depth: int = Query(20, ge=1, le=100)):
    """
    Get order book / market depth for an instrument.
    
    Returns read-only order book visualization where supported by provider.
    """
    try:
        depth_data = await derivatives_manager.get_market_depth(instrument_id, depth)
        return depth_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Historical Data Endpoints
# =============================================================================

@router.get("/historical/{instrument_id}")
async def get_historical_data(
    instrument_id: str,
    start_date: date,
    end_date: date,
    interval: str = Query("1d", pattern="^(1m|5m|15m|1h|4h|1d|1w|1M)$")
):
    """
    Get historical price data for an instrument.
    
    Returns actual historical data from legitimate providers.
    """
    try:
        data = await derivatives_manager.get_historical_data(
            instrument_id, start_date, end_date, interval
        )
        return {
            "instrument_id": instrument_id,
            "data": data,
            "count": len(data)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Funding Analytics Endpoints
# =============================================================================

@router.get("/funding/{instrument_id}", response_model=FundingData)
async def get_funding_data(instrument_id: str):
    """
    Get funding rate data for a perpetual futures instrument.
    
    Returns current and historical funding information where available.
    """
    try:
        funding_data = await derivatives_manager.get_funding_data(instrument_id)
        
        # Enhance with historical data if available
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
            historical_funding = await derivatives_manager.get_historical_funding(
                instrument_id, start_date, end_date
            )
            funding_data = FundingAnalyticsService.enhance_funding_data(
                funding_data, historical_funding
            )
        except Exception:
            # Historical data not available, use current data only
            pass
        
        return funding_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/funding/{instrument_id}/history")
async def get_funding_history(
    instrument_id: str,
    start_date: date,
    end_date: date
):
    """Get historical funding rate data."""
    try:
        historical_funding = await derivatives_manager.get_historical_funding(
            instrument_id, start_date, end_date
        )
        
        # Add trend analysis
        trend_analysis = FundingAnalyticsService.analyze_funding_trend(historical_funding)
        
        return {
            "instrument_id": instrument_id,
            "data": historical_funding,
            "trend_analysis": trend_analysis,
            "count": len(historical_funding)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Open Interest Endpoints
# =============================================================================

@router.get("/open-interest/{instrument_id}", response_model=OpenInterestData)
async def get_open_interest(instrument_id: str):
    """
    Get open interest data for an instrument.
    
    Returns current and historical open interest where available.
    """
    try:
        oi_data = await derivatives_manager.get_open_interest(instrument_id)
        
        # Enhance with historical data if available
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
            historical_oi = await derivatives_manager.get_historical_open_interest(
                instrument_id, start_date, end_date
            )
            oi_data = OpenInterestAnalyticsService.enhance_oi_data(oi_data, historical_oi)
        except Exception:
            # Historical data not available, use current data only
            pass
        
        return oi_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/open-interest/{instrument_id}/history")
async def get_open_interest_history(
    instrument_id: str,
    start_date: date,
    end_date: date
):
    """Get historical open interest data."""
    try:
        historical_oi = await derivatives_manager.get_historical_open_interest(
            instrument_id, start_date, end_date
        )
        
        # Add trend analysis
        trend_analysis = OpenInterestAnalyticsService.analyze_oi_trend(historical_oi)
        
        return {
            "instrument_id": instrument_id,
            "data": historical_oi,
            "trend_analysis": trend_analysis,
            "count": len(historical_oi)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Analytics Endpoints
# =============================================================================

@router.get("/analytics/{instrument_id}", response_model=AdvancedAnalytics)
async def get_advanced_analytics(instrument_id: str, days: int = Query(30, ge=7, le=365)):
    """
    Get advanced analytics for an instrument.
    
    Returns statistical analysis using NumPy, Pandas, and SciPy.
    """
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        historical_data = await derivatives_manager.get_historical_data(
            instrument_id, start_date, end_date, "1d"
        )
        
        analytics = DerivativesAnalyticsService.calculate_advanced_analytics(historical_data)
        analytics.instrument_id = instrument_id
        
        return analytics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/risk/{instrument_id}", response_model=RiskMetrics)
async def get_risk_metrics(instrument_id: str, days: int = Query(90, ge=30, le=365)):
    """
    Get risk metrics for an instrument.
    
    Returns educational risk metrics without guaranteed profit claims.
    """
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        historical_data = await derivatives_manager.get_historical_data(
            instrument_id, start_date, end_date, "1d"
        )
        
        # Get current price
        quote = await derivatives_manager.get_quote(instrument_id)
        current_price = quote.last_price
        
        risk_metrics = RiskMetricsService.calculate_risk_metrics(
            historical_data, current_price
        )
        risk_metrics.instrument_id = instrument_id
        
        return risk_metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Paper Simulation Endpoints
# =============================================================================

@router.post("/simulation", response_model=PaperSimulationScenario)
async def create_simulation(request: PaperSimulationRequest, user_id: str = "anonymous"):
    """
    Create a paper/simulation scenario.
    
    Clearly labeled as PAPER SIMULATION - no real-money execution.
    """
    try:
        # Validate request
        is_valid, errors = PaperSimulationService.validate_simulation_request(request)
        if not is_valid:
            raise HTTPException(status_code=400, detail={"errors": errors})
        
        simulation = PaperSimulationService.create_simulation(request, user_id)
        simulation.id = str(uuid4())
        paper_scenarios[simulation.id] = simulation
        
        return simulation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulation/{simulation_id}/close")
async def close_simulation(simulation_id: str, exit_price: float = Query(..., gt=0)):
    """
    Close a paper simulation by setting exit price.
    """
    try:
        simulation = paper_scenarios.get(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=404, detail="Paper simulation not found")
        closed = PaperSimulationService.close_simulation(simulation, exit_price)
        paper_scenarios[simulation_id] = closed
        return closed
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulation/replay", response_model=HistoricalReplayResult)
async def historical_replay(request: HistoricalReplayRequest):
    """
    Perform historical replay simulation.
    
    Uses actual historical data for hypothetical price movement analysis.
    """
    try:
        historical_data = await derivatives_manager.get_historical_data(
            request.instrument_id, request.start_date, request.end_date, "1d"
        )
        
        result = await PaperSimulationService.historical_replay(request, historical_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, client_id: str = Query(...)):
    """
    WebSocket endpoint for real-time derivatives data streaming.
    
    Clients can subscribe to instrument updates and receive real-time quotes.
    """
    await derivatives_ws_manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            message_type = data.get("type")
            
            if message_type == "subscribe":
                instrument_id = data.get("instrument_id")
                if instrument_id:
                    await derivatives_ws_manager.subscribe_to_instrument(client_id, instrument_id)
                    if instrument_id not in quote_stream_tasks:
                        quote_stream_tasks[instrument_id] = asyncio.create_task(stream_instrument_quotes(instrument_id))
            
            elif message_type == "unsubscribe":
                instrument_id = data.get("instrument_id")
                if instrument_id:
                    await derivatives_ws_manager.unsubscribe_from_instrument(client_id, instrument_id)
            
            elif message_type == "ping":
                await derivatives_ws_manager.send_heartbeat(client_id)
            
            elif message_type == "get_subscriptions":
                subscriptions = derivatives_ws_manager.get_client_subscriptions(client_id)
                await derivatives_ws_manager.send_personal_message(client_id, {
                    "type": "subscriptions",
                    "subscriptions": list(subscriptions)
                })
            
    except WebSocketDisconnect:
        await derivatives_ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        await derivatives_ws_manager.disconnect(client_id)


# =============================================================================
# System Endpoints
# =============================================================================

@router.get("/system/health")
async def system_health():
    """Get derivatives system health status."""
    try:
        return {
            "status": "ok",
            "providers": derivatives_manager.provider_status(),
            "cache_stats": derivatives_manager.cache_stats(),
            "websocket_stats": derivatives_ws_manager.get_connection_stats(),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/system/cleanup")
async def system_cleanup():
    """Clean up expired cache entries and stale connections."""
    try:
        cache_removed = derivatives_manager.purge_expired_caches()
        await derivatives_ws_manager.cleanup_stale_connections()
        
        return {
            "status": "ok",
            "cache_entries_removed": cache_removed,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
