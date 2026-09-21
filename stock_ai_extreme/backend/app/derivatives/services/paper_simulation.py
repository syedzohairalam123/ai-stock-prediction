"""
Paper simulation service for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine

This module provides non-monetary paper/simulation trading functionality for educational purposes.
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import logging
import pandas as pd

from ..schemas import (
    PaperSimulationScenario, PaperSimulationRequest, PaperSimulationUpdate,
    HistoricalReplayRequest, HistoricalReplayResult
)

logger = logging.getLogger("neural_market.derivatives.services.paper_simulation")


class PaperSimulationService:
    """
    Service for paper/simulation trading scenarios.
    
    Provides:
    - Hypothetical scenario creation
    - P/L calculation
    - Historical replay
    - Scenario management
    
    Clearly labeled as PAPER SIMULATION - no real-money execution.
    """
    
    @staticmethod
    def create_simulation(request: PaperSimulationRequest, user_id: str = "anonymous") -> PaperSimulationScenario:
        """
        Create a new paper simulation scenario.
        
        Args:
            request: Simulation request data
            user_id: User identifier (default anonymous)
            
        Returns:
            PaperSimulationScenario object
        """
        try:
            now = datetime.utcnow()
            
            simulation = PaperSimulationScenario(
                id=None,  # Will be assigned by database
                user_id=user_id,
                instrument_id=request.instrument_id,
                scenario_name=request.scenario_name,
                direction=request.direction,
                entry_price=request.entry_price,
                exit_price=None,
                quantity=request.quantity,
                leverage=request.leverage,
                entry_timestamp=now,
                exit_timestamp=None,
                gross_pnl=None,
                gross_pnl_percent=None,
                status="ACTIVE",
                notes=request.notes,
                created_at=now,
                updated_at=now
            )
            
            logger.info(f"Created paper simulation: {request.scenario_name} for {request.instrument_id}")
            return simulation
            
        except Exception as e:
            logger.error(f"Error creating paper simulation: {e}")
            raise
    
    @staticmethod
    def calculate_pnl(simulation: PaperSimulationScenario, current_price: float) -> Dict[str, Any]:
        """
        Calculate hypothetical P/L for a simulation.
        
        Args:
            simulation: Paper simulation object
            current_price: Current market price
            
        Returns:
            Dictionary with P/L calculations
        """
        try:
            if simulation.status != "ACTIVE":
                return {
                    "gross_pnl": simulation.gross_pnl,
                    "gross_pnl_percent": simulation.gross_pnl_percent,
                    "unrealized_pnl": 0,
                    "unrealized_pnl_percent": 0,
                    "status": simulation.status
                }
            
            # Calculate position value
            position_value = simulation.quantity * current_price
            
            # Calculate P/L based on direction
            if simulation.direction == "LONG":
                price_change = current_price - simulation.entry_price
                gross_pnl = price_change * simulation.quantity
            else:  # SHORT
                price_change = simulation.entry_price - current_price
                gross_pnl = price_change * simulation.quantity
            
            # Calculate P/L percentage
            entry_value = simulation.quantity * simulation.entry_price
            gross_pnl_percent = (gross_pnl / entry_value) * 100 if entry_value != 0 else 0
            
            # Apply leverage for educational display (not real leverage)
            leveraged_pnl = gross_pnl * simulation.leverage
            leveraged_pnl_percent = gross_pnl_percent * simulation.leverage
            
            return {
                "gross_pnl": float(gross_pnl),
                "gross_pnl_percent": float(gross_pnl_percent),
                "unrealized_pnl": float(gross_pnl),
                "unrealized_pnl_percent": float(gross_pnl_percent),
                "leveraged_pnl": float(leveraged_pnl),
                "leveraged_pnl_percent": float(leveraged_pnl_percent),
                "position_value": float(position_value),
                "entry_value": float(entry_value),
                "current_price": float(current_price),
                "disclaimer": "PAPER SIMULATION - Not real trading"
            }
            
        except Exception as e:
            logger.error(f"Error calculating P/L: {e}")
            return {
                "gross_pnl": None,
                "gross_pnl_percent": None,
                "unrealized_pnl": None,
                "unrealized_pnl_percent": None,
                "error": str(e)
            }
    
    @staticmethod
    def close_simulation(simulation: PaperSimulationScenario, exit_price: float) -> PaperSimulationScenario:
        """
        Close a paper simulation by setting exit price.
        
        Args:
            simulation: Paper simulation to close
            exit_price: Exit price for the simulation
            
        Returns:
            Updated PaperSimulation object
        """
        try:
            # Calculate final P/L
            pnl_result = PaperSimulationService.calculate_pnl(simulation, exit_price)
            
            simulation.exit_price = exit_price
            simulation.exit_timestamp = datetime.utcnow()
            simulation.gross_pnl = pnl_result.get("gross_pnl")
            simulation.gross_pnl_percent = pnl_result.get("gross_pnl_percent")
            simulation.status = "CLOSED"
            simulation.updated_at = datetime.utcnow()
            
            logger.info(f"Closed paper simulation: {simulation.scenario_name} with P/L: {simulation.gross_pnl}")
            return simulation
            
        except Exception as e:
            logger.error(f"Error closing simulation: {e}")
            raise
    
    @staticmethod
    async def historical_replay(request: HistoricalReplayRequest, 
                               historical_data: List[Dict[str, Any]]) -> HistoricalReplayResult:
        """
        Perform historical replay simulation.
        
        Args:
            request: Historical replay request
            historical_data: Historical price data
            
        Returns:
            HistoricalReplayResult with simulation results
        """
        try:
            if not historical_data:
                raise ValueError("No historical data provided for replay")
            
            # Convert to DataFrame
            df = pd.DataFrame(historical_data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp')
            
            # Get price column
            if 'close' in df.columns:
                price_col = 'close'
            elif 'last_price' in df.columns:
                price_col = 'last_price'
            else:
                raise ValueError("No price column found in historical data")
            
            # Find entry and exit points
            entry_price = request.entry_price
            entry_timestamp = None
            exit_price = None
            exit_timestamp = None
            
            # Find closest entry point
            entry_diff = (df[price_col] - entry_price).abs()
            entry_idx = entry_diff.idxmin()
            entry_timestamp = df.loc[entry_idx, 'timestamp']
            
            # Use last data point as exit
            exit_idx = len(df) - 1
            exit_price = df.loc[exit_idx, price_col]
            exit_timestamp = df.loc[exit_idx, 'timestamp']
            
            # Calculate price movement
            if request.direction == "LONG":
                price_movement = exit_price - entry_price
            else:  # SHORT
                price_movement = entry_price - exit_price
            
            # Calculate hypothetical result
            entry_value = request.quantity * entry_price
            hypothetical_result = price_movement * request.quantity
            hypothetical_result_percent = (hypothetical_result / entry_value) * 100 if entry_value != 0 else 0
            
            # Apply leverage for educational display
            leveraged_result = hypothetical_result * request.leverage
            leveraged_result_percent = hypothetical_result_percent * request.leverage
            
            # Calculate max drawdown and max profit during the period
            running_pnl = []
            for i in range(entry_idx, len(df)):
                current_price = df.loc[i, price_col]
                if request.direction == "LONG":
                    pnl = (current_price - entry_price) * request.quantity
                else:
                    pnl = (entry_price - current_price) * request.quantity
                running_pnl.append(pnl)
            
            max_profit = max(running_pnl) if running_pnl else 0
            max_drawdown = min(running_pnl) if running_pnl else 0
            
            return HistoricalReplayResult(
                instrument_id=request.instrument_id,
                entry_reference=entry_price,
                exit_reference=exit_price,
                price_movement=float(price_movement),
                hypothetical_result=float(hypothetical_result),
                hypothetical_result_percent=float(hypothetical_result_percent),
                max_drawdown=float(max_drawdown),
                max_profit=float(max_profit),
                data_points=len(df) - entry_idx,
                disclaimer="Paper simulation only - not investment advice"
            )
            
        except Exception as e:
            logger.error(f"Error in historical replay: {e}")
            raise
    
    @staticmethod
    def calculate_scenario_metrics(simulations: List[PaperSimulationScenario]) -> Dict[str, Any]:
        """
        Calculate aggregate metrics for multiple simulations.
        
        Args:
            simulations: List of paper simulations
            
        Returns:
            Dictionary with aggregate metrics
        """
        try:
            if not simulations:
                return {
                    "total_simulations": 0,
                    "active_simulations": 0,
                    "closed_simulations": 0,
                    "total_pnl": 0,
                    "win_rate": 0,
                    "average_pnl": 0,
                    "max_profit": 0,
                    "max_loss": 0
                }
            
            closed_sims = [s for s in simulations if s.status == "CLOSED"]
            active_sims = [s for s in simulations if s.status == "ACTIVE"]
            
            total_pnl = sum(s.gross_pnl or 0 for s in closed_sims)
            winning_sims = [s for s in closed_sims if s.gross_pnl and s.gross_pnl > 0]
            
            win_rate = len(winning_sims) / len(closed_sims) if closed_sims else 0
            average_pnl = total_pnl / len(closed_sims) if closed_sims else 0
            
            pnls = [s.gross_pnl for s in closed_sims if s.gross_pnl is not None]
            max_profit = max(pnls) if pnls else 0
            max_loss = min(pnls) if pnls else 0
            
            return {
                "total_simulations": len(simulations),
                "active_simulations": len(active_sims),
                "closed_simulations": len(closed_sims),
                "total_pnl": float(total_pnl),
                "win_rate": float(win_rate),
                "average_pnl": float(average_pnl),
                "max_profit": float(max_profit),
                "max_loss": float(max_loss),
                "disclaimer": "PAPER SIMULATION - Not real trading"
            }
            
        except Exception as e:
            logger.error(f"Error calculating scenario metrics: {e}")
            return {
                "total_simulations": 0,
                "active_simulations": 0,
                "closed_simulations": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "average_pnl": 0,
                "max_profit": 0,
                "max_loss": 0,
                "error": str(e)
            }
    
    @staticmethod
    def validate_simulation_request(request: PaperSimulationRequest) -> tuple[bool, List[str]]:
        """
        Validate a paper simulation request.
        
        Args:
            request: Simulation request to validate
            
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        if not request.instrument_id:
            errors.append("Instrument ID is required")
        
        if not request.scenario_name:
            errors.append("Scenario name is required")
        
        if request.direction not in ["LONG", "SHORT"]:
            errors.append("Direction must be LONG or SHORT")
        
        if request.entry_price <= 0:
            errors.append("Entry price must be positive")
        
        if request.quantity <= 0:
            errors.append("Quantity must be positive")
        
        if request.leverage <= 0:
            errors.append("Leverage must be positive")
        
        if request.leverage > 100:
            errors.append("Leverage cannot exceed 100x for educational purposes")
        
        return len(errors) == 0, errors
