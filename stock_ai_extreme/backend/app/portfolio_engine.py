"""
Phase 9 — Professional Portfolio Calculation Engine

Advanced financial calculations for portfolio management including:
- FIFO, LIFO, and Weighted Average cost basis methods
- Realized and unrealized P&L with full accounting
- IRR (Internal Rate of Return) and XIRR (Irregular intervals)
- Sharpe Ratio, Sortino Ratio, Maximum Drawdown
- CAGR (Compound Annual Growth Rate)
- Risk-adjusted returns and volatility metrics
- Transaction cost tracking with fees
- Multi-currency support preparation
- Tax lot tracking for accurate gain/loss reporting

All calculations are based on actual transactions, never on assumed positions.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CORE DATA STRUCTURES
# ============================================================================

class Position:
    """Represents a current position in a security."""
    def __init__(self, symbol: str, quantity: float, average_cost: float, 
                 total_cost: float, realized_pnl: float = 0.0):
        self.symbol = symbol
        self.quantity = quantity  # Current shares held
        self.average_cost = average_cost  # Weighted average cost per share
        self.total_cost = total_cost  # Total invested (including fees)
        self.realized_pnl = realized_pnl  # Cumulative realized P&L from sells


class Transaction:
    """Transaction data structure for calculations."""
    def __init__(self, symbol: str, tx_type: str, quantity: float, price: float, 
                 fees: float, date: datetime, tx_id: Optional[int] = None):
        self.symbol = symbol
        self.type = tx_type.upper()  # BUY or SELL
        self.quantity = quantity
        self.price = price
        self.fees = fees
        self.date = date
        self.id = tx_id
        
        # Calculate total amount
        if self.type == "BUY":
            self.total_amount = (quantity * price) + fees
        elif self.type == "SELL":
            self.total_amount = (quantity * price) - fees
        else:
            raise ValueError(f"Invalid transaction type: {tx_type}")


# ============================================================================
# POSITION CALCULATION (FIFO/LIFO/WEIGHTED AVERAGE)
# ============================================================================

def calculate_positions_fifo(transactions: List[dict]) -> Dict[str, Position]:
    """
    Calculate current positions using FIFO (First In, First Out) method.
    
    This is the most common method for tax reporting. Shares bought first
    are considered sold first when calculating realized gains.
    
    Args:
        transactions: List of transaction dicts with symbol, type, quantity, price, fees, date
        
    Returns:
        Dict mapping symbol to Position object
    """
    positions: Dict[str, Position] = {}
    # Track lots for each symbol (for FIFO calculation)
    lots: Dict[str, List[Tuple[float, float, float]]] = defaultdict(list)  # [(quantity, cost_per_share_incl_fees, fees_per_share), ...]
    # Phase 9 fix: realized P&L is accumulated per symbol across every SELL and
    # carried into the final Position. The previous code computed it inside the
    # loop and then discarded it ("simplified here"), so realized P&L was
    # always reported as 0.00 — a genuine accounting bug.
    realized_by_symbol: Dict[str, float] = defaultdict(float)

    # Sort transactions by date, then by id for a stable order on same-day txs.
    # (If two transactions share a timestamp, insertion order — the
    # autoincrement id — is the only honest tiebreaker; without it FIFO lot
    # selection is nondeterministic across runs.)
    sorted_txs = sorted(
        transactions,
        key=lambda t: (t['transaction_date'], t.get('id') or 0),
    )

    for tx_dict in sorted_txs:
        symbol = str(tx_dict['symbol']).upper()
        tx_type = str(tx_dict['transaction_type']).upper()
        quantity = float(tx_dict['quantity'])
        price = float(tx_dict['price'])
        fees = float(tx_dict.get('fees', 0.0) or 0.0)

        if tx_type == 'BUY':
            # Add to lots
            fees_per_share = fees / quantity if quantity > 0 else 0
            lots[symbol].append((quantity, price + fees_per_share, fees_per_share))

        elif tx_type == 'SELL':
            # Remove from lots using FIFO
            remaining_to_sell = quantity
            # NaN-safe division: quantity==0 previously raised ZeroDivisionError
            fees_per_share = fees / quantity if quantity > 0 else 0
            # Fees on a SELL reduce this sale's realized proceeds.
            sale_fees_per_share = fees_per_share

            while remaining_to_sell > 0 and lots[symbol]:
                lot_qty, lot_cost, _ = lots[symbol][0]

                if lot_qty <= remaining_to_sell:
                    # Sell entire lot
                    realized_by_symbol[symbol] += (price - lot_cost) * lot_qty - (sale_fees_per_share * lot_qty)
                    remaining_to_sell -= lot_qty
                    lots[symbol].pop(0)
                else:
                    # Partial lot sale
                    realized_by_symbol[symbol] += (price - lot_cost) * remaining_to_sell - (sale_fees_per_share * remaining_to_sell)
                    lots[symbol][0] = (lot_qty - remaining_to_sell, lot_cost, 0)
                    remaining_to_sell = 0

            if remaining_to_sell > 0:
                # Phase 9 hardening: never invent a short position. The engine
                # clamps to what was actually held; the caller (route layer)
                # validates BEFORE writing, so reaching this line means data
                # was edited behind the engine's back — warn and move on.
                logger.warning(
                    "SELL for %s exceeds available shares by %s — clamped to holdings "
                    "(short selling is not supported).",
                    symbol, remaining_to_sell,
                )

    # Calculate final positions
    for symbol, symbol_lots in lots.items():
        if not symbol_lots:
            continue

        total_quantity = sum(lot[0] for lot in symbol_lots)
        total_cost = sum(lot[0] * lot[1] for lot in symbol_lots)
        average_cost = total_cost / total_quantity if total_quantity > 0 else 0

        positions[symbol] = Position(
            symbol=symbol,
            quantity=total_quantity,
            average_cost=average_cost,
            total_cost=total_cost,
            realized_pnl=round(realized_by_symbol.get(symbol, 0.0), 2),
        )

    return positions


def _lot_avg_cost(lots_list: List[Tuple[float, float, float]]) -> float:
    """Average cost per share across the remaining lots of one symbol.
    Used only for diagnostics when a SELL exceeds holdings."""
    total_qty = sum(l[0] for l in lots_list)
    if total_qty <= 0:
        return 0.0
    return sum(l[0] * l[1] for l in lots_list) / total_qty


def calculate_positions_weighted_average(transactions: List[dict]) -> Dict[str, Position]:
    """
    Calculate current positions using Weighted Average Cost method.
    
    This method averages the cost of all purchases. Simpler than FIFO/LIFO
    but may not match tax reporting requirements in some jurisdictions.
    
    Args:
        transactions: List of transaction dicts
        
    Returns:
        Dict mapping symbol to Position object
    """
    positions: Dict[str, Dict] = defaultdict(lambda: {
        'total_quantity': 0.0,
        'total_cost': 0.0,
        'realized_pnl': 0.0
    })
    
    # Sort transactions by date (then id — same stable tiebreaker as FIFO)
    sorted_txs = sorted(
        transactions,
        key=lambda t: (t['transaction_date'], t.get('id') or 0),
    )

    for tx_dict in sorted_txs:
        symbol = str(tx_dict['symbol']).upper()
        tx_type = str(tx_dict['transaction_type']).upper()
        quantity = float(tx_dict['quantity'])
        price = float(tx_dict['price'])
        fees = float(tx_dict.get('fees', 0.0) or 0.0)

        pos = positions[symbol]

        if tx_type == 'BUY':
            # Add to position
            pos['total_cost'] += (quantity * price) + fees
            pos['total_quantity'] += quantity

        elif tx_type == 'SELL':
            if pos['total_quantity'] <= 0:
                logger.warning("SELL for %s with no holdings — transaction ignored.", symbol)
                continue

            # Phase 9 hardening: never allow a negative holding. If the sell is
            # larger than the position, clamp to what is held, apply the sell
            # only for the clamped quantity, and report it — the numbers shown
            # stay internally consistent instead of inventing a short position.
            sell_qty = min(quantity, pos['total_quantity'])
            if sell_qty < quantity:
                logger.warning(
                    "SELL for %s exceeds available shares (%s held, %s requested) — "
                    "clamped to holdings (short selling is not supported).",
                    symbol, pos['total_quantity'], quantity,
                )

            # Calculate average cost at time of sale
            avg_cost = pos['total_cost'] / pos['total_quantity'] if pos['total_quantity'] > 0 else 0

            # Calculate realized P&L
            sale_proceeds = (sell_qty * price) - fees
            sale_cost = sell_qty * avg_cost
            realized_pnl = sale_proceeds - sale_cost

            pos['realized_pnl'] += realized_pnl
            pos['total_cost'] -= sale_cost
            pos['total_quantity'] -= sell_qty

            # Guard against float drift producing a -1e-9 quantity
            if abs(pos['total_quantity']) < 1e-9:
                pos['total_quantity'] = 0.0
                pos['total_cost'] = 0.0

    # Convert to Position objects (only open positions remain)
    result = {}
    for symbol, pos_data in positions.items():
        if pos_data['total_quantity'] > 0:
            avg_cost = pos['total_cost'] / pos_data['total_quantity']
            result[symbol] = Position(
                symbol=symbol,
                quantity=pos_data['total_quantity'],
                average_cost=avg_cost,
                total_cost=pos_data['total_cost'],
                realized_pnl=round(pos_data['realized_pnl'], 2),
            )

    return result


# ============================================================================
# P&L CALCULATIONS
# ============================================================================

def calculate_unrealized_pnl(position: Position, current_price: float) -> Tuple[float, float]:
    """
    Calculate unrealized P&L for a position.
    
    Args:
        position: Position object
        current_price: Current market price
        
    Returns:
        Tuple of (unrealized_pnl_amount, unrealized_pnl_percent)
    """
    if position.quantity <= 0:
        return 0.0, 0.0
    
    current_value = position.quantity * current_price
    unrealized_pnl = current_value - position.total_cost
    unrealized_pnl_pct = (unrealized_pnl / position.total_cost * 100) if position.total_cost > 0 else 0.0
    
    return round(unrealized_pnl, 2), round(unrealized_pnl_pct, 2)


def calculate_total_return(position: Position, current_price: float) -> Tuple[float, float]:
    """
    Calculate total return including both realized and unrealized P&L.
    
    Args:
        position: Position object
        current_price: Current market price
        
    Returns:
        Tuple of (total_return_amount, total_return_percent)
    """
    unrealized_pnl, _ = calculate_unrealized_pnl(position, current_price)
    total_return = position.realized_pnl + unrealized_pnl
    
    # Calculate percentage based on total capital deployed
    # This includes both current investment and capital from realized gains
    total_invested = position.total_cost + abs(min(0, position.realized_pnl))
    total_return_pct = (total_return / total_invested * 100) if total_invested > 0 else 0.0
    
    return round(total_return, 2), round(total_return_pct, 2)


# ============================================================================
# PORTFOLIO-LEVEL METRICS
# ============================================================================

def calculate_portfolio_summary(positions: Dict[str, Position], 
                                current_prices: Dict[str, float]) -> dict:
    """
    Calculate comprehensive portfolio summary with all metrics.
    
    Args:
        positions: Dict of symbol to Position
        current_prices: Dict of symbol to current price
        
    Returns:
        Dict with portfolio summary metrics
    """
    total_cost_basis = 0.0
    total_market_value = 0.0
    total_realized_pnl = 0.0
    total_unrealized_pnl = 0.0
    total_invested_all_time = 0.0
    
    enriched_positions = []
    unavailable_symbols: List[str] = []
    
    for symbol, position in positions.items():
        current_price = current_prices.get(symbol)
        
        if current_price is None or (isinstance(current_price, float) and math.isnan(current_price)):
            # Phase 9 spec I: a position without a live price is REPORTED, not
            # silently skipped and not priced at a stale/fake value.
            unavailable_symbols.append(symbol)
            enriched_positions.append({
                'symbol': symbol,
                'quantity': round(position.quantity, 4),
                'average_cost': round(position.average_cost, 2),
                'total_cost': round(position.total_cost, 2),
                'current_price': None,
                'market_value': None,
                'unrealized_pnl': None,
                'unrealized_pnl_pct': None,
                'realized_pnl': round(position.realized_pnl, 2),
                'total_return': round(position.realized_pnl, 2),
                'allocation_pct': None,
                'price_available': False,
            })
            total_realized_pnl += position.realized_pnl
            total_invested_all_time += position.total_cost
            continue
        
        unrealized_pnl, unrealized_pnl_pct = calculate_unrealized_pnl(position, current_price)
        market_value = position.quantity * current_price
        
        total_cost_basis += position.total_cost
        total_market_value += market_value
        total_realized_pnl += position.realized_pnl
        total_unrealized_pnl += unrealized_pnl
        total_invested_all_time += position.total_cost
        
        enriched_positions.append({
            'symbol': symbol,
            'quantity': round(position.quantity, 4),
            'average_cost': round(position.average_cost, 2),
            'total_cost': round(position.total_cost, 2),
            'current_price': round(current_price, 2),
            'market_value': round(market_value, 2),
            'unrealized_pnl': round(unrealized_pnl, 2),
            'unrealized_pnl_pct': round(unrealized_pnl_pct, 2),
            'realized_pnl': round(position.realized_pnl, 2),
            'total_return': round(unrealized_pnl + position.realized_pnl, 2),
            'allocation_pct': 0.0,  # filled after totals
            'price_available': True,
        })
    
    # Calculate allocation percentages (priced positions only — an unpriced
    # position cannot honestly claim a share of a value we can't compute)
    for pos in enriched_positions:
        if pos['price_available'] and total_market_value > 0:
            pos['allocation_pct'] = round((pos['market_value'] / total_market_value) * 100, 2)
    
    # Calculate portfolio-level metrics
    total_pnl = total_realized_pnl + total_unrealized_pnl
    total_return_pct = (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0
    
    return {
        'positions': enriched_positions,
        'summary': {
            'num_positions': len(enriched_positions),
            'num_priced_positions': len(enriched_positions) - len(unavailable_symbols),
            'unavailable_symbols': unavailable_symbols,
            'total_cost_basis': round(total_cost_basis, 2),
            'total_market_value': round(total_market_value, 2),
            'total_realized_pnl': round(total_realized_pnl, 2),
            'total_unrealized_pnl': round(total_unrealized_pnl, 2),
            'total_pnl': round(total_pnl, 2),
            'total_return_pct': round(total_return_pct, 2),
        }
    }


# ============================================================================
# ADVANCED FINANCIAL METRICS
# ============================================================================

def calculate_irr(cash_flows: List[Tuple[datetime, float]], final_value: float, 
                 final_date: datetime) -> Optional[float]:
    """
    Calculate Internal Rate of Return (IRR) using Newton-Raphson method.
    
    IRR is the discount rate that makes NPV = 0.
    
    Args:
        cash_flows: List of (date, amount) tuples. Negative = investment, positive = return
        final_value: Current portfolio value
        final_date: Current date
        
    Returns:
        IRR as a decimal (e.g., 0.15 for 15%) or None if cannot converge
    """
    if not cash_flows:
        return None
    
    # Add final value as the last cash flow
    all_flows = cash_flows + [(final_date, final_value)]
    
    # Calculate days from first cash flow
    start_date = min(cf[0] for cf in all_flows)
    periods = [(cf[0] - start_date).days / 365.25 for cf in all_flows]  # Years
    amounts = [cf[1] for cf in all_flows]
    
    # Newton-Raphson method to find IRR
    guess = 0.1  # Start with 10% guess
    tolerance = 0.0001
    max_iterations = 100
    
    for _ in range(max_iterations):
        npv = sum(amt / ((1 + guess) ** period) for amt, period in zip(amounts, periods))
        
        if abs(npv) < tolerance:
            return round(guess * 100, 2)  # Return as percentage
        
        # Calculate derivative for Newton-Raphson
        d_npv = sum(-period * amt / ((1 + guess) ** (period + 1)) for amt, period in zip(amounts, periods))
        
        if abs(d_npv) < 1e-10:
            break
        
        guess = guess - npv / d_npv
        
        # Prevent negative or unreasonable rates
        if guess < -0.99 or guess > 10:
            break
    
    return None  # Could not converge


def calculate_cagr(initial_value: float, final_value: float, years: float) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate.
    
    CAGR = (Final Value / Initial Value) ^ (1 / Years) - 1
    
    Args:
        initial_value: Starting portfolio value
        final_value: Ending portfolio value
        years: Time period in years
        
    Returns:
        CAGR as percentage or None if invalid
    """
    if initial_value <= 0 or years <= 0:
        return None
    
    cagr = (math.pow(final_value / initial_value, 1 / years) - 1) * 100
    return round(cagr, 2)


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.02) -> Optional[float]:
    """
    Calculate Sharpe Ratio (risk-adjusted return).
    
    Sharpe Ratio = (Mean Return - Risk Free Rate) / Standard Deviation
    
    Args:
        returns: List of period returns (as decimals)
        risk_free_rate: Annual risk-free rate (default 2%)
        
    Returns:
        Sharpe ratio or None if insufficient data
    """
    if len(returns) < 2:
        return None
    
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    
    if std_dev == 0:
        return None
    
    # Annualize assuming daily returns
    annual_return = mean_return * 252  # Trading days
    annual_std = std_dev * math.sqrt(252)
    
    sharpe = (annual_return - risk_free_rate) / annual_std
    return round(sharpe, 2)


def calculate_max_drawdown(portfolio_values: List[float]) -> Tuple[float, int, int]:
    """
    Calculate maximum drawdown (largest peak-to-trough decline).
    
    Args:
        portfolio_values: List of portfolio values over time
        
    Returns:
        Tuple of (max_drawdown_pct, peak_index, trough_index)
    """
    if len(portfolio_values) < 2:
        return 0.0, 0, 0
    
    max_dd = 0.0
    peak = portfolio_values[0]
    peak_idx = 0
    trough_idx = 0
    
    for i, value in enumerate(portfolio_values):
        if value > peak:
            peak = value
            peak_idx = i
        
        dd = (peak - value) / peak if peak > 0 else 0
        
        if dd > max_dd:
            max_dd = dd
            trough_idx = i
    
    return round(max_dd * 100, 2), peak_idx, trough_idx


# ============================================================================
# VALIDATION
# ============================================================================

def validate_transaction(symbol: str, tx_type: str, quantity: float, price: float,
                        fees: float, current_position: Optional[Position] = None,
                        tx_date: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Validate a transaction before processing.
    
    Args:
        symbol: Stock symbol
        tx_type: BUY or SELL
        quantity: Number of shares
        price: Price per share
        fees: Transaction fees
        current_position: Current position for SELL validation
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Basic validation
    if not symbol or not symbol.strip():
        return False, "Symbol cannot be empty"
    
    tx_type = tx_type.upper()
    if tx_type not in ['BUY', 'SELL']:
        return False, f"Invalid transaction type: {tx_type}. Must be BUY or SELL"
    
    if quantity <= 0:
        return False, "Quantity must be positive"
    
    if price <= 0:
        return False, "Price must be positive"
    
    if fees < 0:
        return False, "Fees cannot be negative"
    
    # Phase 9: reject NaN/Infinity prices and quantities explicitly — they pass
    # naive `<= 0` comparisons and would poison every downstream calculation.
    for name, value in (("Quantity", quantity), ("Price", price), ("Fees", fees)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return False, f"{name} must be a finite number"

    # Phase 9: reject future-dated transactions. A BUY dated tomorrow would let
    # P&L be computed on a price that has not happened yet. A missing date is
    # also invalid (spec N: "Invalid date") — every transaction needs one.
    if tx_date is None:
        return False, "Transaction date is required"
    now_utc = datetime.now(timezone.utc)
    compare = tx_date if tx_date.tzinfo else tx_date.replace(tzinfo=timezone.utc)
    if compare > now_utc + timedelta(minutes=5):
        return False, "Transaction date cannot be in the future"

    # SELL-specific validation
    if tx_type == 'SELL':
        if current_position is None:
            return False, f"No position exists for {symbol}"
        
        if current_position.quantity < quantity:
            return False, f"Insufficient shares. Have {current_position.quantity}, trying to sell {quantity}"
    
    return True, ""


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def format_currency(amount: float, currency: str = "PKR") -> str:
    """Format currency with proper separators."""
    return f"{currency} {amount:,.2f}"


def format_percentage(pct: float, show_sign: bool = True) -> str:
    """Format percentage with sign."""
    sign = "+" if pct > 0 and show_sign else ""
    return f"{sign}{pct:.2f}%"
