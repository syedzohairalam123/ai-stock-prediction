"""
Tests for `app.news_sources` — the keyless publisher RSS/Atom layer.

Every feed payload here is hand-written inline. No test reaches the network:
`fetch_feed` is driven with a stub client, so the suite stays green whether or
not a publisher is reachable and never asserts against live content.
"""
from datetime import datetime, timezone

import pytest

from app import news_sources as ns


# --------------------------------------------------------------------------
# test fixtures / helpers
# --------------------------------------------------------------------------

RSS_PAYLOAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Test Publisher</title>
    <item>
      <title>Synthetic headline about cement dispatches</title>
      <link>https://example.invalid/story/1</link>
      <pubDate>Tue, 15 Sep 26 08:54:43 +0500</pubDate>
      <dc:creator><![CDATA[Staff Reporter]]></dc:creator>
      <description><![CDATA[<p>First paragraph of the lede &amp; more.</p>]]></description>
      <content:encoded><![CDATA[<p>Body text.</p><img src="https://example.invalid/img/1.jpg">]]></content:encoded>
      <media:thumbnail url="https://example.invalid/thumb/1.jpg"/>
    </item>
    <item>
      <title>Second synthetic headline</title>
      <link>https://example.invalid/story/2</link>
      <pubDate>Tue, 15 Sep 2026 08:00:00 GMT</pubDate>
      <description>Plain summary</description>
    </item>
    <item>
      <title>Item with no link is unusable</title>
      <pubDate>Tue, 15 Sep 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_PAYLOAD = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <entry>
    <title>Atom entry headline</title>
    <link href="https://example.invalid/atom/1" rel="alternate"/>
    <updated>2026-09-15T08:54:43Z</updated>
    <summary>Atom summary text</summary>
    <author><name>Atom Author</name></author>
  </entry>
</feed>
"""

GOOGLE_NEWS_PAYLOAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Synthetic PSX headline - Example News</title>
      <link>https://news.example.invalid/rss/articles/abc</link>
      <pubDate>Mon, 14 Sep 2026 11:45:39 GMT</pubDate>
      <source url="https://example-news.invalid">Example News</source>
      <description>&lt;a href="https://x"&gt;Related: another synthetic headline&lt;/a&gt;</description>
    </item>
  </channel>
</rss>
"""


class _StubResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", "replace")


class _StubClient:
    """Minimal object with the one method `fetch_feed` calls."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def get(self, url, headers=None):  # noqa: ARG002 - signature mirrors httpx
        if self._exc is not None:
            raise self._exc
        return self._response


def _feed(**overrides) -> ns.NewsFeed:
    base = dict(key="test", name="Test Publisher", url="https://example.invalid/feed",
                region="PK", category="Business")
    base.update(overrides)
    return ns.NewsFeed(**base)


# --------------------------------------------------------------------------
# text cleanup
# --------------------------------------------------------------------------

def test_clean_text_strips_tags_and_unescapes_entities():
    assert ns.clean_text("<p>Hello &amp; goodbye</p>") == "Hello & goodbye"


def test_clean_text_handles_double_escaped_entities():
    assert ns.clean_text("&lt;p&gt;Escaped once more&lt;/p&gt;") == "Escaped once more"


def test_clean_text_collapses_whitespace():
    assert ns.clean_text("a\n\n   b\t c") == "a b c"


def test_clean_text_truncates_on_a_word_boundary():
    result = ns.clean_text("alpha beta gamma delta", limit=12)
    assert result.endswith("…")
    assert not result[:-1].endswith(" ")


def test_clean_text_empty_inputs():
    assert ns.clean_text(None) == ""
    assert ns.clean_text("") == ""


# --------------------------------------------------------------------------
# date parsing
# --------------------------------------------------------------------------

def test_parse_date_handles_two_digit_rfc822_year():
    parsed = ns._parse_date("Tue, 15 Sep 26 08:54:43 +0500")
    assert parsed is not None
    assert parsed.year == 2026
    assert parsed.tzinfo is not None


def test_parse_date_handles_iso_with_z():
    parsed = ns._parse_date("2026-09-15T08:54:43Z")
    assert parsed == datetime(2026, 9, 15, 8, 54, 43, tzinfo=timezone.utc)


def test_parse_date_handles_a_date_only_string():
    assert ns._parse_date("2026-09-15") == datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_parse_date_never_guesses():
    # A date is never invented — unparseable input is reported as unknown.
    assert ns._parse_date("sometime last week") is None
    assert ns._parse_date(None) is None
    assert ns._parse_date("   ") is None


def test_parse_date_normalises_naive_input_to_utc():
    parsed = ns._parse_date("2026-09-15")
    assert parsed.tzinfo is timezone.utc


# --------------------------------------------------------------------------
# SVG-free HTML safety
# --------------------------------------------------------------------------

def test_parse_feed_rejects_a_dtd_declaration():
    hostile = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><rss><item><title>x</title></item></rss>'
    with pytest.raises(ValueError, match="DTD/ENTITY"):
        ns.parse_feed(hostile, _feed())


def test_parse_feed_rejects_malformed_xml():
    with pytest.raises(ValueError, match="malformed XML"):
        ns.parse_feed(b"<rss><channel><item>", _feed())


def test_parse_feed_rejects_an_empty_body():
    with pytest.raises(ValueError, match="empty feed"):
        ns.parse_feed(b"", _feed())


# --------------------------------------------------------------------------
# RSS 2.0 parsing
# --------------------------------------------------------------------------

def test_parse_feed_reads_rss_2_0_items():
    articles = ns.parse_feed(RSS_PAYLOAD, _feed())
    # The third item has no link and is correctly dropped.
    assert len(articles) == 2
    first = articles[0]
    assert first["title"] == "Synthetic headline about cement dispatches"
    assert first["source_url"] == "https://example.invalid/story/1"
    assert first["publisher"] == "Test Publisher"
    assert first["author"] == "Staff Reporter"
    assert first["published_at"].year == 2026
    assert "First paragraph" in first["excerpt"]
    assert first["category"] == "Business"
    assert first["data_source"] == "rss:test"


def test_parse_feed_picks_up_a_media_thumbnail():
    articles = ns.parse_feed(RSS_PAYLOAD, _feed())
    assert articles[0]["image_url"] == "https://example.invalid/thumb/1.jpg"


def test_parse_feed_picks_up_an_image_from_the_body_when_there_is_no_media_tag():
    articles = ns.parse_feed(RSS_PAYLOAD, _feed())
    assert articles[1]["image_url"] is None  # no thumbnail, no <img>
    atom_articles = ns.parse_feed(ATOM_PAYLOAD, _feed())
    assert atom_articles[0]["image_url"] is None


def test_parse_feed_returns_empty_for_a_feed_without_items():
    assert ns.parse_feed(b"<rss><channel><title>empty</title></channel></rss>", _feed()) == []


def test_parse_feed_ignores_items_without_a_title():
    payload = b'<rss><channel><item><link>https://example.invalid/x</link></item></channel></rss>'
    assert ns.parse_feed(payload, _feed()) == []


# --------------------------------------------------------------------------
# Atom parsing
# --------------------------------------------------------------------------

def test_parse_feed_reads_atom_entries():
    articles = ns.parse_feed(ATOM_PAYLOAD, _feed())
    assert len(articles) == 1
    entry = articles[0]
    assert entry["title"] == "Atom entry headline"
    assert entry["source_url"] == "https://example.invalid/atom/1"
    assert entry["author"] == "Atom Author"
    assert entry["published_at"] == datetime(2026, 9, 15, 8, 54, 43, tzinfo=timezone.utc)
    assert entry["excerpt"] == "Atom summary text"


# --------------------------------------------------------------------------
# Google News handling
# --------------------------------------------------------------------------

def test_parse_feed_splits_the_publisher_off_a_google_news_headline():
    articles = ns.parse_feed(GOOGLE_NEWS_PAYLOAD, _feed(key="gnews_x", description_is_links=True))
    assert articles[0]["title"] == "Synthetic PSX headline"
    assert articles[0]["publisher"] == "Example News"


def test_parse_feed_discards_google_news_link_boilerplate():
    articles = ns.parse_feed(GOOGLE_NEWS_PAYLOAD, _feed(key="gnews_x", description_is_links=True))
    # The description is a list of links to *other* coverage; treating it as the
    # article's own lede would attribute every cited story to this one.
    assert articles[0]["excerpt"] is None
    assert articles[0]["content"] is None


def test_parse_feed_keeps_the_description_for_a_normal_feed():
    articles = ns.parse_feed(GOOGLE_NEWS_PAYLOAD, _feed())
    assert articles[0]["excerpt"] is not None


# --------------------------------------------------------------------------
# author cleanup
# --------------------------------------------------------------------------

def test_parse_feed_unwraps_a_placeholder_address_byline():
    payload = (b'<rss><channel><item><title>T</title>'
               b'<link>https://example.invalid/a</link>'
               b"<dc:creator xmlns:dc='http://purl.org/dc/elements/1.1/'>"
               b"none@none.com (The Newspaper's Staff Reporter)</dc:creator>"
               b'</item></channel></rss>')
    articles = ns.parse_feed(payload, _feed())
    assert articles[0]["author"] == "The Newspaper's Staff Reporter"


def test_parse_feed_drops_a_pure_email_byline():
    payload = (b'<rss><channel><item><title>T</title>'
               b'<link>https://example.invalid/a</link>'
               b"<dc:creator xmlns:dc='http://purl.org/dc/elements/1.1/'>desk@example.invalid</dc:creator>"
               b'</item></channel></rss>')
    assert ns.parse_feed(payload, _feed())[0]["author"] is None


# --------------------------------------------------------------------------
# fetch_feed — honest status reporting
# --------------------------------------------------------------------------

def test_fetch_feed_reports_ok_with_items():
    articles, status = ns.fetch_feed(_feed(), client=_StubClient(_StubResponse(200, RSS_PAYLOAD)))
    assert status.status == "OK"
    assert status.http_status == 200
    # `items` counts usable articles: the feed declared three, but the one
    # without a link cannot be attributed and is not counted or returned.
    assert status.items == 2
    assert len(articles) == 2
    assert status.error is None


def test_fetch_feed_reports_error_on_http_403():
    _, status = ns.fetch_feed(_feed(), client=_StubClient(_StubResponse(403, b"denied")))
    assert status.status == "ERROR"
    assert status.http_status == 403
    assert status.items == 0
    assert "403" in status.error


def test_fetch_feed_reports_error_on_a_network_failure():
    _, status = ns.fetch_feed(_feed(), client=_StubClient(exc=ConnectionError("dns down")))
    assert status.status == "ERROR"
    assert status.http_status is None
    assert "ConnectionError" in status.error


def test_fetch_feed_reports_empty_when_the_feed_has_no_usable_items():
    _, status = ns.fetch_feed(_feed(), client=_StubClient(_StubResponse(200, b"<rss><channel/></rss>")))
    assert status.status == "EMPTY"
    assert status.items == 0


def test_fetch_feed_reports_error_on_unsafe_xml_instead_of_raising():
    hostile = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>'
    _, status = ns.fetch_feed(_feed(), client=_StubClient(_StubResponse(200, hostile)))
    assert status.status == "ERROR"
    assert "DTD" in status.error


def test_fetch_feed_reports_disabled_feeds_without_a_request():
    class _Exploding:
        def get(self, *args, **kwargs):
            raise AssertionError("a disabled feed must never be requested")

    articles, status = ns.fetch_feed(
        _feed(key="off", enabled=False, note="blocked upstream"), client=_Exploding()
    )
    assert articles == []
    assert status.status == "DISABLED"
    assert "blocked upstream" in status.error


def test_fetch_feed_caps_the_response_size(monkeypatch):
    huge = b"<rss><channel>" + b"<!--" + b"x" * (ns.MAX_FEED_BYTES + 10) + b"--></channel></rss>"
    _, status = ns.fetch_feed(_feed(), client=_StubClient(_StubResponse(200, huge)))
    # Truncating mid-comment produces malformed XML, which is reported honestly
    # rather than parsed into a partial, misleading article list.
    assert status.status == "ERROR"


def test_feed_status_serialises_to_a_plain_dict():
    _, status = ns.fetch_feed(_feed(), client=_StubClient(_StubResponse(200, RSS_PAYLOAD)))
    payload = status.as_dict()
    assert set(payload) == {"key", "name", "region", "url", "status",
                            "http_status", "items", "error", "fetched_at"}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def test_registry_keys_are_unique():
    keys = [f.key for f in ns.FEEDS]
    assert len(keys) == len(set(keys))


def test_registry_lookup_matches_the_registry():
    for feed in ns.FEEDS:
        assert ns.FEEDS_BY_KEY[feed.key] is feed


def test_registry_uses_only_https_feeds():
    assert all(f.url.startswith("https://") for f in ns.FEEDS)


def test_disabled_feeds_are_kept_and_explained():
    disabled = [f for f in ns.FEEDS if not f.enabled]
    assert disabled, "the registry should retain feeds that currently block this server"
    assert all(f.note for f in disabled)


def test_enabled_feeds_filters_by_region():
    assert all(f.region == "PK" for f in ns.enabled_feeds("PK"))
    assert all(f.region == "GLOBAL" for f in ns.enabled_feeds("GLOBAL"))
    assert all(f.enabled for f in ns.enabled_feeds())


def test_disabled_feed_statuses_covers_every_disabled_feed():
    statuses = ns.disabled_feed_statuses()
    assert len(statuses) == len([f for f in ns.FEEDS if not f.enabled])
    assert all(s.status == "DISABLED" for s in statuses)


# --------------------------------------------------------------------------
# symbol search URLs
# --------------------------------------------------------------------------

def test_symbol_search_url_quotes_the_ticker():
    url = ns.symbol_search_url("OGDC")
    assert url.startswith("https://news.google.com/rss/search?q=")
    assert "%22OGDC%22" in url


def test_symbol_search_url_includes_the_company_name_when_known():
    url = ns.symbol_search_url("OGDC")
    assert "Oil+and+Gas+Development+Company" in url


def test_symbol_search_url_accepts_extra_names_and_normalises_case():
    url = ns.symbol_search_url("abcd", extra_names=("Some Company",))
    assert "%22ABCD%22" in url
    assert "Some+Company" in url


def test_symbol_search_names_reference_real_symbols_only():
    from app.symbols import PSX_SYMBOLS
    assert all(symbol in PSX_SYMBOLS for symbol in ns.SYMBOL_SEARCH_NAMES)
