"""
Phase 13 — server-side search (BM25 Okapi).

The client's `searchGlobal` is a fast substring matcher over the bundled PSX
metadata. This endpoint adds a *ranked* server path on top of it, reusing the
news desk's `BM25Index` (same probabilistic retrieval the article search uses)
so a query with a company's full name, a partial name, or a small typo still
finds the right ticker.

Corpus (all real, none invented)
    * every ticker in `symbols.PSX_SYMBOLS`, with the company aliases from
      `news_analytics.COMPANY_ALIASES` as its body text;
    * the four headline PSX indices.

The client keeps its local search as the primary, instant path and consults this
endpoint for ranking/typo tolerance, falling back locally if the server is down.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import repository as repo
from .logging_config import get_logger
from .news_analytics import BM25Index, COMPANY_ALIASES
from .symbols import PSX_SYMBOLS

logger = get_logger("neural_market.search")

router = APIRouter(prefix="/api/search", tags=["Search"])

#: Real PSX headline indices the terminal links to elsewhere.
INDICES: dict[str, str] = {
    "KSE100": "KSE 100 Index",
    "KSE30": "KSE 30 Index",
    "KMI30": "KMI 30 Index",
    "ALLSHR": "All Share Index",
}


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=120)
    limit: int = Field(default=20, ge=1, le=100)
    includeWatchlist: bool = True


def _alias_index() -> dict[str, list[str]]:
    """ticker -> [company names] inverted from the entity linker's alias table."""
    by_ticker: dict[str, list[str]] = defaultdict(list)
    for name, ticker in COMPANY_ALIASES.items():
        by_ticker[ticker].append(name)
    return by_ticker


def build_corpus() -> tuple[list[tuple[int, str, str]], dict[int, dict[str, Any]]]:
    """Build the BM25 documents + their metadata.

    Doc ids are dense integers (BM25Index keys on ints); `meta` maps each back
    to the public result shape.
    """
    aliases = _alias_index()
    documents: list[tuple[int, str, str]] = []
    meta: dict[int, dict[str, Any]] = {}
    doc_id = 0

    for symbol in sorted(PSX_SYMBOLS):
        names = aliases.get(symbol, [])
        documents.append((doc_id, symbol, " ".join(names)))
        meta[doc_id] = {
            "id": f"stock-{symbol}",
            "type": "stock",
            "symbol": symbol,
            "name": names[0].title() if names else symbol,
        }
        doc_id += 1

    for symbol, name in INDICES.items():
        documents.append((doc_id, f"{symbol} {name}", "psx market index benchmark"))
        meta[doc_id] = {"id": f"index-{symbol}", "type": "index", "symbol": symbol, "name": name}
        doc_id += 1

    return documents, meta


def _watchlist_documents(meta: dict[int, dict[str, Any]], documents: list[tuple[int, str, str]]) -> None:
    """Append any watchlisted symbols not already in the corpus (real user data)."""
    known = {entry["symbol"] for entry in meta.values()}
    doc_id = len(documents)
    for item in repo.list_watchlist():
        symbol = str(item.get("ticker") or "").upper()
        if not symbol or symbol in known:
            continue
        documents.append((doc_id, symbol, item.get("note") or ""))
        meta[doc_id] = {"id": f"stock-{symbol}", "type": "stock", "symbol": symbol, "name": symbol}
        known.add(symbol)
        doc_id += 1


def search(query: str, limit: int = 20, include_watchlist: bool = True) -> list[dict[str, Any]]:
    """Rank matches for `query` with BM25 (+ fuzzy term expansion)."""
    documents, meta = build_corpus()
    if include_watchlist:
        try:
            _watchlist_documents(meta, documents)
        except Exception as exc:  # DB hiccup must not break search
            logger.debug("watchlist corpus skipped: %s", exc)

    index = BM25Index(documents)
    ranked = index.search(query, top_n=limit, fuzzy=True)

    results: list[dict[str, Any]] = []
    for doc_id, score in ranked:
        entry = meta.get(doc_id)
        if entry is None:
            continue
        results.append({**entry, "score": round(float(score), 4), "source": "SERVER_BM25"})
    return results


@router.post("")
def search_route(body: SearchRequest):
    """POST /api/search — ranked symbol/index suggestions."""
    try:
        results = search(body.query, limit=body.limit, include_watchlist=body.includeWatchlist)
        return {"query": body.query, "results": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("search failed: %s", exc)
        raise HTTPException(500, "Search is temporarily unavailable.")


@router.get("")
def search_get_route(q: str, limit: int = 20):
    """GET /api/search?q=... convenience form for quick checks."""
    return search_route(SearchRequest(query=q, limit=limit))
