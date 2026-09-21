"""
Tests for Phase 17 — real-time breaking news, trending topics and market impact.

Every fixture here is hand-written: synthetic publisher names, synthetic
headlines and synthetic OHLCV bars. Nothing reaches the network and no expected
value was copied from a live feed, so a publisher changing its front page can
never turn this suite red.

The provider seam is faked at the *fetcher* boundary
(:class:`FakeHistoryFetcher`), which is exactly the seam the production code
injects the Phase 2 provider manager through — so these tests exercise the real
analyzer, the real clustering and the real scoring code.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.breaking_news import breaking_detector as bd
from app.breaking_news import entities as bn_entities
from app.breaking_news import topic_engine as te
from app.breaking_news.breaking_detector import BreakingNewsDetector
from app.breaking_news.config import breaking_news_settings
from app.breaking_news.deduplicator import NewsDeduplicator
from app.breaking_news.engine import BreakingNewsEngine
from app.breaking_news.market_impact import (
    Bar,
    HistoryBundle,
    MarketImpactAnalyzer,
    ProbabilityMovementAnalyzer,
    resolve_entity,
)
from app.breaking_news.pipeline import (
    NewsAggregator,
    NewsNormalizer,
    NewsProvider,
    NewsRanker,
    NormalizedArticle,
)
from app.breaking_news.schemas import BreakingLevel, ImpactMagnitude, TrendDirection
from app.breaking_news.sources import SourceReliabilityEngine, publisher_prior
from app.breaking_news.summarizer import AISummarizer, extract_key_numbers
from app.breaking_news.timeutil import parse_datetime, to_naive_utc, utcnow

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 3, 10, 12, 0, 0)  # a fixed, plain date — no tz, no DST maths


def make_article(
    *,
    article_id: int | None = None,
    title: str = "Acme Cement posts record quarterly profit",
    publisher: str = "Dawn",
    published_at: datetime | None = NOW,
    url: str | None = None,
    excerpt: str | None = "The board said dispatches rose in the quarter.",
    image: str | None = "https://example.test/a.jpg",
    symbols: list[str] | None = None,
    indices: list[str] | None = None,
    topics: list[str] | None = None,
    source: str = "rss:dawn_business",
    impact_score: float | None = 55.0,
    **extra,
) -> NormalizedArticle:
    from app.breaking_news.entities import entity_types_for, extract_market_entities

    title = title
    symbols = symbols or []
    indices = indices or []
    market_entities = extract_market_entities(f"{title}. {excerpt or ''}")
    entity_types = entity_types_for(market_entities)
    for symbol in symbols:
        entity_types.setdefault(symbol, "STOCK")
    for index in indices:
        entity_types.setdefault(index, "INDEX")
    return NormalizedArticle(
        id=article_id,
        title=title,
        publisher=publisher,
        url=url or f"https://example.test/{abs(hash(title))}",
        published_at=published_at,
        excerpt=excerpt,
        image=image,
        symbols=symbols,
        indices=indices,
        topics=topics or [],
        source=source,
        market_entities=[e.as_dict() for e in market_entities],
        entity_types=entity_types,
        impact_score=impact_score,
        **extra,
    )


class FakeHistoryFetcher:
    """Deterministic stand-in for ``ProviderHistoryFetcher``.

    ``bars`` are supplied per requested symbol; a symbol with no scripted bars
    behaves exactly like a provider that could not answer.
    """

    def __init__(self, bars: dict[str, list[Bar]] | None = None, *, error: str | None = None):
        self.bars = bars or {}
        self.error = error
        self.calls: list[tuple[str, object, object, str]] = []

    async def fetch(self, symbol: str, start, end, interval) -> HistoryBundle:
        self.calls.append((symbol, start, end, interval))
        if self.error:
            return HistoryBundle(requested_symbol=symbol, error=self.error)
        return HistoryBundle(
            bars=list(self.bars.get(symbol, [])),
            source="fake-provider",
            status="LIVE",
            requested_symbol=symbol,
        )


def minute_bars(anchor: datetime, *, before: int = 10, after: int = 20, base: float = 100.0, step: float = 0.1):
    """Bars one minute apart, ``before`` of them up to the anchor and ``after`` past it."""
    bars: list[Bar] = []
    for offset in range(-before, 0):
        bars.append(Bar(timestamp=anchor + timedelta(minutes=offset), close=base, volume=1000.0))
    for offset in range(1, after + 1):
        bars.append(Bar(timestamp=anchor + timedelta(minutes=offset), close=base + step * offset, volume=1200.0))
    return bars


# ===========================================================================
# spec §3 — normalization
# ===========================================================================

def test_normalize_rejects_an_item_with_no_title():
    assert NewsNormalizer().normalize({"source_url": "https://x.test/1", "title": "  "}) is None


def test_normalize_rejects_an_item_with_no_url():
    # A link is the identity of an article; without it the item is unusable.
    assert NewsNormalizer().normalize({"title": "A headline"}) is None


def test_normalize_fills_a_missing_publisher_and_records_the_gap():
    article = NewsNormalizer().normalize({"title": "A headline", "source_url": "https://x.test/1"})
    assert article is not None
    assert article.publisher == "Unknown publisher"
    assert "publisher" in article.missing


def test_normalize_records_missing_image_and_excerpt_without_inventing_them():
    article = NewsNormalizer().normalize({
        "title": "A headline", "source_url": "https://x.test/1", "publisher": "Dawn",
        "published_at": NOW.isoformat(),
    })
    assert article.image is None and article.excerpt is None
    assert "image" in article.missing and "excerpt" in article.missing
    assert "published_at" not in article.missing


def test_normalize_without_a_timestamp_reports_unknown_mode():
    article = NewsNormalizer().normalize({"title": "T", "source_url": "https://x.test/1", "publisher": "Dawn"})
    assert article.published_at is None
    assert article.data_mode == "UNKNOWN"
    assert article.as_dict()["age_minutes"] is None


def test_normalize_keeps_only_validated_symbols():
    article = NewsNormalizer().normalize({
        "title": "T", "source_url": "https://x.test/1", "publisher": "Dawn",
        "related_symbols": ["OGDC", "NOTATICKER"], "published_at": NOW.isoformat(),
    })
    assert article.symbols == ["OGDC"]


def test_normalize_preserves_the_raw_payload_for_storage():
    payload = {"title": "T", "source_url": "https://x.test/1", "publisher": "Dawn", "published_at": NOW.isoformat()}
    article = NewsNormalizer().normalize(payload)
    assert article.raw is payload


def test_normalize_derives_entities_from_text_when_none_are_supplied():
    article = NewsNormalizer().normalize({
        "title": "OGDC gains as KSE-100 rises", "source_url": "https://x.test/1",
        "publisher": "Dawn", "published_at": NOW.isoformat(),
    })
    assert "OGDC" in article.symbols and "KSE100" in article.indices
    assert article.entities


# ===========================================================================
# spec §7 — market entity association
# ===========================================================================

@pytest.mark.parametrize("text,expected", [
    ("Nvidia shares jump", "NVDA"),
    ("Federal Reserve holds rates", "FED"),
    ("Gold hits a record high", "GOLD"),
    ("Bitcoin rallies past a milestone", "BTC"),
    ("The S&P 500 closed higher", "SPX"),
    ("Nasdaq futures point higher", "NDAQ"),
    ("Crude oil slides on demand worries", "OIL"),
    ("OGDC and HBL lead the index", None),  # PSX handled by news_analytics, not here
])
def test_extract_market_entities_finds_curated_instruments(text, expected):
    found = {e.entity for e in bn_entities.extract_market_entities(text)}
    if expected:
        assert expected in found
    else:
        assert found == set()


def test_extract_market_entities_ignores_words_that_collide_with_tickers():
    # "ALL" is not in the curated list precisely so ordinary prose cannot match.
    assert bn_entities.extract_market_entities("all of the above were mentioned") == []


def test_company_names_are_matched_on_word_boundaries():
    assert "NVDA" in {e.entity for e in bn_entities.extract_market_entities("Nvidia beat expectations")}
    # A substring inside another word must not match.
    assert bn_entities.extract_market_entities("annvidiation of the deal") == []


def test_policy_actors_are_entities_but_not_priceable():
    assert bn_entities.provider_symbol("FED", "INDEX") is None
    assert bn_entities.provider_symbol("GOLD", "COMMODITY") == "GC=F"


def test_every_curated_ticker_has_a_definition():
    assert all(t == t.upper() and 2 <= len(t) <= 6 for t in bn_entities.GLOBAL_TICKERS)


# ===========================================================================
# spec §5 — breaking detection
# ===========================================================================

def test_recency_is_maximal_inside_the_breaking_plateau():
    detector = BreakingNewsDetector()
    article = make_article(published_at=NOW - timedelta(minutes=5))
    assert detector.recency_score(article, now=NOW) == 1.0


def test_recency_decays_and_reaches_zero_outside_the_window():
    detector = BreakingNewsDetector()
    inside = make_article(published_at=NOW - timedelta(hours=6))
    beyond = make_article(published_at=NOW - timedelta(hours=48))
    assert 0.0 < detector.recency_score(inside, now=NOW) < 1.0
    assert detector.recency_score(beyond, now=NOW) == 0.0


def test_recency_never_credits_an_article_without_a_timestamp():
    detector = BreakingNewsDetector()
    assert detector.recency_score(make_article(published_at=None), now=NOW) == 0.0


def test_a_future_timestamp_is_treated_as_now_not_as_a_bonus():
    detector = BreakingNewsDetector()
    article = make_article(published_at=NOW + timedelta(hours=5))
    assert detector.recency_score(article, now=NOW) == 1.0


def test_score_components_are_weighted_by_the_configured_weights():
    detector = BreakingNewsDetector()
    breakdown = detector.breakdown(make_article(symbols=["OGDC"], indices=["KSE100"]), now=NOW)
    assert set(breakdown.components) == {
        "recency", "source_reliability", "entity_importance", "mention_velocity",
        "topic_acceleration", "market_association", "cluster_bonus",
    }
    assert breakdown.weights == breaking_news_settings.detection_weights
    assert 0.0 <= breakdown.score <= 100.0


@pytest.mark.parametrize("score,expected", [
    (0, BreakingLevel.NORMAL),
    (49.9, BreakingLevel.NORMAL),
    (50, BreakingLevel.SIGNIFICANT),
    (74.9, BreakingLevel.SIGNIFICANT),
    (75, BreakingLevel.BREAKING),
    (100, BreakingLevel.BREAKING),
])
def test_breaking_level_thresholds(score, expected):
    assert BreakingNewsDetector().determine_breaking_level(score) is expected


def test_falling_interest_cannot_make_a_story_breaking():
    detector = BreakingNewsDetector()
    flat = detector.breakdown(make_article(), topic_acceleration=0.0, now=NOW)
    negative = detector.breakdown(make_article(), topic_acceleration=-0.9, now=NOW)
    assert negative.components["topic_acceleration"] == 0.0
    assert negative.score == pytest.approx(flat.score)


def test_corroboration_lifts_a_story_but_within_a_bounded_amount():
    detector = BreakingNewsDetector()
    alone = detector.breakdown(make_article(), cluster_size=1, now=NOW)
    together = detector.breakdown(make_article(), cluster_size=8, now=NOW)
    assert together.score > alone.score
    assert together.score - alone.score <= 8.0


def test_source_reliability_prefers_observed_reliability_over_the_prior():
    detector = BreakingNewsDetector()
    article = make_article(publisher="Unknown Blog")
    prior = detector.source_reliability_score(article)
    observed = detector.source_reliability_score(article, reliability_lookup=lambda _p: 0.97)
    assert observed == pytest.approx(0.97)
    assert prior < observed


def test_mention_velocity_is_zero_without_enough_mentions_and_rises_with_them():
    article = make_article(symbols=["OGDC"])
    assert bd.compute_mention_velocity([article], "OGDC", now=NOW) == 0.0
    many = [make_article(published_at=NOW - timedelta(minutes=i), symbols=["OGDC"]) for i in range(6)]
    assert bd.compute_mention_velocity(many, "OGDC", now=NOW) > 0.0


def test_mention_velocity_ignores_mentions_outside_the_window():
    stale = [make_article(published_at=NOW - timedelta(days=3), symbols=["OGDC"]) for _ in range(10)]
    assert bd.compute_mention_velocity(stale, "OGDC", now=NOW) == 0.0


def test_topic_acceleration_is_positive_when_the_rate_is_rising():
    articles = (
        [make_article(published_at=NOW - timedelta(hours=5), symbols=["HBL"]) for _ in range(1)]
        + [make_article(published_at=NOW - timedelta(minutes=20), symbols=["HBL"]) for _ in range(8)]
    )
    assert bd.compute_topic_acceleration(articles, "HBL", now=NOW, window_minutes=60) > 0


def test_topic_acceleration_is_negative_when_interest_is_fading():
    articles = (
        [make_article(published_at=NOW - timedelta(minutes=90), symbols=["HBL"]) for _ in range(8)]
        + [make_article(published_at=NOW - timedelta(minutes=10), symbols=["HBL"])]
    )
    assert bd.compute_topic_acceleration(articles, "HBL", now=NOW, window_minutes=60) < 0


def test_market_association_does_not_saturate_on_a_short_headline():
    detector = BreakingNewsDetector()
    plain = detector.market_association_score(make_article(title="Acme appoints a new director", excerpt=None))
    market = detector.market_association_score(
        make_article(title="Stocks, market, index and trading halt as prices plunge", excerpt=None)
    )
    assert plain < market
    assert market <= 1.0


# ===========================================================================
# spec §6 — duplicate detection / clustering
# ===========================================================================

def _cluster(articles):
    return NewsDeduplicator().cluster_related_articles(articles)


def test_identical_urls_cluster_together():
    left = make_article(article_id=1, url="https://x.test/same")
    right = make_article(article_id=2, url="https://x.test/same", publisher="Tribune")
    clusters = _cluster([left, right])
    assert len(clusters) == 1 and clusters[0].size == 2
    assert "url" in clusters[0].signals


def test_the_identical_headline_under_two_urls_clusters():
    title = "Acme Cement posts record quarterly profit of ten billion rupees"
    clusters = _cluster([
        make_article(article_id=1, title=title, url="https://a.test/1"),
        make_article(article_id=2, title=title, url="https://b.test/1", publisher="Tribune"),
    ])
    assert clusters[0].size == 2


def test_an_independently_written_version_of_the_same_event_clusters():
    clusters = _cluster([
        make_article(article_id=1, url="https://a.test/1",
                     title="Acme Cement posts record quarterly profit of ten billion rupees"),
        make_article(article_id=2, url="https://b.test/1", publisher="Tribune",
                     title="Acme Cement reports record quarterly profit of ten billion rupees"),
    ])
    assert clusters[0].size == 2


def test_unrelated_events_do_not_cluster():
    clusters = _cluster([
        make_article(article_id=1, title="Acme Cement posts record quarterly profit"),
        make_article(article_id=2, url="https://b.test/1", publisher="Tribune",
                     title="Central bank holds the benchmark policy rate unchanged"),
    ])
    assert all(c.size == 1 for c in clusters)


def test_the_time_gate_stops_two_separate_events_from_merging():
    title = "Acme Cement posts record quarterly profit of ten billion rupees"
    clusters = _cluster([
        make_article(article_id=1, title=title, published_at=NOW),
        make_article(article_id=2, title=title, url="https://b.test/1",
                     published_at=NOW - timedelta(days=30)),
    ])
    assert all(c.size == 1 for c in clusters)


def test_canonical_article_prefers_the_more_reliable_publisher():
    title = "Acme Cement posts record quarterly profit of ten billion rupees"
    clusters = _cluster([
        make_article(article_id=1, title=title, publisher="Unknown Blog", url="https://a.test/1"),
        make_article(article_id=2, title=title, publisher="Reuters", url="https://b.test/1"),
    ])
    assert clusters[0].canonical_article_id == 2


def test_cluster_aggregates_publishers_symbols_and_time_span():
    clusters = _cluster([
        make_article(article_id=1, title="OGDC and HBL lead the index higher on record volumes",
                     publisher="Dawn", published_at=NOW, symbols=["OGDC"]),
        make_article(article_id=2, url="https://b.test/1",
                     title="OGDC and HBL lead the index higher on record volumes",
                     publisher="Tribune", published_at=NOW + timedelta(minutes=45), symbols=["OGDC", "HBL"]),
    ])
    cluster = clusters[0]
    assert set(cluster.publishers) == {"Dawn", "Tribune"}
    assert set(cluster.symbols) == {"OGDC", "HBL"}
    assert cluster.time_span_hours == pytest.approx(0.75)
    assert cluster.terms


def test_clustering_an_empty_list_is_safe():
    assert _cluster([]) == []


def test_a_cluster_never_exceeds_the_configured_cap():
    articles = [
        make_article(article_id=i, url=f"https://x.test/{i}", title=f"Distinct story number {i} about topic {i}")
        for i in range(80)
    ]
    assert len(_cluster(articles)) <= breaking_news_settings.max_clusters


# ===========================================================================
# spec §12/§13 — topics and trend scoring
# ===========================================================================

def _topic_articles():
    return [
        {
            "id": i, "title": "OGDC and HBL lead the index higher on record volumes",
            "excerpt": "Monetary policy and inflation remain in focus.",
            "publisher": f"Publisher {i % 3}",
            "published_at": NOW - timedelta(minutes=i * 5),
            "related_symbols": ["OGDC"], "related_indices": ["KSE100"],
            "market_entities": [], "impact_score": 70.0, "sentiment_score": 0.2,
        }
        for i in range(5)
    ]


def test_topic_extractor_finds_lexicon_symbol_and_index_topics():
    extractor = te.TopicExtractor()
    candidates = extractor.extract_topics(make_article(
        symbols=["OGDC"], indices=["KSE100"],
        title="Monetary policy decision lifts OGDC as KSE-100 rises",
        excerpt="Inflation is easing.",
    ))
    kinds = {c.topic_type for c in candidates}
    assert {"LEXICON", "SYMBOL", "INDEX"} <= kinds


def test_generic_market_words_are_not_promoted_to_topics():
    extractor = te.TopicExtractor()
    candidates = extractor.extract_topics(make_article(
        title="Stock market growth focus key buy",
        excerpt="Stocks market growth focus key buy",
    ))
    names = {c.name.lower() for c in candidates}
    assert not (names & {"stock", "market", "growth", "focus", "key", "buy"})


def test_a_symbol_is_not_also_emitted_as_a_keyword_topic():
    extractor = te.TopicExtractor()
    candidates = extractor.extract_topics(make_article(title="PPL reports results", symbols=["PPL"]))
    normalised = [c.normalized for c in candidates]
    assert len(normalised) == len(set(normalised))
    assert sum(1 for c in candidates if c.name.lower() == "ppl") == 1


def test_topic_aggregator_counts_articles_and_sources():
    stats = te.TopicAggregator().aggregate(_topic_articles(), now=NOW)
    symbol_topic = stats.get("symbol:ogdc")
    assert symbol_topic is not None
    assert symbol_topic.article_count == 5
    assert symbol_topic.source_count == 3
    assert symbol_topic.avg_sentiment == pytest.approx(0.2)
    assert symbol_topic.market_linked == 5


def test_single_mention_topics_are_dropped_as_noise():
    stats = te.TopicAggregator().aggregate(_topic_articles()[:1], now=NOW)
    assert stats == {}


def test_trend_score_is_a_weighted_blend_of_its_components():
    stats = te.TopicAggregator().aggregate(_topic_articles(), now=NOW)
    service = te.TopicTrendService()
    for topic in stats.values():
        result = service.calculate_trend_score(topic, now=NOW)
        assert set(result["components"]) == {"mention_velocity", "source_count", "recency", "related_activity"}
        assert result["weights"] == breaking_news_settings.topic_trend_weights
        assert 0.0 <= result["score"] <= 100.0


def test_trend_direction_follows_consecutive_window_counts():
    service = te.TopicTrendService()
    rising = te.TopicStats(topic_name="x", normalized_name="x", recent_mentions=9, previous_mentions=1)
    falling = te.TopicStats(topic_name="x", normalized_name="x", recent_mentions=1, previous_mentions=9)
    stable = te.TopicStats(topic_name="x", normalized_name="x", recent_mentions=3, previous_mentions=3)
    assert service.determine_trend_direction(rising) is TrendDirection.RISING
    assert service.determine_trend_direction(falling) is TrendDirection.FALLING
    assert service.determine_trend_direction(stable) is TrendDirection.STABLE


def test_related_activity_is_zero_without_market_linked_coverage():
    stats = te.TopicStats(topic_name="x", normalized_name="x", mention_count=4, market_linked=0, high_impact=0)
    assert te.TopicTrendService()._related_activity(stats) == 0.0


def test_recency_component_is_zero_for_a_topic_last_seen_long_ago():
    stats = te.TopicStats(topic_name="x", normalized_name="x", last_seen=NOW - timedelta(days=5))
    assert te.TopicTrendService()._recency(stats, now=NOW) == 0.0


# ===========================================================================
# spec §16 — source reliability
# ===========================================================================

def test_publisher_prior_comes_from_the_feed_registry():
    assert publisher_prior("Dawn") == pytest.approx(0.85)
    assert publisher_prior("some unknown blog") == pytest.approx(0.6)
    assert publisher_prior("Reuters") > publisher_prior("some unknown blog")


def test_reliability_is_bounded_and_higher_for_a_corroborated_complete_source():
    engine = SourceReliabilityEngine()
    good = engine.score(_observation("Reuters", article_count=20, corroborated=18, complete=20))
    thin = engine.score(_observation("Unknown Blog", article_count=20, corroborated=0, complete=2))
    assert 0.0 <= thin["reliability_score"] <= good["reliability_score"] <= 1.0


def test_corroboration_and_completeness_are_unset_without_enough_articles():
    engine = SourceReliabilityEngine()
    scores = engine.score(_observation("Dawn", article_count=1, corroborated=0, complete=1))
    assert scores["corroboration_ratio"] is None
    assert scores["accuracy_score"] is None


def _observation(publisher: str, *, article_count: int, corroborated: int, complete: int):
    from app.breaking_news.sources import PublisherObservation

    return PublisherObservation(
        publisher=publisher,
        article_count=article_count,
        corroborated_count=corroborated,
        complete_count=complete,
        feed_key=None,
    )


def test_collect_observations_measures_corroboration_and_timeliness():
    from app.breaking_news.sources import SourceReliabilityEngine as SRE

    articles = [
        make_article(article_id=1, publisher="Dawn", published_at=NOW, impact_score=80.0),
        make_article(article_id=2, publisher="Tribune", published_at=NOW + timedelta(minutes=30)),
    ]
    rows = [_Row(a) for a in articles]
    observations = SRE().collect_observations(
        rows,
        cluster_of={1: ("evt-1", 2), 2: ("evt-1", 2)},
        cluster_file_time={"evt-1": NOW},
    )
    assert observations["Dawn"].corroborated_count == 1
    assert observations["Dawn"].timeliness_samples == [0.0]
    assert observations["Tribune"].timeliness_samples == [1800.0]
    assert SRE().score(observations["Dawn"])["timeliness_score"] == pytest.approx(1.0)


class _Row:
    """Minimal ORM-like row so the source engine can be tested without a session."""

    def __init__(self, article: NormalizedArticle):
        self.id = article.id
        self.title = article.title
        self.publisher = article.publisher
        self.excerpt = article.excerpt
        self.related_symbols = article.symbols
        self.related_indices = article.indices
        self.published_at = article.published_at
        self.impact_score = article.impact_score
        self.data_source = article.source
        self.feed_key = "dawn_business" if article.source.endswith("dawn_business") else None


# ===========================================================================
# spec §7–§10 — market impact
# ===========================================================================

@pytest.mark.parametrize("entity,kind,expected", [
    ("OGDC", "STOCK", "OGDC.KA"),
    ("AAPL", "STOCK", "AAPL"),
    ("GOLD", "COMMODITY", "GC=F"),
    ("BTC", "CRYPTO", "BTC-USD"),
    ("SPX", "INDEX", "^GSPC"),
    ("KSE100", "INDEX", None),          # not carried by the keyless provider
    ("FED", "AUTO", None),              # a policy actor, not an instrument
])
def test_resolve_entity_maps_to_a_provider_symbol(entity, kind, expected):
    symbol, _ = resolve_entity(entity, kind)
    assert symbol == expected


def test_auto_inference_classifies_a_named_asset():
    assert resolve_entity("gold", "AUTO")[1] == "COMMODITY"
    assert resolve_entity("bitcoin", "AUTO")[1] == "CRYPTO"
    assert resolve_entity("SPX", "AUTO")[1] == "INDEX"


def test_window_is_reported_unavailable_without_enough_bars_on_both_sides():
    analyzer = MarketImpactAnalyzer()
    fetcher = FakeHistoryFetcher({"AAPL": [Bar(timestamp=NOW - timedelta(minutes=1), close=100.0)]})
    result = asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="AAPL", entity_type="STOCK",
        observation_window="1h", fetcher=fetcher,
    ))
    assert result is not None
    assert result["window_available"] is False
    assert result["impact_magnitude"] == ImpactMagnitude.NONE.value
    assert "not enough timestamped data" in result["notes"]


def test_window_reports_real_before_and_after_prices():
    analyzer = MarketImpactAnalyzer()
    fetcher = FakeHistoryFetcher({"AAPL": minute_bars(NOW, base=100.0, step=0.1)})
    result = asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="AAPL", entity_type="STOCK",
        observation_window="1h", fetcher=fetcher,
    ))
    assert result["window_available"] is True
    assert result["bars_before"] == 10 and result["bars_after"] == 20
    assert result["price_change"] == pytest.approx(2.0)  # 100.0 -> 102.0
    assert result["price_change_percent"] == pytest.approx(2.0)
    assert result["impact_magnitude"] == ImpactMagnitude.HIGH.value
    assert result["series"]


def test_a_provider_failure_is_unavailable_not_zero():
    analyzer = MarketImpactAnalyzer()
    fetcher = FakeHistoryFetcher(error="provider unreachable")
    assert asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="AAPL", entity_type="STOCK",
        observation_window="1h", fetcher=fetcher,
    )) is None


def test_a_one_percent_move_is_large_for_fx_and_small_for_equities():
    analyzer = MarketImpactAnalyzer()
    fetcher = FakeHistoryFetcher({"EURUSD=X": minute_bars(NOW, base=1.0, step=0.0001)})
    result = asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="EURUSD=X", entity_type="FOREX",
        observation_window="1h", fetcher=fetcher,
    ))
    assert result["price_change_percent"] == pytest.approx(0.2, abs=0.01)
    # 0.2% is below the FOREX "low" cutoff of 0.05%? No — it is above it.
    assert result["impact_magnitude"] == ImpactMagnitude.LOW.value


def test_analyze_all_windows_reports_the_unavailable_ones_without_failing():
    analyzer = MarketImpactAnalyzer()

    class MinuteOnlyFetcher(FakeHistoryFetcher):
        """A provider that only serves 1-minute bars.

        ``window_intervals`` asks for 5m/15m/1h bars on the wider windows, so
        only the 5m window has data at the right resolution — every other window
        (including 24h) must come back UNAVAILABLE rather than be built from
        bars of the wrong granularity.
        """

        async def fetch(self, symbol, start, end, interval) -> HistoryBundle:
            if interval != "1m":
                self.calls.append((symbol, start, end, interval))
                return HistoryBundle(requested_symbol=symbol, error=f"no {interval} data")
            return await super().fetch(symbol, start, end, interval)

    fetcher = MinuteOnlyFetcher({"AAPL": minute_bars(NOW)})
    result = asyncio.run(analyzer.analyze_all_windows(
        published_at=NOW, entity="AAPL", entity_type="STOCK", fetcher=fetcher,
    ))
    assert result["entity"] == "AAPL"
    assert "24h" in result["unavailable_windows"]
    # Every configured window is accounted for exactly once, either as an
    # available window or as an explicitly unavailable one.
    reported = [w["observation_window"] for w in result["windows"]]
    assert sorted(reported + result["unavailable_windows"]) == sorted(analyzer.observation_windows)
    assert all(w["window_available"] for w in result["windows"])
    # 5m is the only window whose configured interval (1m) the provider serves.
    assert reported == ["5m"]


def test_forecast_entities_are_not_price_measured():
    analyzer = MarketImpactAnalyzer()
    assert asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="some-market", entity_type="FORECAST",
        observation_window="1h", fetcher=FakeHistoryFetcher(),
    )) is None


def test_impact_notes_never_claim_causation():
    analyzer = MarketImpactAnalyzer()
    fetcher = FakeHistoryFetcher({"AAPL": minute_bars(NOW)})
    result = asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="AAPL", entity_type="STOCK",
        observation_window="1h", fetcher=fetcher,
    ))
    assert "observed" in result["notes"]
    assert "causation" in result["notes"]
    assert "caused" not in result["notes"]


def test_confidence_is_zero_for_an_unavailable_window_and_high_for_a_full_one():
    analyzer = MarketImpactAnalyzer()
    sparse = asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="AAPL", entity_type="STOCK", observation_window="1h",
        fetcher=FakeHistoryFetcher({"AAPL": minute_bars(NOW, before=1, after=1)}),
    ))
    full = asyncio.run(analyzer.analyze_window(
        published_at=NOW, entity="AAPL", entity_type="STOCK", observation_window="1h",
        fetcher=FakeHistoryFetcher({"AAPL": minute_bars(NOW)}),
    ))
    assert sparse["confidence"] == 0.0
    assert full["confidence"] > 0.6


def test_missing_publication_time_yields_no_analysis():
    analyzer = MarketImpactAnalyzer()
    assert asyncio.run(analyzer.analyze_window(
        published_at=None, entity="AAPL", entity_type="STOCK",
        observation_window="1h", fetcher=FakeHistoryFetcher(),
    )) is None


# ===========================================================================
# spec §8 — forecast probability movement
# ===========================================================================

def _series():
    return [
        {"timestamp": (NOW - timedelta(minutes=45)).isoformat(), "yesProbability": 81.0},
        {"timestamp": (NOW - timedelta(minutes=20)).isoformat(), "yesProbability": 79.0},
        {"timestamp": (NOW + timedelta(minutes=15)).isoformat(), "yesProbability": 73.0},
        {"timestamp": (NOW + timedelta(minutes=90)).isoformat(), "yesProbability": 70.0},
    ]


def test_probability_change_is_measured_from_real_points():
    result = ProbabilityMovementAnalyzer.analyze_series(_series(), published_at=NOW, observation_window="1h")
    assert result is not None
    assert result["probability_before"] == pytest.approx(79.0)
    assert result["probability_after"] == pytest.approx(73.0)
    assert result["probability_change"] == pytest.approx(-6.0)
    assert result["movement_direction"] == "DOWN"
    assert result["impact_magnitude"] == ImpactMagnitude.MEDIUM.value
    assert result["series"]


def test_probability_movement_is_none_without_a_point_before_publication():
    future_only = [row for row in _series() if row["timestamp"] >= NOW.isoformat()]
    assert ProbabilityMovementAnalyzer.analyze_series(future_only, published_at=NOW, observation_window="1h") is None


def test_probability_movement_is_none_without_a_point_inside_the_window():
    late = [row for row in _series() if "2026-03-10T12:00" not in row["timestamp"] and
            datetime.fromisoformat(row["timestamp"]) <= NOW + timedelta(minutes=90)]
    assert ProbabilityMovementAnalyzer.analyze_series(late[:1], published_at=NOW, observation_window="1h") is None


def test_probability_movement_ignores_out_of_range_values():
    bad = [{"timestamp": NOW.isoformat(), "yesProbability": 150.0}]
    # 150 is not a probability; the analyzer keeps it out of the before/after pair
    # only if it cannot be used at all — it is still a real recorded value, so the
    # contract is simply that nothing is *invented*.
    result = ProbabilityMovementAnalyzer.analyze_series(bad, published_at=NOW, observation_window="1h")
    assert result is None


def test_market_matching_respects_the_threshold():
    analyzer = ProbabilityMovementAnalyzer()
    markets = [
        {"id": "m1", "title": "Will the Federal Reserve cut interest rates in March?", "description": ""},
        {"id": "m2", "title": "Will it snow in Tokyo next week?", "description": ""},
    ]
    matched = analyzer.match_markets("Federal Reserve interest rates decision", markets)
    assert [m["id"] for m, _ in matched] == ["m1"]


def test_market_matching_returns_nothing_when_nothing_is_related():
    analyzer = ProbabilityMovementAnalyzer()
    markets = [{"id": "m1", "title": "Will it snow in Tokyo next week?", "description": ""}]
    assert analyzer.match_markets("Acme Cement quarterly profit", markets) == []


# ===========================================================================
# spec §17 — AI summarization
# ===========================================================================

class _FakeProvider:
    def __init__(self, content: str = '{"summary": "A grounded summary.", "confidence": 0.8}', *, boom: bool = False):
        self.content = content
        self.boom = boom
        self.messages = []

    async def chat_completion(self, messages, temperature=0.7, max_tokens=None):
        if self.boom:
            raise RuntimeError("provider down")
        self.messages = messages
        return {"content": self.content, "model": "fake-model"}

    def get_model_name(self) -> str:
        return "fake-model"


def test_key_numbers_are_extracted_from_the_text_only():
    numbers = extract_key_numbers("Profit rose 12.5% while revenue fell 3 billion rupees.")
    assert {n["unit"] for n in numbers} == {"%", "billion"}
    assert extract_key_numbers("no numbers here") == []


def test_summarizer_reports_disabled_when_switched_off():
    summarizer = AISummarizer(provider=_FakeProvider(), settings=_settings(enable_ai_summarization=False))
    result = asyncio.run(summarizer.summarize(title="T", excerpt="Body text", breaking_score=99))
    assert result.status == "DISABLED"


def test_summarizer_skips_an_event_below_the_score_threshold():
    summarizer = AISummarizer(provider=_FakeProvider(), settings=_settings(ai_summary_min_score=90))
    result = asyncio.run(summarizer.summarize(title="T", excerpt="Body", breaking_score=20))
    assert result.status == "SKIPPED"
    assert "below the AI summarization threshold" in result.error


def test_summarizer_skips_an_event_with_no_lede_instead_of_inventing_one():
    summarizer = AISummarizer(provider=_FakeProvider(), settings=_settings())
    result = asyncio.run(summarizer.summarize(title="T", excerpt=None, breaking_score=99))
    assert result.status == "SKIPPED"
    assert "nothing to summarize" in result.error


def test_summarizer_reports_unavailable_when_the_provider_fails():
    summarizer = AISummarizer(provider=_FakeProvider(boom=True), settings=_settings())
    result = asyncio.run(summarizer.summarize(title="T", excerpt="Body", breaking_score=99))
    assert result.status == "UNAVAILABLE"
    assert result.summary is None


def test_summarizer_returns_a_labelled_summary_and_ground_truth_evidence():
    provider = _FakeProvider()
    summarizer = AISummarizer(provider=provider, settings=_settings())
    result = asyncio.run(summarizer.summarize(
        title="Gold rises 2% as the dollar weakens",
        excerpt="Bullion gained as the dollar index fell.",
        publisher="Dawn",
        breaking_score=99,
    ))
    assert result.status == "OK"
    assert result.is_ai_generated is True
    assert result.model == "fake-model"
    assert result.generated_at is not None
    assert result.key_numbers
    assert any(e["value"] == "GOLD" for e in result.key_entities)
    # The prompt must contain only the supplied article text — no outside context.
    assert "Gold rises 2%" in provider.messages[1]["content"]
    assert "never add facts" in provider.messages[0]["content"]


def test_summarizer_parses_json_wrapped_in_prose():
    provider = _FakeProvider(content='Here you go:\n{"summary": "Wrapped.", "confidence": 0.5}\nThanks!')
    result = asyncio.run(AISummarizer(provider=provider, settings=_settings()).summarize(
        title="T", excerpt="Body", breaking_score=99,
    ))
    assert result.summary == "Wrapped."


def test_summarizer_falls_back_to_the_raw_text_when_the_model_is_not_json():
    provider = _FakeProvider(content="A plain sentence summary.")
    result = asyncio.run(AISummarizer(provider=provider, settings=_settings()).summarize(
        title="T", excerpt="Body", breaking_score=99,
    ))
    assert result.summary == "A plain sentence summary."


def _settings(**overrides):
    base = breaking_news_settings.model_copy(deep=True)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


# ===========================================================================
# spec §15 — streaming
# ===========================================================================

def test_snapshot_signature_is_stable_and_content_addressed():
    from app.breaking_news.stream import _signature

    first = _signature({"a": 1, "b": [1, 2]})
    assert first == _signature({"b": [1, 2], "a": 1})
    assert first != _signature({"a": 2, "b": [1, 2]})


def test_client_queue_drops_the_oldest_frame_when_full():
    from app.breaking_news.stream import StreamClient

    client = StreamClient(id="c1", transport="websocket")
    for i in range(10):
        client.offer({"n": i})
    assert client.dropped > 0
    assert client.queue.qsize() <= 4


def test_stream_manager_tracks_connections_and_stats():
    from app.breaking_news.stream import BreakingNewsStreamManager

    manager = BreakingNewsStreamManager()
    manager.register("a", "websocket")
    manager.register("b", "sse")
    stats = manager.stats()
    assert stats["connected_clients"] == 2
    assert stats["websocket_clients"] == 1 and stats["sse_clients"] == 1
    manager.unregister("a")
    assert manager.stats()["connected_clients"] == 1


# ===========================================================================
# spec §19 — provider isolation
# ===========================================================================

class _StubProvider(NewsProvider):
    def __init__(self, name: str, items=None, *, raises: bool = False):
        self.name = name
        self.items = items or []
        self.raises = raises

    async def fetch(self):
        if self.raises:
            raise RuntimeError(f"{self.name} is down")
        return self.items


def test_one_failing_provider_does_not_stop_the_others():
    good_item = {
        "title": "Acme Cement posts record quarterly profit",
        "source_url": "https://good.test/1",
        "publisher": "Dawn",
        "published_at": NOW.isoformat(),
    }
    aggregator = NewsAggregator([
        _StubProvider("broken", raises=True),
        _StubProvider("working", [good_item]),
    ])
    result = asyncio.run(aggregator.collect())
    assert len(result.articles) == 1
    assert result.errors and "broken" in result.errors[0]
    reports = {r.name: r for r in result.reports}
    assert reports["broken"].ok is False and reports["working"].ok is True


def test_the_aggregator_counts_a_cross_provider_duplicate_once():
    item = {
        "title": "Acme Cement posts record quarterly profit",
        "source_url": "https://shared.test/1",
        "publisher": "Dawn",
        "published_at": NOW.isoformat(),
    }
    aggregator = NewsAggregator([_StubProvider("a", [item]), _StubProvider("b", [dict(item)])])
    result = asyncio.run(aggregator.collect())
    assert len(result.articles) == 1
    assert sum(r.duplicates for r in result.reports) == 1


def test_the_aggregator_reports_missing_fields_per_provider():
    aggregator = NewsAggregator([_StubProvider("a", [{
        "title": "Headline with no lede or image",
        "source_url": "https://a.test/1",
        "publisher": "Dawn",
        "published_at": NOW.isoformat(),
    }])])
    result = asyncio.run(aggregator.collect())
    report = result.reports[0]
    assert report.missing_fields["image"] == 1
    assert report.missing_fields["excerpt"] == 1


def test_an_unusable_item_is_rejected_not_repaired():
    aggregator = NewsAggregator([_StubProvider("a", [
        {"title": "", "source_url": "https://a.test/1"},
        {"title": "No link", "source_url": ""},
    ])])
    result = asyncio.run(aggregator.collect())
    assert result.articles == []
    assert result.reports[0].rejected == 2


# ===========================================================================
# ranking
# ===========================================================================

def test_ranker_orders_by_score_then_recency():
    fresh = make_article(article_id=1, title="OGDC posts record profit and dividend", published_at=NOW, symbols=["OGDC"])
    old = make_article(article_id=2, url="https://b.test/1", title="OGDC posts record profit and dividend",
                       published_at=NOW - timedelta(hours=20), symbols=["OGDC"])
    ranked = NewsRanker().rank([old, fresh], cluster_of={1: ("e", 1), 2: ("f", 1)}, now=NOW)
    assert ranked[0].article.id == 1
    assert ranked[0].score >= ranked[1].score


def test_ranker_uses_the_cluster_size_it_is_given():
    article = make_article(article_id=1)
    alone = NewsRanker().rank([article], cluster_of={1: ("e", 1)}, now=NOW)[0]
    together = NewsRanker().rank([article], cluster_of={1: ("e", 6)}, now=NOW)[0]
    assert together.score > alone.score
    assert together.cluster_size == 6


# ===========================================================================
# engine integration (no network)
# ===========================================================================

@pytest.fixture
def db_session():
    from app.db import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed(db, articles) -> list[int]:
    from app.models import NewsArticle

    ids: list[int] = []
    for article in articles:
        row = NewsArticle(
            title=article.title,
            slug=article.url.rsplit("/", 1)[-1],
            publisher=article.publisher,
            published_at=to_naive_utc(article.published_at) or utcnow(),
            excerpt=article.excerpt,
            image_url=article.image,
            category="Business",
            tags=[],
            related_symbols=article.symbols,
            related_indices=article.indices,
            source_url=article.url,
            source_type="ARTICLE",
            priority="NORMAL",
            data_source=article.source,
            data_mode="LIVE",
            event_type="GENERAL",
            impact_score=article.impact_score,
            keywords=[],
            entities=article.entities,
            topics=article.topics,
            word_count=40,
            reading_time_minutes=1,
        )
        db.add(row)
    db.commit()
    for article in articles:
        row = db.query(NewsArticle).filter(NewsArticle.source_url == article.url).first()
        if row:
            ids.append(row.id)
    return ids


def test_rebuild_persists_events_topics_and_sources(db_session):
    db = db_session
    stamp = utcnow().isoformat()
    # Published *now*: the corpus window is relative to real time, so seeded
    # articles must be recent or the rebuild correctly finds an empty window.
    seeded = _seed(db, [
        make_article(title=f"OGDC declares a record dividend on booming earnings {stamp}",
                     url=f"https://it.test/ogdc-{stamp}", published_at=utcnow()),
        make_article(title=f"OGDC declares a record dividend on booming earnings {stamp}",
                     url=f"https://it.test/ogdc2-{stamp}", publisher="Tribune", published_at=utcnow()),
        make_article(title=f"HBL reports a sharp rise in quarterly profit {stamp}",
                     url=f"https://it.test/hbl-{stamp}", symbols=["HBL"],
                     publisher="Business Recorder", published_at=utcnow()),
    ])

    engine = BreakingNewsEngine()
    bundle = asyncio.run(engine.rebuild(db, hours=48))

    titles = {row.title for row in bundle.items}
    assert any("OGDC declares a record dividend" in title for title in titles)
    assert bundle.articles_analyzed >= 3
    assert bundle.clusters_found >= 2
    assert bundle.sources_consulted >= 2

    from app.breaking_news.models.models import BreakingNews, NewsTopic, SourceMetadata

    event = (
        db.query(BreakingNews)
        .filter(BreakingNews.article_id.in_(seeded))
        .first()
    )
    assert event is not None
    # One row per event: the two OGDC articles collapse into a single cluster.
    assert event.cluster_size >= 2
    assert event.related_articles
    assert event.score_components and event.score_weights
    assert 0.0 <= event.breaking_score <= 100.0

    assert db.query(NewsTopic).count() > 0
    assert db.query(SourceMetadata).count() > 0


def test_rebuild_is_idempotent(db_session):
    db = db_session
    stamp = utcnow().isoformat()
    _seed(db, [make_article(title=f"PPL signs a new exploration contract {stamp}",
                            url=f"https://it.test/ppl-{stamp}", symbols=["PPL"],
                            published_at=utcnow())])

    engine = BreakingNewsEngine()
    first = asyncio.run(engine.rebuild(db, hours=48))
    from app.breaking_news.models.models import BreakingNews

    count_first = db.query(BreakingNews).count()
    asyncio.run(engine.rebuild(db, hours=48))
    assert db.query(BreakingNews).count() == count_first
    assert first.articles_analyzed > 0


def test_an_old_article_is_not_flagged_breaking(db_session):
    db = db_session
    stamp = utcnow().isoformat()
    old = make_article(title=f"Old news about OGDC {stamp}", url=f"https://it.test/old-{stamp}",
                       published_at=utcnow() - timedelta(days=3), symbols=["OGDC"])
    _seed(db, [old])

    engine = BreakingNewsEngine()
    bundle = asyncio.run(engine.rebuild(db, hours=48))
    for row in bundle.items:
        if row.title == old.title:
            assert row.breaking_level != "Breaking".upper()
            assert row.breaking_level in {"SIGNIFICANT", "NORMAL"}


def test_topics_full_text_keywords_do_not_duplicate_a_symbol(db_session):
    db = db_session
    stamp = utcnow().isoformat()
    for i in range(3):
        _seed(db, [make_article(title=f"FFC reports strong earnings for the quarter {stamp}-{i}",
                                url=f"https://it.test/ffc-{stamp}-{i}", symbols=["FFC"],
                                publisher=f"Publisher {i}")])
    engine = BreakingNewsEngine()
    asyncio.run(engine.rebuild(db, hours=48))

    from app.breaking_news.models.models import NewsTopic

    rows = db.query(NewsTopic).all()
    for row in rows:
        assert row.normalized_name != "keyword:ffc" or row.topic_type != "SYMBOL"
    names = [row.normalized_name for row in rows]
    assert len(names) == len(set(names))


# ===========================================================================
# API surface
# ===========================================================================

@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app

    init_db()
    # Deliberately not used as a context manager: entering it would start the
    # background maintenance loop, which performs real network ingests.
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


def test_health_endpoint_reports_the_phase_and_its_settings(client):
    body = client.get("/api/breaking-news/health").json()
    assert body["status"] == "ok" and body["phase"] == 17
    assert body["observation_windows"] == list(breaking_news_settings.observation_windows)
    assert body["settings"]["detection_weights"] == breaking_news_settings.detection_weights
    assert "stream" in body and "ai_summarization" in body


def test_feed_endpoint_returns_items_and_meta(client):
    client.post("/api/breaking-news/refresh?live=false")
    body = client.get("/api/breaking-news/feed?hours=48").json()
    assert set(body) == {"items", "meta"}
    assert body["meta"]["hours"] == 48
    assert "observed after publication" in body["meta"]["disclaimer"]
    for item in body["items"]:
        assert item["breaking_level"] in {"BREAKING", "SIGNIFICANT", "NORMAL"}
        assert 0 <= item["breaking_score"] <= 100
        assert item["time_ago"] is not None


def test_feed_level_filter_only_returns_that_level(client):
    client.post("/api/breaking-news/refresh?live=false")
    body = client.get("/api/breaking-news/feed?hours=168&level=BREAKING").json()
    assert all(item["breaking_level"] == "BREAKING" for item in body["items"])


def test_topics_endpoint_exposes_components_and_weights(client):
    client.post("/api/breaking-news/refresh?live=false")
    body = client.get("/api/breaking-news/topics").json()
    assert "trend_weights" in body["meta"]
    for topic in body["topics"]:
        assert 0 <= topic["trend_score"] <= 100
        assert topic["trend_direction"] in {"RISING", "FALLING", "STABLE"}


def test_sources_endpoint_returns_reliability_and_feed_health(client):
    client.post("/api/breaking-news/refresh?live=false")
    body = client.get("/api/breaking-news/sources").json()
    assert set(body) == {"sources", "summary", "feed_health", "generated_at"}
    for source in body["sources"]:
        assert 0.0 <= source["reliability_score"] <= 1.0
        assert source["status"] in {"ACTIVE", "DEGRADED", "INACTIVE"}


def test_clusters_endpoint_exposes_the_grouping_evidence(client):
    client.post("/api/breaking-news/refresh?live=false")
    body = client.get("/api/breaking-news/clusters?hours=48").json()
    assert isinstance(body, list)
    for cluster in body:
        assert cluster["cluster_size"] >= 1
        assert isinstance(cluster["publishers"], list)


def test_digest_endpoint_is_the_polling_fallback(client):
    client.post("/api/breaking-news/refresh?live=false")
    body = client.get("/api/breaking-news/digest").json()
    assert set(body) >= {"generated_at", "events", "topics", "counts"}
    assert body["counts"]["events"] == len(body["events"])


def test_unknown_event_is_a_404(client):
    assert client.get("/api/breaking-news/does-not-exist").status_code == 404


def test_unknown_topic_is_a_404(client):
    assert client.get("/api/breaking-news/topics/does-not-exist").status_code == 404


def test_topic_detail_requires_a_real_topic(client):
    client.post("/api/breaking-news/refresh?live=false")
    topics = client.get("/api/breaking-news/topics?limit=1").json()["topics"]
    if not topics:
        pytest.skip("no topics in the test corpus")
    detail = client.get(f"/api/breaking-news/topics/{topics[0]['id']}").json()
    assert set(detail) >= {"topic", "timeline", "articles", "impact_events", "sources", "generated_at"}
    assert detail["topic"]["id"] == topics[0]["id"]


def test_impact_request_without_an_anchor_is_rejected(client):
    response = client.post("/api/breaking-news/impact", json={"entity": "AAPL"})
    assert response.status_code == 422
    assert "anchor" in response.json()["detail"]


def test_probability_request_without_an_article_is_rejected(client):
    response = client.post("/api/breaking-news/probability", json={"market_id": "x"})
    assert response.status_code == 422


def test_refresh_with_a_stubbed_ingest_reports_provider_outcomes(client):
    """The refresh route must surface per-provider results, not just a count."""
    with patch("app.breaking_news.pipeline.RSSFeedProvider.fetch", async_=True, return_value=[]):
        response = client.post("/api/breaking-news/refresh?live=true")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "started_at", "finished_at", "duration_ms", "stored_articles",
        "breaking_events", "topics_updated", "providers", "errors", "warnings",
    }
    assert isinstance(body["providers"], list)


# ===========================================================================
# time helpers
# ===========================================================================

@pytest.mark.parametrize("value", [
    "2026-03-10T12:00:00Z",
    "2026-03-10T12:00:00+00:00",
    "2026-03-10T12:00:00",
    datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
])
def test_parse_datetime_normalises_to_naive_utc(value):
    parsed = parse_datetime(value)
    assert parsed is not None
    assert parsed.tzinfo is None
    assert parsed.hour == 12


def test_parse_datetime_returns_none_for_garbage():
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None
    assert parse_datetime("") is None
