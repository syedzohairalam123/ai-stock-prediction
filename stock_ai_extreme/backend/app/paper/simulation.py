"""
Phase 20 — the simulation engine.

`SimulationEngine` turns a validated request plus a real, observed quote into a
paper order *and* into its illustrative preview. It never touches the network
directly (quotes are injected), which is what makes its arithmetic testable.

Nothing in this file can place an order. There is no broker client, no exchange
endpoint, no signing key, no payment path and no settlement code — by
construction, not by policy flag.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import paper_settings
from .instruments import PaperInstrument, QuoteMode
from .pnl import (
    compute_pnl,
    evaluate_limit_fill,
    finite_or_none,
    position_notional,
    quantity_from_notional,
)
from .quotes import PaperDataMode, PaperQuote

PAPER_BANNER = "PAPER SIMULATION — NOT A REAL ORDER"

#: Simulation statuses (spec §11). There is deliberately no FILLED/EXECUTED.
STATUS_DRAFT = "DRAFT"
STATUS_SIMULATED = "SIMULATED"
STATUS_CANCELLED = "CANCELLED"
STATUS_EXPIRED = "EXPIRED"

SIMULATION_STATUSES = (STATUS_DRAFT, STATUS_SIMULATED, STATUS_CANCELLED, STATUS_EXPIRED)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SimulationInput:
    """Everything the engine needs, already validated."""

    side: str
    order_type: str
    amount: float
    amount_mode: str  # NOTIONAL | QUANTITY
    limit_price: Optional[float] = None
    notes: Optional[str] = None


class SimulationEngine:
    """Pure-ish simulation logic. Same input → same output, no hidden state."""

    # ---------------------------------------------------------------- pricing

    @staticmethod
    def reference_price(instrument: PaperInstrument, quote: PaperQuote) -> Optional[float]:
        """The observed reference the simulation is anchored to.

        For a price instrument that is the real observed price; for a forecast
        event it is the probability of the selected outcome, in percent.
        Returns None when nothing honest can be anchored — the caller must then
        refuse to simulate rather than anchor on a fabricated number.
        """
        if instrument.quote_mode is QuoteMode.PROBABILITY:
            side = None
            return None  # filled in by `reference_price_for_side`
        if quote.data_mode == PaperDataMode.UNAVAILABLE:
            return None
        return finite_or_none(quote.price)

    @staticmethod
    def reference_price_for_side(instrument: PaperInstrument, quote: PaperQuote, side: str) -> Optional[float]:
        """Probability-mode reference: the selected outcome's own probability."""
        if instrument.quote_mode is QuoteMode.PROBABILITY:
            side = (side or "").upper()
            if side == "YES":
                return finite_or_none(quote.probability_yes)
            if side == "NO":
                return finite_or_none(quote.probability_no)
            return None
        return SimulationEngine.reference_price(instrument, quote)

    @staticmethod
    def derive_quantity(amount: float, amount_mode: str, reference: Optional[float]) -> Optional[float]:
        if amount_mode == "QUANTITY":
            value = finite_or_none(amount)
            return value if value is not None and value > 0 else None
        if reference is None or reference <= 0:
            return None
        return quantity_from_notional(amount, reference)

    # ---------------------------------------------------------------- preview

    @classmethod
    def preview(
        cls,
        instrument: PaperInstrument,
        quote: PaperQuote,
        payload: SimulationInput,
    ) -> dict:
        """Preview payload shown before submission (spec §10).

        It states plainly that nothing has been sent anywhere and that this is
        a paper simulation, and it exposes the quote's freshness so a stale
        reference is never presented as current.
        """
        side = (payload.side or "").upper()
        reference = cls.reference_price_for_side(instrument, quote, side)
        quantity = cls.derive_quantity(payload.amount, payload.amount_mode, reference)
        notional = position_notional(quantity, reference) if (quantity and reference) else None

        warnings: list[str] = []
        if quote.stale:
            warnings.append(
                ("STALE DATA — this reference is not a current price. " + (quote.stale_reason or "")).strip()
            )
        if quote.data_mode == PaperDataMode.UNAVAILABLE:
            warnings.append("No usable quote is available, so this simulation cannot be anchored to a price.")
        if payload.order_type == "LIMIT" and side in ("BUY", "YES") and reference and payload.limit_price:
            if payload.limit_price > reference:
                warnings.append("A LIMIT BUY above the observed price would not fill immediately.")
        if payload.order_type == "LIMIT" and side in ("SELL", "NO") and reference and payload.limit_price:
            if payload.limit_price < reference:
                warnings.append("A LIMIT SELL below the observed price would not fill immediately.")

        return {
            "banner": PAPER_BANNER,
            "paper": True,
            "simulationOnly": True,
            "instrument": instrument.symbol,
            "displayName": instrument.display_name,
            "instrumentKind": instrument.kind.value,
            "quoteMode": instrument.quote_mode.value,
            "direction": side,
            "directionLabel": _direction_label(instrument, side),
            "orderType": payload.order_type,
            "orderTypeExplanation": explain_order_type(payload.order_type, instrument.quote_mode),
            "referencePrice": reference,
            "referenceLabel": _reference_label(instrument),
            "limitPrice": finite_or_none(payload.limit_price),
            "amountMode": payload.amount_mode,
            "amount": finite_or_none(payload.amount),
            "quantity": quantity,
            "estimatedNotional": notional,
            "currency": instrument.currency,
            "timestamp": utcnow().isoformat(),
            "quoteTimestamp": quote.timestamp,
            "dataMode": quote.data_mode,
            "dataSource": quote.source,
            "dataStatus": quote.status,
            "stale": quote.stale,
            "warnings": warnings,
            "disclaimer": (
                "This is a hypothetical simulation. No order is placed, no money moves, "
                "and no broker or exchange is contacted."
            ),
        }

    # ------------------------------------------------------------- submission

    @classmethod
    def build_order(
        cls,
        instrument: PaperInstrument,
        quote: PaperQuote,
        payload: SimulationInput,
        *,
        opened_snapshot: Optional[dict],
        draft: bool = False,
    ) -> dict:
        """Build the persistable paper order.

        A MARKET simulation is anchored at the observed reference immediately.
        A LIMIT simulation is anchored at its *limit* price, and its condition
        is left undecided (`None`) until real subsequent observations are
        checked — never assumed to have filled.
        """
        side = (payload.side or "").upper()
        observed_reference = cls.reference_price_for_side(instrument, quote, side)
        if payload.order_type == "LIMIT":
            anchor = finite_or_none(payload.limit_price)
        else:
            anchor = observed_reference

        quantity = cls.derive_quantity(payload.amount, payload.amount_mode, anchor or observed_reference)
        notional = position_notional(quantity, anchor or observed_reference) if quantity else None

        now = utcnow()
        submitted_snapshot = {
            "capturedAt": now.isoformat(),
            "observedPrice": observed_reference,
            "observedTimestamp": quote.timestamp,
            "source": quote.source,
            "status": quote.status,
            "dataMode": quote.data_mode,
            "stale": quote.stale,
            "probabilityYes": quote.probability_yes,
            "probabilityNo": quote.probability_no,
        }

        status = STATUS_DRAFT if draft else STATUS_SIMULATED
        expires_at = None
        if not draft and payload.order_type == "LIMIT":
            expires_at = now + timedelta(seconds=paper_settings.paper_order_ttl_seconds)

        condition_met: Optional[bool] = None
        condition_detail: dict[str, Any] = {}
        if not draft:
            if payload.order_type == "MARKET":
                condition_met = True
                condition_detail = {
                    "reason": "Simulated at market on the observed reference; no exchange was contacted.",
                    "observationsChecked": 0,
                }
            else:
                condition_detail = {
                    "reason": "Waiting for a real subsequent observation to test the limit condition.",
                    "observationsChecked": 0,
                }

        return {
            "symbol": instrument.symbol,
            "instrument_kind": instrument.kind.value,
            "display_name": instrument.display_name,
            "quote_mode": instrument.quote_mode.value,
            "side": side,
            "order_type": payload.order_type,
            "amount_mode": payload.amount_mode,
            "amount": float(payload.amount or 0.0),
            "quantity": float(quantity or 0.0),
            "limit_price": finite_or_none(payload.limit_price),
            "reference_price": anchor,
            "currency": instrument.currency,
            "notional": notional,
            "status": status,
            "data_mode": quote.data_mode,
            "data_source": quote.source,
            "opened_snapshot": opened_snapshot or {},
            "submit_snapshot": submitted_snapshot,
            "forecast_market_id": instrument.market_id,
            "probability_at_open": _opening_probability(opened_snapshot or {}, side),
            "probability_current": (
                finite_or_none(quote.probability_yes if side == "YES" else quote.probability_no)
                if instrument.quote_mode is QuoteMode.PROBABILITY
                else None
            ),
            "condition_met": condition_met,
            "condition_checked_at": now if condition_met is not None else None,
            "condition_detail": condition_detail,
            "exit_reference": None,
            "exit_at": None,
            "pnl": None,
            "pnl_percent": None,
            "notes": payload.notes,
            "opened_at": now,
            "submitted_at": now,
            "expires_at": expires_at,
        }

    # -------------------------------------------------------------- evaluation

    @classmethod
    def evaluate(
        cls,
        order: dict,
        instrument: PaperInstrument,
        bars: list[dict],
        *,
        live_quote: Optional[PaperQuote] = None,
    ) -> dict:
        """Re-evaluate a simulation against real subsequent observations.

        `bars` must be real OHLC rows **strictly after** the simulation was
        submitted. An empty list means "no newer data yet" and produces no P&L
        and no condition verdict — never a fabricated exit price.
        """
        result: dict[str, Any] = {
            "orderId": order.get("id"),
            "status": order.get("status"),
            "paper": True,
            "observationsChecked": len(bars),
            "evaluatedAt": utcnow().isoformat(),
        }

        if order.get("status") != STATUS_SIMULATED:
            result["outcome"] = order.get("status")
            result["message"] = "This simulation is no longer open, so it is not re-evaluated."
            return result

        side = order.get("side") or ""
        order_type = order.get("order_type") or order.get("orderType") or "MARKET"
        quote_mode = (
            QuoteMode.PROBABILITY
            if (order.get("quote_mode") or order.get("quoteMode")) == QuoteMode.PROBABILITY.value
            else QuoteMode.PRICE
        )
        reference = finite_or_none(order.get("reference_price") if "reference_price" in order else order.get("referencePrice"))
        limit_price = finite_or_none(order.get("limit_price") if "limit_price" in order else order.get("limitPrice"))
        quantity = finite_or_none(order.get("quantity")) or 0.0

        updates: dict[str, Any] = {}

        if order_type == "LIMIT":
            fill = evaluate_limit_fill(side, limit_price or 0.0, bars)
            if fill is not None:
                entry = finite_or_none(fill.get("fillReference")) or limit_price
                updates["condition_met"] = True
                updates["condition_checked_at"] = utcnow()
                updates["condition_detail"] = {
                    "reason": fill.get("reason"),
                    "observationsChecked": len(bars),
                    "filledAt": fill.get("timestamp"),
                    "observedLow": fill.get("observedLow"),
                    "observedHigh": fill.get("observedHigh"),
                    "observedClose": fill.get("observedClose"),
                }
                result["conditionMet"] = True
                result["fill"] = fill
                # The entry reference for a limit fill is the limit price (or
                # better); the exit is the newest real close after the fill.
                exit_reference = _latest_close(bars)
                if exit_reference is not None and entry is not None:
                    pnl = compute_pnl(side, entry, exit_reference, quantity, quote_mode)
                    if pnl is not None:
                        updates["exit_reference"] = exit_reference
                        updates["exit_at"] = _latest_timestamp(bars)
                        updates["pnl"] = pnl.hypothetical_pnl
                        updates["pnl_percent"] = pnl.hypothetical_pnl_percent
                        result["pnl"] = pnl.to_dict()
            elif bars:
                updates["condition_met"] = False
                updates["condition_checked_at"] = utcnow()
                updates["condition_detail"] = {
                    "reason": (
                        f"Checked {len(bars)} real observation(s) after submission; "
                        "the limit level was not reached in them."
                    ),
                    "observationsChecked": len(bars),
                }
                result["conditionMet"] = False
                result["message"] = (
                    "The hypothetical limit was not reached in the observations available so far. "
                    "It stays open until it expires or is cancelled."
                )
            else:
                updates["condition_checked_at"] = utcnow()
                updates["condition_detail"] = {
                    "reason": "No newer observations have been published yet.",
                    "observationsChecked": 0,
                }
                result["conditionMet"] = None
                result["message"] = "No newer observations yet — the limit condition cannot be judged."
        else:
            exit_reference = _latest_close(bars)
            if exit_reference is None and live_quote is not None and live_quote.price is not None:
                # The provider itself is the freshest observation we have; using
                # it is honest (it is real) as long as we label the source.
                exit_reference = finite_or_none(live_quote.price)
                result["exitSource"] = live_quote.source
            if exit_reference is not None and reference is not None:
                pnl = compute_pnl(side, reference, exit_reference, quantity, quote_mode)
                if pnl is not None:
                    updates["exit_reference"] = exit_reference
                    updates["exit_at"] = _latest_timestamp(bars) or utcnow()
                    updates["pnl"] = pnl.hypothetical_pnl
                    updates["pnl_percent"] = pnl.hypothetical_pnl_percent
                    result["pnl"] = pnl.to_dict()
            else:
                result["message"] = "No newer real observation is available, so no P&L is computed."

        result["updates"] = updates
        return result


# --------------------------------------------------------------------------- #
# Presentational helpers (kept next to the engine so the UI and API agree)
# --------------------------------------------------------------------------- #

def explain_order_type(order_type: str, quote_mode: QuoteMode = QuoteMode.PRICE) -> str:
    """Plain-language explanation of the selected order type (spec §5)."""
    order_type = (order_type or "").upper()
    if order_type == "MARKET":
        return (
            "MARKET — the simulation is anchored to the price observed right now. "
            "No exchange is contacted; the fill is assumed at the observed reference."
        )
    if order_type == "LIMIT":
        if quote_mode is QuoteMode.PROBABILITY:
            return (
                "LIMIT — the simulation only becomes 'reached' when the real traded probability "
                "actually touches your limit level. Nothing is sent anywhere."
            )
        return (
            "LIMIT — the simulation only fills when the market really trades at your limit price "
            "or better. Subsequent real prices are checked afterwards; nothing is sent anywhere."
        )
    return "Choose MARKET or LIMIT to see what it means in this simulation."


def describe_status(status: str) -> str:
    return {
        STATUS_DRAFT: "Draft — prepared but not simulated yet.",
        STATUS_SIMULATED: "Simulated — recorded as a paper scenario. No order was placed.",
        STATUS_CANCELLED: "Cancelled — you stopped this simulation.",
        STATUS_EXPIRED: "Expired — the simulation reached its time limit without its condition being met.",
    }.get(status, status or "Unknown")


def _direction_label(instrument: PaperInstrument, side: str) -> str:
    if instrument.quote_mode is QuoteMode.PROBABILITY:
        return f"PAPER {side} (informational forecast selection)"
    return f"PAPER {side}"


def _reference_label(instrument: PaperInstrument) -> str:
    return "Current probability (%)" if instrument.quote_mode is QuoteMode.PROBABILITY else "Observed price"


def _opening_probability(snapshot: dict, side: str) -> Optional[float]:
    """The outcome's probability as captured when the ticket was opened.

    Prefers the outcome-specific field; falls back to the generic
    `observedPrice` (which is exactly what the ticket records for the selected
    outcome) so an API client that sends either shape is treated the same.
    Returns None — never 0 — when nothing was captured.
    """
    if side == "NO":
        specific = finite_or_none(snapshot.get("probabilityNo"))
    elif side == "YES":
        specific = finite_or_none(snapshot.get("probabilityYes"))
    else:
        specific = None
    return specific if specific is not None else finite_or_none(snapshot.get("observedPrice"))


def _latest_close(bars: list[dict]) -> Optional[float]:
    for row in reversed(bars):
        value = finite_or_none(row.get("close"))
        if value is not None:
            return value
    return None


def _latest_timestamp(bars: list[dict]) -> Optional[datetime]:
    for row in reversed(bars):
        raw = row.get("timestamp")
        if not raw:
            continue
        text = str(raw).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None
