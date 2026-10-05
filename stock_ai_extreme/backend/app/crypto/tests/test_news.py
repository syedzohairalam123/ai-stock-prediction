"""Crypto news module tests (additive feature).

All network I/O is mocked at the feed seam (:func:`app.news_sources.fetch_feed`)
so the suite stays offline and deterministic — exactly like the provider tests.
The live path is covered separately by ``test_real_data_trace.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import news_sources
from app.crypto import news


def _status(feed: news_sources.NewsFeed, status: str, *, items: int = 0, error=None):
    return news_sources.FeedStatus(
        feed.key, feed.name, feed.region, feed.url, status, items=items, error=error
    )


def _article(url: str, title: str, *, age_hours: float = 0.0, publisher: str = "Example"):
    return {
        "title": title,
        "publisher": publisher,
        "published_at": datetime.now(timezone.utc) - timedelta(hours=age_hours),
        "source_url": url,
        "image_url": None,
        "excerpt": None,
        "category": "Crypto",
    }


def test_search_url_quotes_ticker_and_name_and_anchors_crypto():
    url = news.search_url("BTC", "Bitcoin")
    assert url.startswith("https://news.google.com/rss/search?q=")
    assert "%22BTC%22" in url  # ticker quoted
    assert "%22Bitcoin%22" in url  # name quoted
    assert "crypto" in url
    assert "hl=en-US" in url and "ceid=US:en" in url


def test_search_url_omits_duplicate_name_term():
    url = news.search_url("BNB", "BNB")
    assert url.count("%22BNB%22") == 1


def test_news_view_normalizes_sorts_and_dedupes(monkeypatch):
    feed_status = None

    def fake_fetch(feed, *, timeout=12.0, client=None):
        nonlocal feed_status
        feed_status = _status(feed, "OK", items=4)
        return (
            [
                _article("https://a.example/1", "older", age_hours=10),
                _article("https://a.example/2", "newest", age_hours=0.1),
                _article("https://a.example/1", "duplicate url", age_hours=1),
                _article("https://a.example/3", "middle", age_hours=3),
            ],
            feed_status,
        )

    monkeypatch.setattr(news_sources, "fetch_feed", fake_fetch)
    import asyncio

    result = asyncio.run(news.news_view("BTC", "Bitcoin", limit=10))

    assert result["status"] == "OK"
    assert result["count"] == 3  # duplicate url removed
    assert [a["title"] for a in result["articles"]] == ["newest", "middle", "older"]
    assert all(a["source"] == "google-news" for a in result["articles"])
    assert all(a["origin"] == "SOURCE" for a in result["articles"])
    assert result["feed"]["status"] == "OK"


def test_news_view_respects_limit(monkeypatch):
    def fake_fetch(feed, *, timeout=12.0, client=None):
        return (
            [_article(f"https://a.example/{i}", f"h{i}", age_hours=float(i)) for i in range(10)],
            _status(feed, "OK", items=10),
        )

    monkeypatch.setattr(news_sources, "fetch_feed", fake_fetch)
    import asyncio

    result = asyncio.run(news.news_view("ETH", "Ethereum", limit=3))
    assert result["count"] == 3
    assert result["returned"] == 3


def test_news_view_empty_reports_reason_without_fabricating(monkeypatch):
    def fake_fetch(feed, *, timeout=12.0, client=None):
        return [], _status(feed, "EMPTY", error="feed parsed but contained no usable items")

    monkeypatch.setattr(news_sources, "fetch_feed", fake_fetch)
    import asyncio

    result = asyncio.run(news.news_view("SOL", "Solana"))
    assert result["status"] == "EMPTY"
    assert result["count"] == 0
    assert result["articles"] == []
    assert result["reason"]  # a real reason, not an invented story


def test_news_view_error_is_unavailable(monkeypatch):
    def fake_fetch(feed, *, timeout=12.0, client=None):
        return [], _status(feed, "ERROR", error="HTTP 503")

    monkeypatch.setattr(news_sources, "fetch_feed", fake_fetch)
    import asyncio

    result = asyncio.run(news.news_view("BTC", "Bitcoin"))
    assert result["status"] == "ERROR"
    assert result["articles"] == []
    assert "503" in result["reason"]


def test_data_mode_reflects_article_age():
    now = datetime.now(timezone.utc)
    assert news._data_mode(now) == "LIVE"
    assert news._data_mode(now - timedelta(days=30)) == "STALE"
    assert news._data_mode(None) == "UNKNOWN"


def test_normalize_drops_items_without_title_or_url(monkeypatch):
    def fake_fetch(feed, *, timeout=12.0, client=None):
        bad = [
            {"title": "", "source_url": "https://a.example/x", "published_at": datetime.now(timezone.utc)},
            {"title": "ok headline", "source_url": "", "published_at": datetime.now(timezone.utc)},
            {"title": "kept", "source_url": "https://a.example/kept", "published_at": datetime.now(timezone.utc)},
        ]
        return bad, _status(feed, "OK", items=3)

    monkeypatch.setattr(news_sources, "fetch_feed", fake_fetch)
    import asyncio

    result = asyncio.run(news.news_view("BTC", "Bitcoin"))
    assert result["count"] == 1
    assert result["articles"][0]["title"] == "kept"
