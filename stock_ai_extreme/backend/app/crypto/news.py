"""
Crypto news feed — real, keyless, per-asset headlines (additive).

Headlines come from **Google News RSS**, scoped to one asset by its ticker and
its published name, through the exact same keyless feed pipeline the rest of the
app uses (:mod:`app.news_sources`) — no new data source and no API key.

Honesty contract, identical to every other crypto surface:

  * every entry is a real headline the publisher emitted, attributed to its
    publisher and linked to its source URL;
  * a feed that fails or returns nothing is reported as ``EMPTY`` / ``ERROR``
    with the real reason — **no placeholder story is ever synthesised to fill
    the gap**;
  * ``data_mode`` is derived from the article's own publication time
    (LIVE / RECENT / STALE), so a week-old headline is never dressed up as live.

No summary, sentiment or "story" is generated here: this module transports what
the source published and nothing more.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional

from app import news_sources

logger = logging.getLogger("neural_market.crypto.news")

#: Human names that disambiguate a bare ticker in prose. Kept explicit for the
#: curated catalogue; an unknown symbol simply queries its ticker.
CRYPTO_SEARCH_NAMES: Dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "ADA": "Cardano",
    "AVAX": "Avalanche",
    "TRX": "TRON",
    "NEAR": "NEAR Protocol",
    "SUI": "Sui",
    "APT": "Aptos",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "POL": "Polygon",
    "IMX": "Immutable",
    "LINK": "Chainlink",
    "DOGE": "Dogecoin",
    "LTC": "Litecoin",
    "DOT": "Polkadot",
    "SHIB": "Shiba Inu",
}

#: Upper bound so a hostile query cannot pull an unbounded list.
MAX_ARTICLES = 50


def search_url(symbol: str, name: Optional[str] = None) -> str:
    """Google News RSS query URL for one asset.

    Terms are quoted so a short ticker (``OP``, ``ARB``) does not match every
    word containing those letters, and the word ``crypto`` anchors the query to
    the asset class.
    """
    ticker = (symbol or "").strip().upper()
    terms = [f'"{ticker}"']
    if name and name.strip().upper() != ticker:
        terms.append(f'"{name.strip()}"')
    query = "(" + " OR ".join(terms) + ") crypto"
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )


def _data_mode(published_at: Optional[datetime]) -> str:
    """Reuse the app's single freshness definition (never invent 'LIVE')."""
    from app.news_service import data_mode_for

    return data_mode_for(published_at)


def _normalize(article: Dict[str, Any], *, feed_key: str) -> Optional[Dict[str, Any]]:
    """One parsed feed item → the crypto news row shape, or ``None`` if unusable."""
    title = (article.get("title") or "").strip()
    url = (article.get("source_url") or "").strip()
    if not title or not url:
        return None
    published = article.get("published_at")
    published_dt = published if isinstance(published, datetime) else None
    return {
        "title": title,
        "url": url,
        "publisher": article.get("publisher") or "Google News",
        "author": article.get("author"),
        "published_at": published_dt.isoformat() if published_dt else None,
        "data_mode": _data_mode(published_dt),
        "image_url": article.get("image_url"),
        "excerpt": article.get("excerpt"),
        "category": article.get("category"),
        "source": "google-news",
        "feed": feed_key,
        "origin": "SOURCE",
    }


async def news_view(symbol: str, name: Optional[str] = None, *, limit: int = 20) -> Dict[str, Any]:
    """Fetch, normalize and rank real headlines for one asset.

    Blocking feed I/O runs off the event loop via ``asyncio.to_thread`` so one
    slow publisher cannot stall the API worker.
    """
    ticker = (symbol or "").strip().upper()
    resolved_name = (name or CRYPTO_SEARCH_NAMES.get(ticker) or ticker).strip()
    feed = news_sources.NewsFeed(
        key=f"gnews_crypto_{ticker.lower()}",
        name="Google News",
        url=search_url(ticker, resolved_name),
        region="GLOBAL",
        category="Crypto",
        quality=0.7,
        description_is_links=True,
    )

    try:
        articles, status = await asyncio.to_thread(news_sources.fetch_feed, feed, timeout=12.0)
    except Exception as exc:  # pragma: no cover - fetch_feed already isolates failures
        logger.warning("crypto news fetch failed for %s: %s", ticker, exc)
        articles, status = [], news_sources.FeedStatus(
            feed.key, feed.name, feed.region, feed.url, "ERROR", error=f"{type(exc).__name__}: {exc}"
        )

    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    for article in articles:
        row = _normalize(article, feed_key=feed.key)
        if row is None or row["url"] in seen:
            continue
        seen.add(row["url"])
        rows.append(row)

    rows.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    cap = max(1, min(int(limit), MAX_ARTICLES))
    rows = rows[:cap]

    available = status.status == "OK" and bool(rows)
    payload: Dict[str, Any] = {
        "symbol": ticker,
        "asset_name": resolved_name,
        "articles": rows,
        "count": len(rows),
        "returned": len(rows),
        "status": "OK" if available else ("EMPTY" if status.status == "OK" else status.status),
        "source": "google-news",
        "feed": status.as_dict(),
        "query": feed.url,
        "origin": "SOURCE",
    }
    if available:
        payload["note"] = (
            "Real headlines fetched live from Google News RSS, attributed to their publisher. "
            "Nothing is generated here: no summary, sentiment or story is invented."
        )
    else:
        payload["reason"] = (
            status.error or "Google News returned no usable headlines for this asset right now."
        )
    return payload
