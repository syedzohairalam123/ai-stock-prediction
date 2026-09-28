"""
Phase 20 — reusable paper P&L / condition maths.

Every function here is pure: numbers in, numbers out, no I/O, no database, no
network. That makes the arithmetic the one part of the simulation that can be
verified exactly, which matters because this is the number a user reads.

Two hard rules the whole module obeys:

1. **Never fabricate an exit price.** If a real observed price is not supplied,
   the result is `None` and the caller reports "not enough data" — it is not
   filled in with the reference price or a guess.
2. **Never emit NaN/Infinity.** Non-finite inputs are rejected at the door by
   returning `None`, so a bad provider value cannot propagate into the UI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

from .instruments import ORDER_TYPES, QuoteMode

#: Sides that profit when the reference value rises.
_LONG_SIDES = frozenset({"BUY", "YES"})
#: Sides that profit when the reference value falls.
_SHORT_SIDES = frozenset({"SELL", "NO"})


def is_finite_number(value: object) -> bool:
    """True only for a real, finite number. Rejects bool/NaN/Inf/strings."""
    if isinstance(value, bool) or value is None:
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def finite_or_none(value: object) -> Optional[float]:
    """Coerce to a finite float or None — the single NaN/Infinity gate."""
    if not is_finite_number(value):
        return None
    return float(value)


def position_notional(quantity: float, price: float) -> Optional[float]:
    """Estimated notional = quantity × reference price."""
    if not (is_finite_number(quantity) and is_finite_number(price)):
        return None
    out = float(quantity) * float(price)
    return out if math.isfinite(out) else None


def quantity_from_notional(amount: float, price: float) -> Optional[float]:
    """Quantity implied by a notional amount at a reference price."""
    if not (is_finite_number(amount) and is_finite_number(price)):
        return None
    if float(price) <= 0 or float(amount) <= 0:
        return None
    qty = float(amount) / float(price)
    return qty if math.isfinite(qty) else None


def notional_from_quantity(quantity: float, price: float) -> Optional[float]:
    """Alias kept explicit so call sites read the intent, not the direction."""
    return position_notional(quantity, price)


def price_difference(side: str, entry: float, exit_price: float, quote_mode: QuoteMode = QuoteMode.PRICE) -> Optional[float]:
    """Signed price move in the direction the side actually profits from.

    BUY/YES profit from a rise, SELL/NO from a fall. For a forecast event the
    units are percentage points of probability, which is why `quote_mode` is
    carried through rather than assumed.
    """
    if not (is_finite_number(entry) and is_finite_number(exit_price)):
        return None
    side = (side or "").upper()
    if side in _LONG_SIDES:
        return float(exit_price) - float(entry)
    if side in _SHORT_SIDES:
        return float(entry) - float(exit_price)
    return None


@dataclass(frozen=True)
class PaperPnl:
    """A hypothetical (never real) profit/loss result."""

    side: str
    entry_reference: float
    exit_reference: float
    price_difference: float
    quantity: float
    hypothetical_pnl: float
    hypothetical_pnl_percent: Optional[float]
    unit: str  # "PRICE" | "PERCENTAGE_POINTS"

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "entryReference": self.entry_reference,
            "exitReference": self.exit_reference,
            "priceDifference": round(self.price_difference, 8),
            "quantity": self.quantity,
            "hypotheticalPnl": round(self.hypothetical_pnl, 6),
            "hypotheticalPnlPercent": (
                None if self.hypothetical_pnl_percent is None
                else round(self.hypothetical_pnl_percent, 4)
            ),
            "unit": self.unit,
            "paper": True,
            "disclaimer": "Hypothetical simulation result — not a real trade, order or payout.",
        }


def compute_pnl(
    side: str,
    entry_reference: float,
    exit_reference: float,
    quantity: float,
    quote_mode: QuoteMode = QuoteMode.PRICE,
) -> Optional[PaperPnl]:
    """Hypothetical P&L for a completed simulation.

    Returns `None` when any input is not a real number or the quantity is
    non-positive — the caller then reports "not enough data" rather than
    showing a fabricated figure.
    """
    if quote_mode is QuoteMode.PROBABILITY:
        # A forecast selection is informational: the "position" is the
        # probability of the chosen outcome, so a 100-unit notional keeps the
        # arithmetic readable without pretending anyone wagered anything.
        quantity = 100.0 if not is_finite_number(quantity) else float(quantity)
    if not (is_finite_number(entry_reference) and is_finite_number(exit_reference)):
        return None
    if not is_finite_number(quantity) or float(quantity) <= 0:
        return None

    diff = price_difference(side, entry_reference, exit_reference, quote_mode)
    if diff is None:
        return None

    pnl = diff * float(quantity)
    if not math.isfinite(pnl):
        return None

    if quote_mode is QuoteMode.PROBABILITY:
        # Percentage points, reported in the same units as the probability
        # itself. There is no monetary return to compute, and inventing one
        # would be exactly the wagering mechanic this phase forbids.
        return PaperPnl(
            side=(side or "").upper(),
            entry_reference=float(entry_reference),
            exit_reference=float(exit_reference),
            price_difference=diff,
            quantity=float(quantity),
            hypothetical_pnl=pnl,
            hypothetical_pnl_percent=None,
            unit="PERCENTAGE_POINTS",
        )

    entry_value = float(entry_reference) * float(quantity)
    pct = (pnl / entry_value * 100.0) if entry_value else None
    if pct is not None and not math.isfinite(pct):
        pct = None
    return PaperPnl(
        side=(side or "").upper(),
        entry_reference=float(entry_reference),
        exit_reference=float(exit_reference),
        price_difference=diff,
        quantity=float(quantity),
        hypothetical_pnl=pnl,
        hypothetical_pnl_percent=pct,
        unit="PRICE",
    )


def limit_condition_met(
    side: str,
    limit_price: float,
    *,
    observed_low: Optional[float] = None,
    observed_high: Optional[float] = None,
    observed_close: Optional[float] = None,
) -> Optional[bool]:
    """Would a hypothetical LIMIT order have filled?

    * BUY  fills when the market traded **at or below** the limit → uses the
      period's LOW.
    * SELL fills when the market traded **at or above** the limit → uses the
      period's HIGH.
    * YES/NO (forecast) fill when the traded probability reached the limit
      level in the favourable direction, using the observed close as the
      available reference.

    Returns `True` / `False`, or `None` when there is genuinely no observation
    to judge against (the honest "not yet determinable" answer — it is never
    coerced to False, because "unknown" and "did not fill" are different).
    """
    if not is_finite_number(limit_price) or float(limit_price) <= 0:
        return None
    side = (side or "").upper()
    limit = float(limit_price)

    if side in _LONG_SIDES:
        low = finite_or_none(observed_low)
        if low is None:
            low = finite_or_none(observed_close)
        if low is None:
            return None
        return low <= limit

    if side in _SHORT_SIDES:
        high = finite_or_none(observed_high)
        if high is None:
            high = finite_or_none(observed_close)
        if high is None:
            return None
        return high >= limit

    return None


def evaluate_limit_fill(
    side: str,
    limit_price: float,
    observations: Iterable[dict],
) -> Optional[dict]:
    """First real observation that would have satisfied a hypothetical limit.

    `observations` is an ordered iterable of `{timestamp, low, high, close}`
    rows taken *after* the simulation was submitted. Returns the matching
    observation plus the inferred fill reference (the limit price itself, which
    is what a limit order fills at or better), or `None` when nothing matched.
    """
    for row in observations:
        met = limit_condition_met(
            side,
            limit_price,
            observed_low=row.get("low"),
            observed_high=row.get("high"),
            observed_close=row.get("close"),
        )
        if met:
            return {
                "timestamp": row.get("timestamp"),
                "observedLow": finite_or_none(row.get("low")),
                "observedHigh": finite_or_none(row.get("high")),
                "observedClose": finite_or_none(row.get("close")),
                "fillReference": float(limit_price),
                "reason": "A real subsequent observation reached the limit level.",
            }
    return None


def summarize_paper_activity(orders: Iterable[dict]) -> dict:
    """Aggregate stats for the paper activity history (never the real portfolio)."""
    rows = [o for o in orders if isinstance(o, dict)]
    simulated = [o for o in rows if o.get("status") == "SIMULATED"]
    cancelled = [o for o in rows if o.get("status") == "CANCELLED"]
    expired = [o for o in rows if o.get("status") == "EXPIRED"]
    drafts = [o for o in rows if o.get("status") == "DRAFT"]

    pnls = [finite_or_none(o.get("pnl")) for o in simulated]
    pnls = [p for p in pnls if p is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    return {
        "total": len(rows),
        "draft": len(drafts),
        "simulated": len(simulated),
        "cancelled": len(cancelled),
        "expired": len(expired),
        "resolved": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": (len(wins) / len(pnls)) if pnls else None,
        "hypotheticalTotalPnl": sum(pnls) if pnls else 0.0,
        "hypotheticalBestPnl": max(pnls) if pnls else None,
        "hypotheticalWorstPnl": min(pnls) if pnls else None,
        "paper": True,
        "disclaimer": (
            "Aggregated paper-simulation statistics only. These are hypothetical results "
            "computed from observed prices, are not real trades, and are kept entirely "
            "separate from the portfolio tracker."
        ),
    }


def is_valid_order_type(order_type: str) -> bool:
    return (order_type or "").strip().upper() in ORDER_TYPES
