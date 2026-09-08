"""
Tests for Phase 10 news + lexicon sentiment:
  - the pure sentiment scorer (no network)
  - the aggregate roll-up
  - the provider fetch (yfinance mocked at the same seam as other provider tests)
  - the manager news() cache/fallback path
  - the route end-to-end with mocked provider
"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.news import analyze_news, score_text


# ---------- pure sentiment scorer ----------

def test_score_text_bullish_headline():
    s = score_text("Apple shares surge to record high after earnings beat")
    assert s["label"] == "bullish"
    assert s["score"] > 0
    assert s["positive_words"] > 0


def test_score_text_bearish_headline():
    s = score_text("Bank plunges after fraud probe and downgrade")
    assert s["label"] == "bearish"
    assert s["score"] < 0


def test_score_text_neutral_headline():
    s = score_text("Company announces quarterly report date")
    assert s["label"] == "neutral"
    assert s["score"] == 0.0
    assert s["positive_words"] == 0 and s["negative_words"] == 0


def test_score_text_case_insensitive_and_strips_punctuation():
    s = score_text("RALLIES! BEAT expectations, then CRASHED.")
    # "rallies", "beat" positive; "crashed" negative -> net positive
    assert s["score"] > 0


# ---------- aggregate ----------

def _items(titles):
    return [{"title": t, "publisher": "TestWire", "link": "https://example.com", "published_at": None} for t in titles]


def test_analyze_news_scores_every_item_and_rolls_up():
    report = analyze_news(_items(["Stock surges to record", "Stock plunges to new low", "Nothing special here"]))
    assert len(report["items"]) == 3
    assert all("sentiment" in i for i in report["items"])
    agg = report["aggregate"]
    assert agg["total"] == 3
    assert agg["bullish_count"] + agg["bearish_count"] + agg["neutral_count"] == 3
    assert agg["label"] in ("bullish", "bearish", "neutral")
    assert -1.0 <= agg["average_score"] <= 1.0
    assert "disclaimer" in report


def test_analyze_news_empty_feed_returns_zeroed_aggregate():
    report = analyze_news([])
    assert report["items"] == []
    assert report["aggregate"]["total"] == 0
    assert report["aggregate"]["label"] == "neutral"


def test_analyze_news_missing_title_does_not_crash():
    report = analyze_news([{"publisher": "X"}])
    assert report["items"][0]["sentiment"]["label"] == "neutral"


# ---------- provider fetch (yfinance mocked) ----------

class _FakeTicker:
    """Real stand-in for yf.Ticker — `.news` is a property, so the MagicMock
    'attribute access doesn't fire side_effect' trap doesn't apply."""
    def __init__(self, news_value):
        self._news_value = news_value

    @property
    def news(self):
        if callable(self._news_value):
            return self._news_value()
        return self._news_value


def _patch_ticker(news_value):
    return patch("app.providers.yfinance_provider.yf.Ticker", side_effect=lambda _t: _FakeTicker(news_value))


def test_yfinance_provider_normalizes_news_items():
    from app.providers.yfinance_provider import YFinanceProvider

    raw = [
        {"title": "Great news", "publisher": "Yahoo", "link": "https://x", "providerPublishTime": 1700000000, "type": "STORY"},
        {"title": "Bad news", "publisher": "Yahoo", "link": "https://y"},
    ]
    with _patch_ticker(raw):
        items = asyncio_run(YFinanceProvider(max_retries=1).get_news("AAPL"))
    assert len(items) == 2
    assert items[0]["published_at"] is not None  # timestamp normalized to ISO
    assert items[1]["published_at"] is None      # missing timestamp stays None


def test_yfinance_provider_empty_news_is_not_an_error():
    from app.providers.yfinance_provider import YFinanceProvider

    with _patch_ticker([]):
        items = asyncio_run(YFinanceProvider(max_retries=1).get_news("AAPL"))
    assert items == []


def test_yfinance_provider_raises_provider_error_on_fetch_failure():
    from app.providers.yfinance_provider import ProviderError, YFinanceProvider

    with _patch_ticker(lambda: (_ for _ in ()).throw(ConnectionError("down"))):
        with pytest.raises(ProviderError):
            asyncio_run(YFinanceProvider(max_retries=1).get_news("AAPL"))


def test_yfinance_provider_handles_new_nested_content_format():
    """yfinance switched from flat items to a nested `content` block — this
    locks in that the normalizer reads the new shape correctly."""
    from app.providers.yfinance_provider import YFinanceProvider

    raw = [{
        "id": "abc",
        "content": {
            "title": "Apple surges on record earnings",
            "contentType": "STORY",
            "pubDate": "2026-09-08T08:48:00Z",
            "provider": {"displayName": "Sky News"},
            "clickThroughUrl": {"url": "https://example.com/story"},
        },
    }]
    with _patch_ticker(raw):
        items = asyncio_run(YFinanceProvider(max_retries=1).get_news("AAPL"))
    assert items[0]["title"] == "Apple surges on record earnings"
    assert items[0]["publisher"] == "Sky News"
    assert items[0]["link"] == "https://example.com/story"
    assert items[0]["published_at"].startswith("2026-09-08")
    assert items[0]["type"] == "STORY"


def test_normalize_published_accepts_epoch_and_iso():
    from app.providers.yfinance_provider import YFinanceProvider

    p = YFinanceProvider()
    assert p._normalize_published(1700000000).startswith("2023-11")
    assert p._normalize_published("2026-09-08T08:48:00Z").startswith("2026-09-08")
    assert p._normalize_published("weird-value") == "weird-value"  # passthrough, never drops the item
    assert p._normalize_published(None) is None


# ---------- manager news() ----------

def test_manager_news_caches_and_reports_status():
    from app.providers.base import DataStatus
    from app.providers.manager import MarketDataManager

    provider = MagicMock()
    provider.name = "fake"
    provider.is_configured.return_value = True
    provider.get_news = AsyncMock(return_value=[{"title": "Headline"}])

    manager = MarketDataManager(providers=[provider])
    items, source, status = asyncio_run(manager.news("AAPL"))
    assert items == [{"title": "Headline"}]
    assert source == "fake" and status == DataStatus.LIVE

    # second call serves from cache with CACHED status, provider not hit again
    items2, _, status2 = asyncio_run(manager.news("AAPL"))
    assert status2 == DataStatus.CACHED
    assert provider.get_news.await_count == 1


def test_manager_news_empty_list_is_cached_as_valid_answer():
    from app.providers.base import DataStatus
    from app.providers.manager import MarketDataManager

    provider = MagicMock()
    provider.name = "fake"
    provider.is_configured.return_value = True
    provider.get_news = AsyncMock(return_value=[])
    manager = MarketDataManager(providers=[provider])
    items, _, status = asyncio_run(manager.news("AAPL"))
    assert items == [] and status == DataStatus.LIVE


def test_manager_news_all_providers_failing_raises():
    from app.providers.base import ProviderError
    from app.providers.manager import MarketDataManager

    provider = MagicMock()
    provider.name = "fake"
    provider.is_configured.return_value = True
    provider.get_news = AsyncMock(side_effect=ProviderError("fake", "boom"))
    manager = MarketDataManager(providers=[provider])
    with pytest.raises(ProviderError):
        asyncio_run(manager.news("AAPL"))


# ---------- route ----------

@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    init_db()
    return TestClient(app)


def test_news_route_returns_analyzed_items(client):
    raw = [{"title": "Tech stock surges on strong earnings", "publisher": "Yahoo", "link": "https://x", "providerPublishTime": 1700000000, "type": "STORY"}]
    # distinct ticker per test: the manager's news cache is shared across the
    # test session, so reusing the same ticker would serve stale cached items
    with _patch_ticker(raw):
        resp = client.get("/api/stocks/NEWSOK/news")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["source"] == "yfinance"
    assert len(body["items"]) == 1
    assert body["items"][0]["sentiment"]["label"] == "bullish"
    assert "aggregate" in body and "disclaimer" in body


def test_news_route_empty_feed_still_200(client):
    with _patch_ticker([]):
        resp = client.get("/api/stocks/NEWSEMPTY/news")
    assert resp.status_code == 200
    assert resp.json()["aggregate"]["total"] == 0


def test_news_route_400_when_provider_down(client):
    with _patch_ticker(lambda: (_ for _ in ()).throw(ConnectionError("down"))):
        resp = client.get("/api/stocks/NEWSDOWN/news")
    assert resp.status_code == 400


def test_news_route_rejects_invalid_ticker(client):
    resp = client.get("/api/stocks/not a ticker!!/news")
    assert resp.status_code == 400


# small helper to run one coroutine in this sync test module
def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)