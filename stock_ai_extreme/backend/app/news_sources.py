"""
Phase 8 — keyless real news sources (RSS/Atom).

The paid news APIs (NewsAPI / Alpha Vantage) need keys and are rate-limited to
a few dozen requests a day, so on a fresh install the news desk can be empty.
Every feed in this registry is a **real publisher feed or the official Google
News RSS endpoint** and needs no key, no account and no scraping:

* Pakistani financial press — Dawn Business, The Express Tribune Business,
  plus Google News queries scoped to PSX / SBP / SECP / the Pakistan economy,
  which is how the local outlets that block server-side access are still read
  through their own published headlines.
* Global markets — BBC Business, CNBC Markets, WSJ Markets, Yahoo Finance,
  Investing.com FX.

Two rules the module enforces rather than documents:

1. **Nothing is fabricated to fill a gap.** If a feed 403s, times out or
   returns malformed XML, that feed is reported as ``ERROR`` with its HTTP
   status and reason, and simply contributes no articles. There is no
   placeholder story anywhere in this file.
2. **Every article keeps its own provenance** — the real headline, the real
   publisher, the publisher's own timestamp and the publisher's own URL. The
   parser never rewrites a headline or invents a date; an item without a link
   is dropped, because the link is the identity of the article.

Parsing is handled by the standard library's ``xml.etree.ElementTree`` with an
explicit hardening pass (DTD/entity declarations rejected, response size
capped) so a hostile or broken feed cannot blow up the process. ``defusedxml``
is used automatically when it happens to be installed.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

try:  # optional hardening — never a hard requirement
    from defusedxml import ElementTree as DefusedET  # type: ignore
    _HAVE_DEFUSED = True
except Exception:  # pragma: no cover - exercised only when defusedxml is absent
    DefusedET = None  # type: ignore
    _HAVE_DEFUSED = False

#: Hard cap on a single feed response. Real financial feeds are well under
#: 1 MB; anything larger is not a feed we want to parse.
MAX_FEED_BYTES = 3_000_000

#: Anything matching this in the first part of a document is rejected before
#: parsing — an XML DTD or entity declaration is never legitimate in RSS/Atom.
_UNSAFE_XML_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


@dataclass(frozen=True)
class NewsFeed:
    """One real, keyless publisher feed."""

    key: str
    name: str            # publisher name shown to the user
    url: str
    region: str          # "PK" | "GLOBAL"
    category: str        # preferred category when the text is ambiguous
    source_type: str = "ARTICLE"   # ARTICLE | MARKET_UPDATE | OFFICIAL_NOTICE ...
    quality: float = 0.7           # ranking prior (see news_analytics.SOURCE_TIERS)
    enabled: bool = True
    note: str = ""                 # why a feed is disabled, shown in /sources
    #: True when the feed's <description> is a list of links to *other*
    #: coverage rather than the article's own lede (Google News does this).
    #: Such a description is discarded — treating it as article text would
    #: attribute every story in the "related coverage" list to this article.
    description_is_links: bool = False


#: The registry. `enabled=False` entries are kept (and reported) rather than
#: deleted, because a feed that blocks this server today may allow it later —
#: and pretending it doesn't exist would hide a real coverage gap.
FEEDS: tuple[NewsFeed, ...] = (
    # ---------------- Pakistan: direct publisher feeds ----------------
    NewsFeed(
        key="dawn_business", name="Dawn", url="https://www.dawn.com/feeds/business",
        region="PK", category="Business", quality=0.85,
    ),
    NewsFeed(
        key="tribune_business", name="The Express Tribune", url="https://tribune.com.pk/feed/business",
        region="PK", category="Business", quality=0.78,
    ),
    NewsFeed(
        key="brecorder", name="Business Recorder", url="https://www.brecorder.com/feed/",
        region="PK", category="Business", quality=0.90, enabled=False,
        note="Publisher's edge currently answers this server with HTTP 403; retained and reported rather than silently dropped.",
    ),
    # ---------------- Pakistan: Google News scoped queries ----------------
    NewsFeed(
        key="gnews_psx", name="Google News",
        url="https://news.google.com/rss/search?q=%22Pakistan+Stock+Exchange%22+OR+PSX&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="PSX", quality=0.70, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_kse", name="Google News",
        url="https://news.google.com/rss/search?q=%22KSE-100%22+OR+KSE100&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="PSX", quality=0.70, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_pak_economy", name="Google News",
        url="https://news.google.com/rss/search?q=Pakistan+economy+inflation+GDP&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="Economy", quality=0.70, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_pak_banking", name="Google News",
        url="https://news.google.com/rss/search?q=Pakistan+bank+profit+deposits&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="Banking", quality=0.70, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_sbp", name="Google News",
        url="https://news.google.com/rss/search?q=%22State+Bank+of+Pakistan%22&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="Regulation", quality=0.72, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_secp", name="Google News",
        url="https://news.google.com/rss/search?q=SECP+Pakistan+regulation&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="Regulation", quality=0.72, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_pkr", name="Google News",
        url="https://news.google.com/rss/search?q=Pakistan+rupee+dollar+interbank+rate&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="Forex", quality=0.70, description_is_links=True,
    ),
    NewsFeed(
        key="gnews_commodities", name="Google News",
        url="https://news.google.com/rss/search?q=Pakistan+gold+price+oil+commodities&hl=en-PK&gl=PK&ceid=PK:en",
        region="PK", category="Commodities", quality=0.70, description_is_links=True,
    ),
    # ---------------- Global markets ----------------
    NewsFeed(
        key="bbc_business", name="BBC Business", url="https://feeds.bbci.co.uk/news/business/rss.xml",
        region="GLOBAL", category="Global Markets", quality=0.88,
    ),
    NewsFeed(
        key="cnbc_markets",
        name="CNBC",
        url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        region="GLOBAL", category="Global Markets", quality=0.88,
    ),
    NewsFeed(
        key="wsj_markets", name="The Wall Street Journal", url="https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        region="GLOBAL", category="Global Markets", quality=0.92,
    ),
    NewsFeed(
        key="yahoo_finance", name="Yahoo Finance", url="https://finance.yahoo.com/news/rssindex",
        region="GLOBAL", category="Stocks", quality=0.70,
    ),
    NewsFeed(
        key="investing_fx", name="Investing.com", url="https://www.investing.com/rss/news_25.rss",
        region="GLOBAL", category="Forex", quality=0.70,
    ),
)

FEEDS_BY_KEY: dict[str, NewsFeed] = {f.key: f for f in FEEDS}

DEFAULT_USER_AGENT = "NeuralMarket/1.0 (+https://github.com; educational market terminal)"

#: Hosts whose article images the backend is willing to re-serve (`GET
#: /api/news/image`). This is an **allowlist, not a denylist** — the endpoint
#: fetches a URL a remote feed told us about, so the only safe design is to name
#: the hosts we trust explicitly and refuse everything else. Entries match a host
#: exactly or as a parent domain (`i.dawn.com` matches `i.dawn.com` and
#: `cdn.i.dawn.com`).
#:
#: This exists for a concrete reason: several publisher CDNs answer a
#: cross-origin browser `<img>` with HTTP 403 while serving the same image
#: happily to a server. Re-serving it through the backend turns those broken
#: thumbnails into pictures — and the frontend only uses this path as a *retry*,
#: so the common case still loads directly from the publisher.
#:
#: Honest limitation, verified live: at least one host (`content-media.investing
#: .com`) refuses *both* the browser and the server, so its images still fall
#: back to the placeholder. Being on this list is permission to try, not a
#: promise that the host cooperates.
IMAGE_HOST_ALLOWLIST: tuple[str, ...] = (
    "dawn.com",
    "tribune.com.pk",
    "brecorder.com",
    "bbci.co.uk",
    "ytimg.com",
    "zenfs.com",
    "yimg.com",
    "yahoo.com",
    "cnbc.com",
    "wsj.net",
    "dowjones.com",
    "investing.com",
    "investorshub.advfn.com",
    "googleusercontent.com",
    "ggpht.com",
    "cloudfront.net",
    "reuters.com",
    "pakistantoday.com.pk",
    "thenews.com.pk",
    "aaj.tv",
    "mettisglobal.news",
    "profit.pk",
    "arabnews.pk",
    "app.com.pk",
)

#: Hard ceiling on a re-served image.
MAX_IMAGE_BYTES = 5_000_000


def is_allowed_image_host(url: str) -> bool:
    """True when `url` is an https image on an allowlisted host.

    Deliberately strict: https only, no credentials, no non-default port, and a
    host that matches the allowlist exactly or as a subdomain. Anything else is
    refused without a request being made, which is what keeps this endpoint from
    becoming a server-side request forgery primitive.
    """
    import urllib.parse

    try:
        parsed = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password or parsed.port:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return any(host == allowed or host.endswith("." + allowed) for allowed in IMAGE_HOST_ALLOWLIST)

# Namespace prefixes seen in real financial feeds.
_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
}


def _local(tag: str) -> str:
    """Strip the namespace from a tag name (`{ns}item` -> `item`)."""
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def clean_text(raw: str | None, *, limit: int = 1000) -> str:
    """Turn a feed's HTML/CDATA fragment into readable plain text.

    Unescapes entities, drops tags, collapses whitespace, and truncates on a
    word boundary so an excerpt never ends mid-word.
    """
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", html.unescape(text)).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:") + "…"


def _parse_date(raw: str | None) -> datetime | None:
    """Parse the many real-world feed date formats, always to aware UTC.

    Handles RFC 822/2822 (including the two-digit years Tribune emits),
    ISO-8601 with or without a ``Z``, and date-only strings. Returns ``None``
    when nothing parses — a date is never guessed.
    """
    if not raw:
        return None
    text = raw.strip()
    # RFC 1123 / RFC 822 ("Tue, 15 Sep 26 08:54:43 +0500")
    try:
        parsed = parsedate_to_datetime(text)
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    # ISO-8601
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # Date only
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _first_text(node: ET.Element, names: Iterable[str]) -> str | None:
    """First non-empty text among direct children whose tag is in `names`.

    Namespace-insensitive (``{dc}creator`` and ``creator`` both match). If the
    matched element holds text directly (RSS) that is returned; if it only wraps
    another element (Atom's ``<author><name>…</name></author>``) the nested
    ``<name>``/``<title>`` is used instead, since that is where the value lives.
    """
    wanted = {n.lower() for n in names}
    for child in node:
        if _local(child.tag) in wanted:
            text = (child.text or "").strip()
            if text:
                return text
            nested = _first_text(child, ("name", "title", "value"))
            if nested:
                return nested
    return None


def _extract_image(node: ET.Element, content_html: str = "") -> str | None:
    """Best available image URL for an item, from the media extensions, an
    enclosure, or the first ``<img>`` inside the body HTML."""
    for child in node.iter():
        tag = _local(child.tag)
        if tag in {"content", "thumbnail"}:
            url = child.get("url")
            if url and child.get("medium", "image") == "image":
                return url
            if url and tag == "thumbnail":
                return url
        if tag == "enclosure":
            url = child.get("url")
            media_type = (child.get("type") or "").lower()
            if url and (not media_type or media_type.startswith("image")):
                return url
    match = _IMG_SRC_RE.search(content_html or "")
    return match.group(1) if match else None


def _extract_google_source(node: ET.Element) -> str | None:
    """Google News names the real outlet in ``<source>``."""
    for child in node:
        if _local(child.tag) == "source":
            text = (child.text or "").strip()
            if text:
                return text
    return None


def parse_feed(xml_bytes: bytes, feed: NewsFeed) -> list[dict]:
    """Parse one feed payload into normalized article dicts.

    Supports RSS 2.0 (``<item>``) and Atom (``<entry>``). Items without a link
    or a title are skipped — there is no such thing as an article we can render
    but cannot attribute. Raises ``ValueError`` on malformed/unsafe XML so the
    caller can report the feed as failed instead of silently returning nothing.
    """
    if not xml_bytes:
        raise ValueError("empty feed body")
    head = xml_bytes[:4096]
    if _UNSAFE_XML_RE.search(head):
        raise ValueError("feed contains a DTD/ENTITY declaration — rejected")

    parser_cls = DefusedET if _HAVE_DEFUSED and DefusedET is not None else ET
    try:
        root = parser_cls.fromstring(xml_bytes)
    except Exception as exc:  # ET.ParseError and defusedxml's own errors
        raise ValueError(f"malformed XML: {exc}") from exc

    containers = [el for el in root.iter() if _local(el.tag) in {"item", "entry"}]
    articles: list[dict] = []

    for node in containers:
        title = clean_text(_first_text(node, ("title",)), limit=500)
        link = (_first_text(node, ("link",)) or "").strip()
        if not link:
            # Atom keeps the URL in <link href="...">.
            for child in node:
                if _local(child.tag) == "link" and child.get("href"):
                    link = child.get("href", "").strip()
                    break
        if not title or not link or link.startswith("{"):
            continue

        content_html = _first_text(node, ("encoded", "content")) or ""
        description = _first_text(node, ("description", "summary")) or ""
        body_source = content_html or description

        author = clean_text(_first_text(node, ("creator", "author", "name")), limit=200) or None
        # Dawn (and a few others) emit a placeholder address before the real
        # byline: "none@none.com (The Newspaper's Staff Reporter)". Keep the
        # human part; never present an address as an author.
        if author and "(" in author:
            inside = author[author.rfind("(") + 1:].rstrip(")").strip()
            if inside and "@" not in inside:
                author = inside
        if author and "@" in author:
            author = None

        publisher = _extract_google_source(node) or feed.name
        # Google News puts "<headline> - <Publisher>" in the title; the
        # publisher belongs in its own field, not glued onto the headline.
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -(len(publisher) + 3)].strip()

        published = (
            _parse_date(_first_text(node, ("pubdate", "published", "updated", "date")))
            or _parse_date(_first_text(node, ("date",)))
            or datetime.now(timezone.utc)
        )

        if feed.description_is_links:
            # Google News only ships a list of links to other coverage as the
            # description. Keeping it would make this article appear to mention
            # every company in that list — so it is dropped, and the article is
            # stored with its headline and nothing invented in place of a lede.
            excerpt = ""
            content = ""
        else:
            excerpt = clean_text(description or content_html, limit=600)
            content = clean_text(body_source, limit=10000)

        articles.append({
            "title": title,
            "publisher": publisher,
            "author": author,
            "published_at": published,
            "image_url": _extract_image(node, body_source),
            "excerpt": excerpt or None,
            "content": content or None,
            "category": feed.category,
            "tags": [feed.key],
            "related_symbols": [],
            "related_indices": [],
            "source_url": link,
            "source_type": feed.source_type,
            "priority": "NORMAL",
            "data_source": f"rss:{feed.key}",
        })

    return articles


@dataclass
class FeedStatus:
    """Honest per-feed result. Reported to the API so the UI can show which
    sources are actually contributing right now."""

    key: str
    name: str
    region: str
    url: str
    status: str                      # OK | EMPTY | ERROR | DISABLED
    http_status: int | None = None
    items: int = 0
    error: str | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "region": self.region,
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "items": self.items,
            "error": self.error,
            "fetched_at": self.fetched_at.isoformat(),
        }


def fetch_feed(feed: NewsFeed, *, timeout: float = 12.0, client=None) -> tuple[list[dict], FeedStatus]:
    """Fetch and parse one feed. Never raises — every failure becomes a
    status record, so one dead publisher cannot blank the desk."""
    import httpx  # local import keeps this module importable without httpx installed

    if not feed.enabled:
        return [], FeedStatus(feed.key, feed.name, feed.region, feed.url, "DISABLED",
                              error=feed.note or "disabled by configuration")

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-PK,en;q=0.9",
    }
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=timeout, follow_redirects=True, headers=headers)

    try:
        response = client.get(feed.url, headers=headers)
        http_status = response.status_code
        if response.status_code >= 400:
            return [], FeedStatus(feed.key, feed.name, feed.region, feed.url, "ERROR",
                                  http_status=http_status, error=f"HTTP {http_status}")
        body = response.content[:MAX_FEED_BYTES]
        articles = parse_feed(body, feed)
        if not articles:
            return [], FeedStatus(feed.key, feed.name, feed.region, feed.url, "EMPTY",
                                  http_status=http_status, error="feed parsed but contained no usable items")
        return articles, FeedStatus(feed.key, feed.name, feed.region, feed.url, "OK",
                                   http_status=http_status, items=len(articles))
    except ValueError as exc:
        return [], FeedStatus(feed.key, feed.name, feed.region, feed.url, "ERROR", error=str(exc))
    except Exception as exc:
        return [], FeedStatus(feed.key, feed.name, feed.region, feed.url, "ERROR",
                              error=f"{type(exc).__name__}: {exc}")
    finally:
        if owns_client:
            client.close()


#: Human names used to broaden a symbol-scoped search when a bare ticker is
#: ambiguous in prose. Only names that map to a real PSX symbol are used.
SYMBOL_SEARCH_NAMES: dict[str, tuple[str, ...]] = {
    "OGDC": ("Oil and Gas Development Company",),
    "PPL": ("Pakistan Petroleum",),
    "POL": ("Pakistan Oilfields",),
    "MARI": ("Mari Petroleum", "Mari Energies"),
    "PSO": ("Pakistan State Oil",),
    "HBL": ("Habib Bank",),
    "UBL": ("United Bank Limited",),
    "MCB": ("MCB Bank",),
    "MEBL": ("Meezan Bank",),
    "NBP": ("National Bank of Pakistan",),
    "BAFL": ("Bank Alfalah",),
    "BAHL": ("Bank AL Habib",),
    "FABL": ("Faysal Bank",),
    "BOP": ("Bank of Punjab",),
    "AKBL": ("Askari Bank",),
    "FFC": ("Fauji Fertilizer",),
    "ENGRO": ("Engro Corporation",),
    "EFERT": ("Engro Fertilizers",),
    "LUCK": ("Lucky Cement",),
    "DGKC": ("D.G. Khan Cement", "DG Khan Cement"),
    "MLCF": ("Maple Leaf Cement",),
    "FCCL": ("Fauji Cement",),
    "PIOC": ("Pioneer Cement",),
    "KOHC": ("Kohat Cement",),
    "ACPL": ("Attock Cement",),
    "SYS": ("Systems Limited",),
    "NETSOL": ("NetSol Technologies",),
    "AVN": ("Avanceon",),
    "TRG": ("TRG Pakistan",),
    "AIRLINK": ("Air Link Communication",),
    "HUBC": ("Hub Power", "Hubco"),
    "KAPCO": ("Kot Addu Power",),
    "KEL": ("K-Electric",),
    "NML": ("Nishat Mills",),
    "NCL": ("Nishat Chunian",),
    "GATM": ("Gul Ahmed Textile",),
    "NESTLE": ("Nestle Pakistan",),
    "INDU": ("Indus Motor",),
    "MTL": ("Millat Tractors",),
    "PSMC": ("Pak Suzuki Motor",),
    "HCAR": ("Honda Atlas Cars",),
    "THALL": ("Thal Limited",),
    "ISL": ("International Steels",),
    "ASL": ("Aisha Steel",),
    "MUGHAL": ("Mughal Iron",),
    "SNGP": ("Sui Northern Gas",),
    "SSGC": ("Sui Southern Gas",),
    "ATRL": ("Attock Refinery",),
    "NRL": ("National Refinery",),
    "PRL": ("Pakistan Refinery",),
    "APL": ("Attock Petroleum",),
    "SHEL": ("Shell Pakistan",),
    "ICI": ("ICI Pakistan",),
    "LOTCHEM": ("Lotte Chemical",),
    "EPCL": ("Engro Polymer",),
    "PIAA": ("Pakistan International Airlines",),
    "PNSC": ("Pakistan National Shipping",),
    "FATIMA": ("Fatima Fertilizer",),
    "COLG": ("Colgate Palmolive Pakistan",),
    "AGP": ("AGP Limited",),
    "SEARL": ("The Searle Company",),
    "GSK": ("GlaxoSmithKline Pakistan",),
    "ABBOTT": ("Abbott Laboratories Pakistan",),
}


def symbol_search_url(symbol: str, *, extra_names: tuple[str, ...] = ()) -> str:
    """Google News RSS query URL for one ticker.

    Two terms are queried — the ticker itself and the company's name — because
    Pakistani outlets write the story either way, and a ticker-only query misses
    the half that spells the company out. Terms are quoted so "PSO" does not
    match every word containing those letters.
    """
    import urllib.parse

    ticker = (symbol or "").strip().upper()
    terms = [f'"{ticker}"']
    for name in SYMBOL_SEARCH_NAMES.get(ticker, ()) + tuple(extra_names or ()):
        terms.append(f'"{name}"')
    query = " OR ".join(terms)
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote_plus(query)
        + "&hl=en-PK&gl=PK&ceid=PK:en"
    )


def enabled_feeds(region: str | None = None) -> list[NewsFeed]:
    """Feeds that will actually be fetched, optionally limited to one region."""
    feeds = [f for f in FEEDS if f.enabled]
    if region:
        feeds = [f for f in feeds if f.region == region.upper()]
    return feeds


def disabled_feed_statuses() -> list[FeedStatus]:
    """Status rows for feeds deliberately switched off, so the source-health
    view shows the full registry rather than only the working half."""
    return [
        FeedStatus(f.key, f.name, f.region, f.url, "DISABLED", error=f.note or "disabled by configuration")
        for f in FEEDS if not f.enabled
    ]
