"""
Phase 20 — `PaperOrderService`.

The single entry point the routes (and anything else) use. It orchestrates:

    resolve instrument → fetch a real quote → validate → (idempotency) →
    simulate → persist → audit

Every branch ends in a decision. There is no code path that returns
"submitting" forever, and no branch that invents a price to keep going.
"""
from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import settings
from ..logging_config import get_logger
from ..security import validate_ticker
from . import repository as repo
from .config import paper_settings
from .instruments import (
    FORECAST_PREFIX,
    InstrumentKind,
    PaperInstrument,
    QuoteMode,
    resolve_instrument,
)
from .pnl import summarize_paper_activity
from .quotes import PaperDataMode, PaperQuote, build_quote, observed_bars_after
from .simulation import (
    STATUS_CANCELLED,
    STATUS_DRAFT,
    STATUS_EXPIRED,
    STATUS_SIMULATED,
    SimulationEngine,
    SimulationInput,
    describe_status,
    utcnow,
)
from .validation import normalize_amount_mode, validate_simulation_request

logger = get_logger("neural_market.paper.service")


class PaperOrderError(Exception):
    """A user-facing, structured failure (mapped to a 4xx by the route layer)."""

    def __init__(self, message: str, *, status_code: int = 400, issues: Optional[list[dict]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.issues = issues or []


class PaperOrderService:
    # ------------------------------------------------------------ instrument

    @staticmethod
    async def resolve(
        symbol: str,
        kind: Optional[str] = None,
        *,
        display_name: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> tuple[Optional[PaperInstrument], Optional[str]]:
        """Resolve a symbol, returning (instrument, error_message)."""
        raw = (symbol or "").strip()
        if not raw:
            return None, "A symbol is required."
        try:
            if raw.upper().startswith(FORECAST_PREFIX):
                instrument = resolve_instrument(raw, kind)
                return await PaperOrderService._enrich_forecast(instrument), None
            instrument = resolve_instrument(validate_ticker(raw), kind, display_name=display_name, currency=currency)
            return instrument, None
        except ValueError as exc:
            return None, str(exc)
        except Exception as exc:  # a provider hiccup must not be a 500
            logger.warning("instrument resolution failed for %s: %s", raw, exc)
            return None, "This instrument could not be resolved."

    @staticmethod
    async def _enrich_forecast(instrument: PaperInstrument) -> PaperInstrument:
        """Attach the forecast event's real title, category and close time.

        A source failure leaves the instrument exactly as it was (with the
        market id) — the ticket then shows the generic label rather than a
        made-up question or date.
        """
        from ..forecast_markets import fetch_market_by_id

        try:
            market = await fetch_market_by_id(
                instrument.market_id or instrument.provider_symbol,
                settings.forecast_market_timeout_seconds,
            )
        except Exception as exc:
            logger.debug("forecast enrichment failed for %s: %s", instrument.market_id, exc)
            market = None
        if not market:
            return instrument
        return dataclasses.replace(
            instrument,
            display_name=market.get("title") or instrument.display_name,
            question=market.get("title"),
            close_time=market.get("closeTime"),
            category=market.get("category"),
            source_url=(market.get("sources") or [{}])[0].get("url"),
        )

    # ---------------------------------------------------------------- quotes

    @staticmethod
    async def quote(instrument: PaperInstrument, *, with_bid_ask: bool = True) -> PaperQuote:
        return await build_quote(instrument, with_bid_ask=with_bid_ask)

    # -------------------------------------------------------------- preview

    async def preview(
        self,
        *,
        symbol: str,
        kind: Optional[str] = None,
        side: str = "BUY",
        order_type: str = "MARKET",
        amount: Optional[float] = None,
        amount_mode: Optional[str] = None,
        limit_price: Optional[float] = None,
        client_timestamp: Optional[str] = None,
        currency: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> dict:
        instrument, error = await self.resolve(symbol, kind, display_name=display_name, currency=currency)
        quote = await build_quote(instrument) if instrument else None
        mode = normalize_amount_mode(amount_mode)

        validation = validate_simulation_request(
            instrument=instrument,
            instrument_error=error,
            side=side,
            order_type=order_type,
            amount=amount,
            amount_mode=mode,
            limit_price=limit_price,
            reference_price=(
                SimulationEngine.reference_price_for_side(instrument, quote, side)
                if instrument and quote else None
            ),
            client_timestamp=client_timestamp,
            symbol=symbol,
        )
        if not validation.ok:
            return {
                "ok": False,
                "issues": [i.to_dict() for i in validation.issues],
                "instrument": instrument.to_dict() if instrument else None,
                "quote": quote.to_dict() if quote else None,
                "banner": "PAPER SIMULATION — NOT A REAL ORDER",
                "paper": True,
            }

        preview = SimulationEngine.preview(
            instrument,
            quote,
            SimulationInput(
                side=side.upper(),
                order_type=order_type.upper(),
                amount=float(amount),
                amount_mode=mode,
                limit_price=limit_price,
            ),
        )
        return {
            "ok": True,
            "preview": preview,
            "instrument": instrument.to_dict(),
            "quote": quote.to_dict(),
            "issues": [],
            "paper": True,
        }

    # ------------------------------------------------------------- submission

    async def submit(
        self,
        *,
        symbol: str,
        kind: Optional[str] = None,
        side: str = "BUY",
        order_type: str = "MARKET",
        amount: Optional[float] = None,
        amount_mode: Optional[str] = None,
        limit_price: Optional[float] = None,
        opened_snapshot: Optional[dict] = None,
        client_timestamp: Optional[str] = None,
        client_request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        currency: Optional[str] = None,
        display_name: Optional[str] = None,
        notes: Optional[str] = None,
        draft: bool = False,
        acknowledge_stale: bool = False,
    ) -> dict:
        request_id = (client_request_id or "").strip() or uuid.uuid4().hex
        user = (user_id or "").strip() or "anonymous"
        mode = normalize_amount_mode(amount_mode)

        # --- idempotency first: a repeated request must not duplicate work ---
        existing = repo.get_order_by_request(user, request_id)
        if existing is not None:
            repo.add_audit(
                request_id=request_id,
                event="DEDUPLICATED",
                order_id=existing["id"],
                user_id=user,
                instrument=existing.get("symbol"),
                reference={"clientRequestId": request_id},
                result={"status": existing.get("status")},
            )
            return {"order": existing, "duplicate": True, "requestId": request_id}

        instrument, error = await self.resolve(symbol, kind, display_name=display_name, currency=currency)
        quote = await build_quote(instrument) if instrument else None
        anchor = (
            SimulationEngine.reference_price_for_side(instrument, quote, side)
            if instrument and quote else None
        )

        validation = validate_simulation_request(
            instrument=instrument,
            instrument_error=error,
            side=side,
            order_type=order_type,
            amount=amount,
            amount_mode=mode,
            limit_price=limit_price,
            reference_price=anchor,
            client_timestamp=client_timestamp,
            symbol=symbol,
        )
        if not validation.ok:
            repo.add_audit(
                request_id=request_id,
                event="REJECTED",
                user_id=user,
                instrument=symbol,
                reference={"side": side, "orderType": order_type, "amount": amount},
                result={"issues": [i.to_dict() for i in validation.issues]},
            )
            raise PaperOrderError(
                "The simulation request is not valid.",
                status_code=422,
                issues=[i.to_dict() for i in validation.issues],
            )

        if not draft and quote.data_mode == PaperDataMode.STALE and not acknowledge_stale:
            raise PaperOrderError(
                "The quote is stale. Acknowledge the stale reading to record this simulation, "
                "or refresh the ticket first.",
                status_code=409,
                issues=[
                    {
                        "field": "quote",
                        "code": "stale_quote",
                        "message": quote.stale_reason or "The quote is stale.",
                    }
                ],
            )

        payload = SimulationInput(
            side=side.upper(),
            order_type=order_type.upper(),
            amount=float(amount),
            amount_mode=mode,
            limit_price=limit_price,
            notes=notes,
        )
        record = SimulationEngine.build_order(
            instrument,
            quote,
            payload,
            opened_snapshot=opened_snapshot,
            draft=draft,
        )
        record["client_request_id"] = request_id
        record["user_id"] = user

        try:
            order = repo.create_order(record)
        except Exception as exc:
            # A racing duplicate hits the unique (user_id, client_request_id)
            # constraint; that is a success for idempotency, not a failure.
            logger.info("paper order insert conflicted, resolving via idempotency: %s", exc)
            existing = repo.get_order_by_request(user, request_id)
            if existing is not None:
                return {"order": existing, "duplicate": True, "requestId": request_id}
            raise PaperOrderError("The simulation could not be recorded.", status_code=500)

        repo.add_audit(
            request_id=request_id,
            event="SUBMITTED",
            order_id=order["id"],
            user_id=user,
            instrument=order["symbol"],
            reference={
                "side": order["side"],
                "orderType": order["orderType"],
                "amountMode": order["amountMode"],
                "amount": order["amount"],
                "limitPrice": order["limitPrice"],
                "quoteSource": quote.source,
                "quoteStatus": quote.status,
                "dataMode": quote.data_mode,
                "referencePrice": order["referencePrice"],
                "stale": quote.stale,
            },
            result={
                "status": order["status"],
                "quantity": order["quantity"],
                "notional": order["notional"],
                "conditionMet": order["conditionMet"],
            },
        )

        return {
            "order": order,
            "duplicate": False,
            "requestId": request_id,
            "message": describe_status(order["status"]),
            "paper": True,
        }

    # ------------------------------------------------------------- retrieval

    def get(self, order_id: str) -> dict:
        order = repo.get_order(order_id)
        if order is None:
            raise PaperOrderError("That simulation does not exist.", status_code=404)
        return order

    def history(
        self,
        *,
        user_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> dict:
        user = (user_id or "").strip() or None
        rows = repo.list_orders(
            user_id=user,
            symbol=symbol,
            status=status,
            limit=limit or paper_settings.paper_default_history_limit,
        )
        return {
            "orders": rows,
            "count": len(rows),
            "summary": summarize_paper_activity(rows),
            "paper": True,
            "separateFromPortfolio": True,
            "disclaimer": (
                "Recent simulations are stored separately from the portfolio tracker. "
                "Nothing here is a real position."
            ),
        }

    def audit(self, *, order_id: Optional[str] = None, request_id: Optional[str] = None) -> dict:
        rows = repo.list_audit(order_id=order_id, request_id=request_id, limit=paper_settings.paper_audit_limit)
        return {"entries": rows, "count": len(rows), "paper": True}

    # ------------------------------------------------------------- lifecycle

    async def evaluate(self, order_id: str) -> dict:
        order = self.get(order_id)
        if order["status"] != STATUS_SIMULATED:
            return {
                "order": order,
                "result": {
                    "outcome": order["status"],
                    "message": "Only an open simulation can be evaluated.",
                    "paper": True,
                },
            }

        instrument, _error = await self.resolve(order["symbol"], order.get("instrumentKind"))
        if instrument is None:
            raise PaperOrderError("This instrument can no longer be resolved.", status_code=409)

        submitted_at = _parse_iso(order.get("submittedAt")) or utcnow()
        quote_mode = order.get("quoteMode")

        bars: list[dict] = []
        live_quote: Optional[PaperQuote] = None
        if quote_mode == QuoteMode.PROBABILITY.value:
            live_quote = await build_quote(instrument, with_bid_ask=False, with_volatility=False)
        else:
            bars = await observed_bars_after(instrument.provider_symbol or instrument.symbol, submitted_at)
            if not bars:
                live_quote = await build_quote(instrument, with_bid_ask=False, with_volatility=False)

        # The repository returns camelCase; the engine also accepts snake_case,
        # so normalise once here to keep the engine's field access explicit.
        engine_order = {
            **order,
            "quote_mode": quote_mode,
            "order_type": order.get("orderType"),
            "reference_price": order.get("referencePrice"),
            "limit_price": order.get("limitPrice"),
        }
        outcome = SimulationEngine.evaluate(engine_order, instrument, bars, live_quote=live_quote)

        updates = outcome.pop("updates", {})
        if live_quote is not None and quote_mode == QuoteMode.PROBABILITY.value:
            probability = (
                live_quote.probability_yes if order.get("side") == "YES" else live_quote.probability_no
            )
            if probability is not None:
                updates["probability_current"] = probability
        if live_quote is not None:
            updates["data_mode"] = live_quote.data_mode
            updates["data_source"] = live_quote.source

        updated = repo.update_order(order_id, **updates) if updates else order

        repo.add_audit(
            request_id=order.get("clientRequestId") or order_id,
            event="EVALUATED",
            order_id=order_id,
            user_id=order.get("userId"),
            instrument=order["symbol"],
            reference={
                "observationsChecked": outcome.get("observationsChecked"),
                "dataMode": (updated or order).get("dataMode"),
            },
            result={
                "conditionMet": outcome.get("conditionMet"),
                "pnl": (updated or order).get("pnl"),
            },
        )

        return {"order": updated or order, "result": outcome, "paper": True}

    def cancel(self, order_id: str, *, reason: Optional[str] = None) -> dict:
        order = self.get(order_id)
        if order["status"] in (STATUS_CANCELLED, STATUS_EXPIRED):
            return order
        detail = dict(order.get("conditionDetail") or {})
        if reason:
            detail["cancelReason"] = reason
        updated = repo.update_order(
            order_id,
            status=STATUS_CANCELLED,
            condition_detail=detail,
        )
        repo.add_audit(
            request_id=order.get("clientRequestId") or order_id,
            event="CANCELLED",
            order_id=order_id,
            user_id=order.get("userId"),
            instrument=order["symbol"],
            reference={"reason": reason},
            result={"status": STATUS_CANCELLED},
        )
        return updated or order

    def expire_due(self) -> int:
        changed = repo.expire_overdue()
        if changed:
            repo.add_audit(
                request_id="background",
                event="EXPIRED",
                instrument=None,
                reference={"count": changed},
                result={"status": STATUS_EXPIRED},
            )
        return changed

    def summary(self, user_id: Optional[str] = None) -> dict:
        user = (user_id or "").strip() or None
        rows = repo.list_orders(user_id=user, limit=paper_settings.paper_max_history_limit)
        return {
            "summary": summarize_paper_activity(rows),
            "byStatus": repo.count_by_status(user),
            "paper": True,
            "separateFromPortfolio": True,
        }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


service = PaperOrderService()
