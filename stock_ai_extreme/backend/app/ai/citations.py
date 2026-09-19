"""
Citation extraction (Phase 10, spec T)

Turns the context that was actually sent to the model into a list of the
records the answer may legitimately cite. The UI shows this list under each
answer, so the reader can audit what the assistant was given.

Rules honoured here:
  - a citation is derived from a real stored/retrieved record, never invented;
  - no URL is synthesized — the source field is copied as-is when present;
  - unavailable data produces no citation at all (silence, not filler).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Upper bound on how many sources a single answer may list.
MAX_CITATIONS = 12


def _add(
    citations: List[Dict[str, Any]],
    seen: set,
    *,
    kind: str,
    title: str,
    source: Optional[str] = None,
    published_at: Optional[str] = None,
    url: Optional[str] = None,
    symbol: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Append a citation once. Blank titles are dropped rather than faked."""
    if not title or not str(title).strip():
        return

    key = (kind, str(title).strip().lower())
    if key in seen:
        return
    seen.add(key)

    citations.append(
        {
            "kind": kind,
            "title": str(title).strip(),
            "source": source or None,
            "published_at": published_at or None,
            "url": url if (url and str(url).startswith(("http://", "https://"))) else None,
            "symbol": symbol or None,
            "detail": detail or None,
        }
    )


def _quote_citation(citations: List[Dict[str, Any]], seen: set, block: Dict[str, Any], symbol: str) -> None:
    """Cite the live quote that grounded a price statement."""
    price = block.get("price", block.get("last"))
    if price is None:
        return

    detail_bits = [f"price {price}"]
    if block.get("previous_close") is not None:
        detail_bits.append(f"previous close {block['previous_close']}")
    if block.get("change_percent") is not None:
        detail_bits.append(f"day change {block['change_percent']:+.2f}%")
    if block.get("last_date"):
        detail_bits.append(f"as of {block['last_date']}")
    if block.get("market_status"):
        detail_bits.append(f"session {block['market_status']}")

    _add(
        citations,
        seen,
        kind="quote",
        title=f"{symbol} market quote",
        source="provider layer (yfinance)",
        published_at=block.get("last_date"),
        detail=", ".join(detail_bits),
        symbol=symbol,
    )


def _surfaces(citations: List[Dict[str, Any]], seen: set, block: Dict[str, Any], symbol: str) -> None:
    """Cite stored news, filings and the sentiment reading for one symbol."""
    for item in block.get("recent_news") or []:
        _add(
            citations,
            seen,
            kind="news",
            title=item.get("title", ""),
            source=item.get("publisher") or item.get("source"),
            published_at=item.get("published_at"),
            url=item.get("url") or item.get("source_url"),
            symbol=symbol,
            detail=(f"sentiment {item.get('sentiment')}" if item.get("sentiment") else None),
        )

    for announcement in block.get("recent_announcements") or []:
        _add(
            citations,
            seen,
            kind="announcement",
            title=announcement.get("title", ""),
            source=announcement.get("company") or "PSX announcement",
            published_at=announcement.get("date"),
            url=announcement.get("url"),
            symbol=symbol,
            detail=announcement.get("type") or None,
        )

    sentiment = block.get("sentiment")
    if isinstance(sentiment, dict) and sentiment.get("label") and sentiment.get("source"):
        score = sentiment.get("score")
        count = sentiment.get("article_count")
        detail_bits = []
        if score is not None:
            detail_bits.append(f"score {score:+.2f}")
        if count is not None:
            detail_bits.append(f"{count} items")
        if sentiment.get("confidence") is not None:
            detail_bits.append(f"confidence {sentiment['confidence']:.2f}")
        _add(
            citations,
            seen,
            kind="sentiment",
            title=f"{symbol} headline sentiment",
            source=sentiment.get("source"),
            symbol=symbol,
            detail=", ".join(detail_bits) or None,
        )


def extract_citations(context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the answer's source list from the context that was sent.

    Returns a list capped at ``MAX_CITATIONS``; an empty list means the answer
    was grounded entirely in the supplied market data (which the prompt tells
    the model to state explicitly).
    """
    if not context:
        return []

    citations: List[Dict[str, Any]] = []
    seen: set = set()

    symbol = context.get("symbol") or ""

    # Stock / index surfaces
    for key, entity in (("stock_context", context.get("stock_context")), ("index_context", context.get("index_context"))):
        if isinstance(entity, dict):
            entity_symbol = entity.get("symbol") or symbol
            _quote_citation(citations, seen, entity, entity_symbol)
            _surfaces(citations, seen, entity, entity_symbol)

    # Index-level market state (spec R: market tone must be attributable)
    market = context.get("market_context")
    if isinstance(market, dict):
        for index_name, index_data in (market.get("indices") or {}).items():
            if not isinstance(index_data, dict) or index_data.get("last") is None:
                continue
            detail = (
                f"last {index_data['last']}, day change "
                f"{index_data.get('change_percent', 0):+.2f}%"
                if index_data.get("change_percent") is not None
                else f"last {index_data['last']}"
            )
            _add(
                citations,
                seen,
                kind="market",
                title=f"{index_name} index",
                source="provider layer (yfinance)",
                detail=detail,
                symbol=index_name,
            )

    # News desk headlines
    news_context = context.get("news_context")
    if isinstance(news_context, dict):
        for headline in news_context.get("recent_headlines") or []:
            _add(
                citations,
                seen,
                kind="news",
                title=headline.get("title", ""),
                source=headline.get("publisher"),
                published_at=headline.get("published_at"),
                detail=headline.get("category") or None,
            )
        aggregate = news_context.get("aggregate_sentiment")
        if isinstance(aggregate, dict) and aggregate.get("label"):
            _add(
                citations,
                seen,
                kind="sentiment",
                title="Aggregate headline sentiment",
                source="news desk",
                detail=(
                    f"{aggregate.get('label')} (avg {aggregate.get('average_score', 0):+.2f}, "
                    f"{aggregate.get('bullish_count', 0)} bullish / "
                    f"{aggregate.get('bearish_count', 0)} bearish)"
                ),
            )

    # Portfolio (user-supplied records; never includes account identifiers)
    portfolio = context.get("portfolio_context")
    if isinstance(portfolio, dict) and "error" not in portfolio:
        _add(
            citations,
            seen,
            kind="portfolio",
            title="Your portfolio records",
            source="app database",
            detail=(
                f"{portfolio.get('positions_count', 0)} positions, "
                f"cost basis PKR {portfolio.get('total_cost_basis', 0):,.2f}"
            ),
        )

    return citations[:MAX_CITATIONS]


def summarise_citations(citations: List[Dict[str, Any]]) -> str:
    """One-line, log-safe summary of a citation list (no user data)."""
    if not citations:
        return "none"
    kinds: Dict[str, int] = {}
    for citation in citations:
        kinds[citation.get("kind", "other")] = kinds.get(citation.get("kind", "other"), 0) + 1
    return ", ".join(f"{kind}:{count}" for kind, count in sorted(kinds.items()))
