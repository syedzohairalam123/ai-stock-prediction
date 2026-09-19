"""
Tests for the news image proxy and the background news-ingestion job.

The proxy endpoint fetches a URL that a remote feed told us about, so its
security properties are the interesting part and are what these tests pin down:
https only, an explicit host allowlist, no credentials/ports, an image
content-type, and a size cap — all enforced *before* or *around* the outbound
request, never after.

No test here reaches the network: the fetch seam is replaced with a stub.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import news_sources as ns


@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    init_db()
    return TestClient(app)


# --------------------------------------------------------------------------
# is_allowed_image_host — the SSRF guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://i.dawn.com/large/2026/09/x.webp",
    "https://ichef.bbci.co.uk/images/ic/1024x576/x.jpg",
    "https://cdn.i.dawn.com/x.jpg",              # subdomain of an allowed parent
    "https://content-media.investing.com/news/x.jpg",
    "https://media.zenfs.com/en/x.jpg",
])
def test_allowed_image_host_accepts_allowlisted_hosts(url):
    assert ns.is_allowed_image_host(url) is True


@pytest.mark.parametrize("url", [
    "http://i.dawn.com/x.jpg",                    # not https
    "https://evil.example.com/x.jpg",             # unknown host
    "https://notdawn.com/x.jpg",                  # looks similar, is not
    "https://127.0.0.1/x.jpg",                    # loopback
    "https://localhost/x.jpg",
    "https://user:pass@i.dawn.com/x.jpg",         # embedded credentials
    "https://i.dawn.com:8443/x.jpg",              # non-default port
    "file:///etc/passwd",
    "",
    None,
])
def test_allowed_image_host_rejects_everything_else(url):
    assert ns.is_allowed_image_host(url) is False


def test_allowlist_entries_are_bare_hostnames():
    # A scheme or slash in the list would make the suffix check meaningless.
    assert all("/" not in host and ":" not in host for host in ns.IMAGE_HOST_ALLOWLIST)


# --------------------------------------------------------------------------
# NewsService.fetch_image
# --------------------------------------------------------------------------

class _ImageResponse:
    def __init__(self, status_code=200, content=b"\x89PNG\r\n", content_type="image/png"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


def _service_with(response=None, exc=None):
    """A NewsService whose HTTP client is a stub.

    The stub's `get` is a **sync** mock on purpose: `fetch_image` runs the
    blocking httpx call through `asyncio.to_thread`, so an ``AsyncMock`` here
    would hand back an un-awaited coroutine instead of a response and every
    assertion would fail for the wrong reason.
    """
    from app.news_service import NewsService

    service = NewsService()
    fake = MagicMock()
    if exc is not None:
        fake.side_effect = exc
    else:
        fake.return_value = response
    service.session = type("S", (), {"get": fake, "close": lambda self: None})()
    return service, fake


def test_fetch_image_refuses_a_non_allowlisted_host_without_a_request():
    import asyncio
    service, fake = _service_with(_ImageResponse())
    with pytest.raises(ValueError, match="allowlist"):
        asyncio.run(service.fetch_image("https://evil.example.com/x.jpg"))
    assert fake.call_count == 0  # refused before any outbound request


def test_fetch_image_returns_content_type_and_bytes():
    import asyncio
    service, _ = _service_with(_ImageResponse(content=b"abc", content_type="image/jpeg"))
    content_type, body = asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))
    assert content_type == "image/jpeg"
    assert body == b"abc"


def test_fetch_image_strips_charset_from_the_content_type():
    import asyncio
    service, _ = _service_with(_ImageResponse(content_type="image/webp; charset=binary"))
    content_type, _ = asyncio.run(service.fetch_image("https://i.dawn.com/x.webp"))
    assert content_type == "image/webp"


def test_fetch_image_rejects_a_non_image_content_type():
    import asyncio
    service, _ = _service_with(_ImageResponse(content_type="text/html"))
    with pytest.raises(RuntimeError, match="not an image"):
        asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))


def test_fetch_image_rejects_a_missing_content_type():
    import asyncio
    service, _ = _service_with(_ImageResponse(content_type=""))
    with pytest.raises(RuntimeError, match="not an image"):
        asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))


def test_fetch_image_rejects_an_oversized_body():
    import asyncio
    oversized = b"x" * (ns.MAX_IMAGE_BYTES + 1)
    service, _ = _service_with(_ImageResponse(content=oversized))
    with pytest.raises(RuntimeError, match="size limit"):
        asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))


def test_fetch_image_rejects_an_empty_body():
    import asyncio
    service, _ = _service_with(_ImageResponse(content=b""))
    with pytest.raises(RuntimeError, match="empty body"):
        asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))


def test_fetch_image_surfaces_an_upstream_failure():
    import asyncio
    service, _ = _service_with(_ImageResponse(status_code=403))
    with pytest.raises(RuntimeError, match="HTTP 403"):
        asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))


def test_fetch_image_caches_a_successful_fetch():
    import asyncio
    service, fake = _service_with(_ImageResponse(content=b"cached"))
    asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))
    asyncio.run(service.fetch_image("https://i.dawn.com/x.jpg"))
    assert fake.call_count == 1  # the second call is served from the cache


# --------------------------------------------------------------------------
# the route
# --------------------------------------------------------------------------

def test_image_route_rejects_a_non_allowlisted_url(client):
    response = client.get("/api/news/image", params={"url": "https://evil.example.com/x.jpg"})
    assert response.status_code == 400
    assert "allowlist" in response.json()["detail"]


def test_image_route_requires_a_url(client):
    assert client.get("/api/news/image").status_code == 422


def test_image_route_returns_the_image_bytes(client):
    with patch("app.news_service.NewsService.fetch_image",
               new=AsyncMock(return_value=("image/png", b"\x89PNG-bytes"))):
        response = client.get("/api/news/image", params={"url": "https://i.dawn.com/x.png"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG-bytes"
    assert "max-age" in response.headers.get("cache-control", "")


def test_image_route_maps_an_upstream_failure_to_502(client):
    with patch("app.news_service.NewsService.fetch_image",
               new=AsyncMock(side_effect=RuntimeError("upstream returned HTTP 403"))):
        response = client.get("/api/news/image", params={"url": "https://i.dawn.com/x.png"})
    assert response.status_code == 502
    assert "403" in response.json()["detail"]


def test_image_route_is_not_shadowed_by_the_article_route(client):
    # `/api/news/{article_id}` is int-typed; if it were registered first this
    # would be a 422 instead of the proxy's own 400.
    response = client.get("/api/news/image", params={"url": "https://evil.example.com/x.jpg"})
    assert response.status_code == 400


# --------------------------------------------------------------------------
# background news ingestion job
# --------------------------------------------------------------------------

def test_ingest_news_calls_the_service_and_reports_a_count():
    import asyncio
    from app import jobs

    with patch("app.jobs.get_news_service") as service_factory, \
         patch("app.jobs.session_scope"):
        service = service_factory.return_value
        service.aggregate_and_store = AsyncMock(return_value=7)
        jobs._last_news_ingest = 0.0
        stored = asyncio.run(jobs.ingest_news(force=True))
    assert stored == 7


def test_ingest_news_is_throttled_by_the_configured_interval():
    import asyncio
    import time as _time
    from app import jobs

    with patch("app.jobs.get_news_service") as service_factory:
        service = service_factory.return_value
        service.aggregate_and_store = AsyncMock(return_value=3)
        jobs._last_news_ingest = _time.monotonic()  # just ran
        assert asyncio.run(jobs.ingest_news()) == 0
        assert service.aggregate_and_store.await_count == 0


def test_ingest_news_returns_zero_when_no_source_is_enabled():
    import asyncio
    from app import jobs
    from app.config import settings

    with patch.object(settings, "news_rss_enabled", False), \
         patch.object(settings, "newsapi_key", None), \
         patch.object(settings, "finnhub_api_key", None), \
         patch.object(settings, "alpha_vantage_key", None):
        jobs._last_news_ingest = 0.0
        assert asyncio.run(jobs.ingest_news(force=True)) == 0


def test_ingest_news_swallows_a_failure_without_marking_the_interval():
    import asyncio
    from app import jobs

    with patch("app.jobs.get_news_service") as service_factory, \
         patch("app.jobs.session_scope"):
        service = service_factory.return_value
        service.aggregate_and_store = AsyncMock(side_effect=RuntimeError("boom"))
        jobs._last_news_ingest = 0.0
        assert asyncio.run(jobs.ingest_news(force=True)) == 0
    # A failure must not consume the interval — the next tick should retry.
    assert jobs._last_news_ingest == 0.0
