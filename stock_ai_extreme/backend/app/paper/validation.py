"""
Phase 20 — server-side validation.

The client is never trusted. Every field that reaches the simulation engine is
re-checked here and the result is a structured list of issues, so the API can
return a precise 422 instead of a generic rejection and the UI can highlight
the exact field.

Explicitly rejected (spec §7):
    * invalid number / non-numeric
    * NaN and Infinity
    * negative amount
    * zero amount
    * excessive precision
    * missing price (a LIMIT order without a limit price)
    * missing symbol
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from .config import paper_settings
from .instruments import (
    AMOUNT_MODES,
    ORDER_TYPES,
    PaperInstrument,
    QuoteMode,
)
from .pnl import is_finite_number


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, field_name: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(field_name, code, message))

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.to_dict() for i in self.issues]}


def _decimal_places(value: float) -> int:
    """How many decimal places a number actually carries (no float noise)."""
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 99
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int):
        return 99
    return max(0, -exponent)


def normalize_amount_mode(value: Optional[str]) -> str:
    mode = (value or "NOTIONAL").strip().upper()
    return mode if mode in AMOUNT_MODES else "NOTIONAL"


def validate_simulation_request(
    *,
    instrument: Optional[PaperInstrument],
    instrument_error: Optional[str],
    side: Optional[str],
    order_type: Optional[str],
    amount: Optional[float],
    amount_mode: Optional[str],
    limit_price: Optional[float],
    reference_price: Optional[float],
    client_timestamp: Optional[str],
    symbol: Optional[str],
) -> ValidationResult:
    """Validate a paper-simulation submission end to end."""
    result = ValidationResult()

    # --- symbol / instrument -------------------------------------------------
    if not symbol or not str(symbol).strip():
        result.add("symbol", "missing_symbol", "A symbol is required.")
    if instrument is None:
        result.add(
            "symbol",
            "unknown_instrument",
            instrument_error or "This instrument could not be resolved.",
        )
        # Without a resolved instrument the remaining checks cannot be trusted
        # to mean anything, so stop here and return exactly what went wrong.
        return result

    # --- side ---------------------------------------------------------------
    allowed_sides = instrument.sides
    normalized_side = (side or "").strip().upper()
    if not normalized_side:
        result.add("side", "missing_side", "Choose a paper direction.")
    elif normalized_side not in allowed_sides:
        result.add(
            "side",
            "invalid_side",
            f"{instrument.kind.value} simulations accept {', '.join(allowed_sides)}.",
        )

    # --- order type ---------------------------------------------------------
    normalized_type = (order_type or "").strip().upper()
    if not normalized_type:
        result.add("orderType", "missing_order_type", "Choose MARKET or LIMIT.")
    elif normalized_type not in ORDER_TYPES:
        result.add("orderType", "invalid_order_type", "Order type must be MARKET or LIMIT.")

    # --- amount -------------------------------------------------------------
    mode = normalize_amount_mode(amount_mode)
    if amount is None:
        result.add("amount", "missing_amount", "Enter a simulated amount or quantity.")
    elif not is_finite_number(amount):
        result.add("amount", "invalid_number", "Amount must be a real, finite number.")
    else:
        value = float(amount)
        if math.isnan(value) or math.isinf(value):
            result.add("amount", "non_finite", "Amount cannot be NaN or Infinity.")
        elif value < 0:
            result.add("amount", "negative_amount", "Amount cannot be negative.")
        elif value == 0:
            result.add("amount", "zero_amount", "Amount must be greater than zero.")
        else:
            if mode == "NOTIONAL":
                if value < paper_settings.paper_min_notional:
                    result.add(
                        "amount",
                        "below_minimum",
                        f"Minimum simulated notional is {paper_settings.paper_min_notional}.",
                    )
                if value > paper_settings.paper_max_notional:
                    result.add(
                        "amount",
                        "above_maximum",
                        f"Simulated notional cannot exceed {paper_settings.paper_max_notional:,.0f}.",
                    )
                places = _decimal_places(value)
                if places > paper_settings.paper_amount_precision:
                    result.add(
                        "amount",
                        "excessive_precision",
                        f"Notional accepts at most {paper_settings.paper_amount_precision} decimal places.",
                    )
            else:
                if value > paper_settings.paper_max_quantity:
                    result.add(
                        "amount",
                        "above_maximum",
                        f"Simulated quantity cannot exceed {paper_settings.paper_max_quantity:,.0f}.",
                    )
                places = _decimal_places(value)
                if places > min(paper_settings.paper_quantity_precision, instrument.quantity_precision):
                    result.add(
                        "amount",
                        "excessive_precision",
                        f"Quantity accepts at most "
                        f"{min(paper_settings.paper_quantity_precision, instrument.quantity_precision)} decimal places "
                        f"for {instrument.kind.value}.",
                    )

    # --- price --------------------------------------------------------------
    if normalized_type == "LIMIT":
        if limit_price is None:
            result.add("limitPrice", "missing_price", "A LIMIT simulation needs a limit price.")
        elif not is_finite_number(limit_price):
            result.add("limitPrice", "invalid_price", "Limit price must be a real, finite number.")
        else:
            lp = float(limit_price)
            if lp <= 0:
                result.add("limitPrice", "invalid_price", "Limit price must be greater than zero.")
            elif lp > paper_settings.paper_max_notional:
                result.add("limitPrice", "price_out_of_range", "Limit price is outside the supported range.")
            else:
                places = _decimal_places(lp)
                if places > paper_settings.paper_price_precision:
                    result.add(
                        "limitPrice",
                        "excessive_precision",
                        f"Limit price accepts at most {paper_settings.paper_price_precision} decimal places.",
                    )
    elif limit_price is not None and is_finite_number(limit_price) and float(limit_price) < 0:
        result.add("limitPrice", "invalid_price", "Limit price cannot be negative.")

    # --- reference price (the simulation cannot claim a current price without one)
    if instrument.quote_mode is QuoteMode.PRICE:
        if reference_price is None or not is_finite_number(reference_price):
            result.add(
                "referencePrice",
                "missing_reference_price",
                "No usable reference price was observed for this instrument, so it cannot be simulated.",
            )
        elif float(reference_price) <= 0:
            result.add(
                "referencePrice",
                "invalid_reference_price",
                "The observed reference price is not positive.",
            )

    # --- client timestamp ---------------------------------------------------
    if client_timestamp:
        parsed = parse_client_timestamp(client_timestamp)
        if parsed is None:
            result.add("timestamp", "invalid_timestamp", "Timestamp is not a valid ISO-8601 instant.")
        else:
            skew = (parsed - datetime.now(timezone.utc)).total_seconds()
            if skew > paper_settings.paper_max_clock_skew_seconds:
                result.add(
                    "timestamp",
                    "timestamp_in_future",
                    "The supplied timestamp is too far in the future.",
                )

    return result


def parse_client_timestamp(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 client timestamp into a timezone-aware UTC datetime."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
