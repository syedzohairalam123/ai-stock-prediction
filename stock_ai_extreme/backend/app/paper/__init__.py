"""
Phase 20 — Advanced Quick Order / Paper Trading Ticket.

A compact, context-aware **simulation** ticket that any page of the terminal can
open for the instrument the user is currently looking at (stock, PSX symbol,
index, crypto, commodity, forex, or a Phase 14 forecast event).

Ground rules this package is built on — they are enforced in code, not just in
comments:

* **Non-monetary.** Nothing here places an order, moves money, settles cash,
  processes a payment, or talks to a broker/exchange order endpoint. There is
  no deposits/withdrawals/wagering surface at all. The only writes that happen
  are rows in this app's own local database recording a *simulation*.
* **Honest data.** Prices/probabilities come from the same provider layer the
  rest of the app uses (one cache, one fallback chain). A value that cannot be
  fetched is reported UNAVAILABLE and never replaced with an invented number.
* **Stale means stale.** A quote older than the configured window is labelled
  STALE and the ticket refuses to claim it as "the current price".
* **Server-authoritative.** The frontend is never trusted: symbol, side, order
  type, amount, price, timestamp and instrument state are all re-validated here.
* **Idempotent.** A repeated submission with the same client request id returns
  the original simulation instead of creating a duplicate.
* **Separate from the real portfolio.** Paper simulations live in their own
  table (`paper_orders`) and are never added to `portfolio_holdings`.
"""
from __future__ import annotations

from .routes import market_router, paper_router
from .state import configure, get_manager

__all__ = ["market_router", "paper_router", "configure", "get_manager"]
