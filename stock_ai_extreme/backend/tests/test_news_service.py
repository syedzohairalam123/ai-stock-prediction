"""
Phase 8 — News Backend Tests

Tests for news service, API routes, and database integration.

Every test here uses synthetic article text written inside the test — no test
depends on a live publisher, and no expected value is copied from a real
headline. Network-dependent paths are mocked at the module seam.
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from app.models import NewsArticle
from app.news_service import (
    NewsService, data_mode_for, _slugify, _extract_tickers, _categorize_article,
)


@pytest.fixture
def client():
    """FastAPI test client bound to the throwaway test database."""
    from app.db import init_db
    from app.main import app
    init_db()
    return TestClient(app)


@pytest.fixture
def test_db():
    """A live SQLAlchemy session, rolled back and closed after the test."""
    from app.db import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def test_slugify():
    """Test slug generation."""
    assert _slugify("Breaking News: PSX Hits Record High!") == "breaking-news-psx-hits-record-high"
    assert _slugify("Oil & Gas Development Company (OGDC)") == "oil-gas-development-company-ogdc"
    assert _slugify("HBL Announces 25% Dividend") == "hbl-announces-25-dividend"


def test_extract_tickers():
    """Test ticker extraction from text."""
    text = "OGDC and HBL reported strong earnings. PSO increased prices."
    tickers = _extract_tickers(text)
    assert "OGDC" in tickers
    assert "HBL" in tickers
    assert "PSO" in tickers
    assert len(tickers) == 3


def test_categorize_article():
    """Test article categorization."""
    assert _categorize_article("PSX index rises", "", "") == "PSX"
    assert _categorize_article("HBL announces dividend", "", "Habib Bank") == "Banking"
    assert _categorize_article("Dollar rate increases", "", "") == "Forex"
    assert _categorize_article("Gold prices surge", "", "") == "Commodities"
    assert _categorize_article("SECP issues new regulations", "", "") == "Regulation"
    assert _categorize_article("GDP growth report", "Pakistan economy", "") == "Economy"


def test_news_article_model(test_db):
    """Test NewsArticle model creation and retrieval."""
    article = NewsArticle(
        title="Test News Article",
        slug="test-news-article",
        publisher="Test Publisher",
        author="Test Author",
        published_at=datetime.now(timezone.utc),
        image_url="https://example.com/image.jpg",
        excerpt="This is a test excerpt",
        content="Full test content here",
        category="PSX",
        tags=["test", "news"],
        related_symbols=["OGDC", "HBL"],
        related_indices=["KSE100"],
        source_url="https://example.com/article",
        source_type="ARTICLE",
        priority="NORMAL",
        data_source="test",
        sentiment_score=0.5,
        sentiment_label="bullish"
    )
    
    test_db.add(article)
    test_db.commit()
    
    # Retrieve and verify
    retrieved = test_db.query(NewsArticle).filter(NewsArticle.slug == "test-news-article").first()
    assert retrieved is not None
    assert retrieved.title == "Test News Article"
    assert retrieved.category == "PSX"
    assert "OGDC" in retrieved.related_symbols
    assert retrieved.sentiment_label == "bullish"


def test_news_article_unique_source_url(test_db):
    """Test that duplicate source URLs are prevented."""
    article1 = NewsArticle(
        title="Article 1",
        slug="article-1",
        published_at=datetime.now(timezone.utc),
        category="PSX",
        related_symbols=[],
        related_indices=[],
        source_url="https://example.com/same-url",
        source_type="ARTICLE",
        priority="NORMAL",
        data_source="test"
    )
    test_db.add(article1)
    test_db.commit()
    
    # Try to add duplicate
    article2 = NewsArticle(
        title="Article 2",
        slug="article-2",
        published_at=datetime.now(timezone.utc),
        category="PSX",
        related_symbols=[],
        related_indices=[],
        source_url="https://example.com/same-url",  # Same URL
        source_type="ARTICLE",
        priority="NORMAL",
        data_source="test"
    )
    test_db.add(article2)
    
    with pytest.raises(Exception):  # Should raise integrity error
        test_db.commit()


def test_news_service_initialization():
    """Test NewsService can be initialized."""
    service = NewsService()
    assert service is not None
    assert hasattr(service, 'session')
    assert hasattr(service, '_cache')


def test_news_api_routes(client):
    """Test news API endpoints."""
    
    # Test /api/news/latest
    response = client.get("/api/news/latest?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "count" in data
    
    # Test /api/news/categories
    response = client.get("/api/news/categories")
    assert response.status_code == 200
    data = response.json()
    assert "categories" in data
    
    # Test /api/news/publishers
    response = client.get("/api/news/publishers")
    assert response.status_code == 200
    data = response.json()
    assert "publishers" in data
    
    # Test /api/news/hero
    response = client.get("/api/news/hero")
    assert response.status_code == 200
    data = response.json()
    assert "hero" in data


def test_news_search_filters(client):
    """Test news search with filters."""
    payload = {
        "category": "PSX",
        "page": 1,
        "page_size": 20
    }
    
    response = client.post("/api/news/search", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "pagination" in data
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["page_size"] == 20


def test_news_by_symbol(client):
    """Test fetching news by symbol (live fallback disabled — no network)."""
    response = client.get("/api/news/by-symbol/OGDC?limit=5&live=false")
    assert response.status_code == 200
    data = response.json()
    assert "symbol" in data
    assert data["symbol"] == "OGDC"
    assert "items" in data
    assert "count" in data
    assert "sentiment_aggregate" in data
    assert data["live_fallback_used"] is False


def test_news_by_symbol_rejects_empty_symbol(client):
    assert client.get("/api/news/by-symbol/%20?live=false").status_code == 400


# --------------------------------------------------------------------------
# freshness (spec J/K)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("age_hours,expected", [
    (0, "LIVE"),
    (5.9, "LIVE"),
    (7, "RECENT"),
    (71, "RECENT"),
    (200, "STALE"),
])
def test_data_mode_reflects_publisher_age(age_hours, expected):
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=age_hours)
    assert data_mode_for(published, now=now) == expected


def test_data_mode_unknown_without_timestamp():
    assert data_mode_for(None) == "UNKNOWN"


def test_data_mode_treats_naive_timestamp_as_utc():
    naive = datetime.now() - timedelta(minutes=5)
    assert data_mode_for(naive) == "LIVE"


# --------------------------------------------------------------------------
# enrichment + storage
# --------------------------------------------------------------------------

#: Deliberately synthetic text. Every substring here was written by hand; none
#: of it is copied from a real article, so the tests never assert against
#: published content.
_RAW_ARTICLE = {
    "title": "Acme Cement posts record quarterly profit",
    "publisher": "Test Wire",
    "published_at": datetime.now(timezone.utc),
    "source_url": "https://example.invalid/news/1",
    "source_type": "ARTICLE",
    "data_source": "rss:test_feed",
    "category": "Business",
    "related_symbols": [],
    "related_indices": [],
    "excerpt": "The company declared a final dividend and lifted guidance.",
}


def test_enrich_articles_adds_analytics_fields():
    service = NewsService()
    enriched = service.enrich_articles([dict(_RAW_ARTICLE)])[0]
    assert enriched["event_type"] == "DIVIDEND"
    assert isinstance(enriched["impact_score"], float)
    assert enriched["priority"] in {"HIGH", "NORMAL", "LOW"}
    assert enriched["data_mode"] == "LIVE"
    assert enriched["feed_key"] == "test_feed"
    assert enriched["simhash"]
    assert enriched["keywords"]
    assert enriched["sentiment_label"] in {"bullish", "bearish", "neutral"}
    assert enriched["word_count"] > 0
    assert enriched["reading_time_minutes"] >= 1


def test_enrich_articles_does_not_mutate_input():
    service = NewsService()
    original = dict(_RAW_ARTICLE)
    service.enrich_articles([original])
    assert original == _RAW_ARTICLE


def test_store_articles_dedupes_by_url_title_and_similarity(test_db):
    service = NewsService()

    def clean():
        test_db.query(NewsArticle).delete()
        test_db.commit()

    clean()
    try:
        first = service.enrich_articles([dict(_RAW_ARTICLE)])
        report = service.store_articles(test_db, first)
        assert report["stored"] == 1

        # 1) identical URL
        same_url = service.enrich_articles([dict(_RAW_ARTICLE)])
        assert service.store_articles(test_db, same_url)["duplicate_url"] == 1

        # 2) same headline, different publisher + URL
        duplicate_title = dict(_RAW_ARTICLE, source_url="https://example.invalid/news/2",
                               publisher="Other Wire")
        assert service.store_articles(test_db, service.enrich_articles([duplicate_title]))["duplicate_title"] == 1

        # 3) reworded headline with a heavily overlapping lede -> SimHash / title similarity
        near = dict(
            _RAW_ARTICLE,
            title="Acme Cement posts record quarterly profit, declares dividend",
            source_url="https://example.invalid/news/3",
            publisher="Third Wire",
        )
        report = service.store_articles(test_db, service.enrich_articles([near]))
        assert report["stored"] + report["near_duplicate"] + report["duplicate_title"] == 1

        # 4) genuinely different story is stored
        other = dict(
            _RAW_ARTICLE,
            title="Central bank holds the policy rate unchanged",
            excerpt="Monetary policy committee decision announced.",
            source_url="https://example.invalid/news/9",
        )
        assert service.store_articles(test_db, service.enrich_articles([other]))["stored"] == 1
    finally:
        clean()


# --------------------------------------------------------------------------
# new intelligence routes (spec F/G/I/M)
# --------------------------------------------------------------------------

def test_news_sources_route_reports_registry_and_health(client):
    body = client.get("/api/news/sources").json()
    assert body["summary"]["total_feeds"] == len(body["registry"])
    assert body["summary"]["enabled_feeds"] <= body["summary"]["total_feeds"]
    # Every feed row carries a real status string, even before the first ingest.
    assert all(s["status"] for s in body["sources"])


def test_news_stats_route_shape(client):
    body = client.get("/api/news/stats?hours=24").json()
    for key in ("total_articles", "articles_in_window", "publishers",
                "by_category", "by_event_type", "by_priority", "by_data_mode"):
        assert key in body
    assert body["window_hours"] == 24


def test_news_trending_route_shape(client):
    body = client.get("/api/news/trending?window_hours=48&top=5").json()
    assert body["window_hours"] == 48
    assert isinstance(body["entities"], list)
    assert "articles_considered" in body


def test_news_clusters_route_validates_threshold(client):
    assert client.post("/api/news/clusters", json={"threshold": 5}).status_code == 422
    body = client.post("/api/news/clusters", json={"window_hours": 24}).json()
    assert body["count"] == len(body["clusters"])


def test_related_news_404_for_unknown_article(client):
    assert client.get("/api/news/987654/related").status_code == 404


def test_search_rejects_invalid_sort(client):
    assert client.post("/api/news/search", json={"sort": "whatever"}).status_code == 422


def test_search_min_impact_and_event_type_filters(client):
    body = client.post("/api/news/search", json={"min_impact": 50, "event_type": "EARNINGS"}).json()
    assert body["filters_applied"]["min_impact"] == 50
    assert body["filters_applied"]["event_type"] == "EARNINGS"
    for item in body["items"]:
        assert (item["impact_score"] or 0) >= 50
        assert item["event_type"] == "EARNINGS"


def test_latest_news_exposes_data_mode(client):
    body = client.get("/api/news/latest?limit=5").json()
    for item in body["items"]:
        assert item["data_mode"] in {"LIVE", "RECENT", "STALE", "UNKNOWN"}


def test_hero_route_never_500s_on_empty_corpus(client):
    body = client.get("/api/news/hero").json()
    assert "hero" in body


def test_hero_route_returns_article_when_one_exists(client, test_db):
    article = NewsArticle(
        title="Synthetic hero candidate", slug="synthetic-hero-candidate",
        publisher="Test Wire", published_at=datetime.now(timezone.utc),
        category="PSX", related_symbols=[], related_indices=[],
        source_url="https://example.invalid/news/hero", source_type="ARTICLE",
        priority="HIGH", data_source="test", impact_score=99.0, data_mode="LIVE",
    )
    test_db.add(article)
    test_db.commit()
    try:
        body = client.get("/api/news/hero").json()
        assert body["hero"] is not None
        assert body["hero"]["title"]
    finally:
        test_db.query(NewsArticle).filter(NewsArticle.id == article.id).delete()
        test_db.commit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
