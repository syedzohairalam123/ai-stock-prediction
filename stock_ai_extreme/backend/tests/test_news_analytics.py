"""
Tests for the Phase 8 news analytics engine.

All article text here is written by hand inside the test file. Nothing asserts
against a real headline, so a publisher rewriting a story can never turn this
suite red, and no expected value was copied from live data.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import news_analytics as na


# --------------------------------------------------------------------------
# tokenisation / keywords
# --------------------------------------------------------------------------

def test_tokenize_drops_stopwords_and_short_tokens():
    tokens = na.tokenize("The Bank of Pakistan said a rise in exports")
    assert "the" not in tokens and "of" not in tokens and "a" not in tokens
    assert "bank" in tokens and "exports" in tokens


def test_tokenize_handles_none_and_empty():
    assert na.tokenize(None) == []
    assert na.tokenize("") == []


def test_tfidf_keywords_favour_rare_terms():
    corpus = [
        "cement company posts profit cement demand",
        "cement company posts profit cement",
        "cement company posts profit cement",
        "unrelated refinery maintenance shutdown announced",
    ]
    tfidf = na.TfIdfCorpus(corpus)
    keywords = tfidf.keywords("cement company posts profit refinery maintenance shutdown", top_k=3)
    # Terms present in almost every document carry less weight than the rare
    # ones, so the distinctive words must appear in the top slice.
    assert any(term in {"refinery", "maintenance", "shutdown"} for term in keywords)


def test_tfidf_vector_is_empty_for_stopword_only_text():
    tfidf = na.TfIdfCorpus(["anything at all"])
    assert tfidf.vector("the of and") == {}


def test_default_keywords_works_without_a_corpus():
    assert na.default_keywords("alpha beta alpha gamma alpha", top_k=2)[0] == "alpha"


def test_cosine_similarity_bounds():
    assert na.cosine_similarity({}, {"a": 1.0}) == 0.0
    assert na.cosine_similarity({"a": 1.0}, {"a": 1.0}) == pytest.approx(1.0)
    assert na.cosine_similarity({"a": 1.0}, {"b": 1.0}) == 0.0


# --------------------------------------------------------------------------
# SimHash
# --------------------------------------------------------------------------

def test_simhash_is_deterministic():
    text = "Acme Cement posts record quarterly profit for the period"
    assert na.simhash(text) == na.simhash(text)


def test_simhash_zero_for_too_little_text():
    # Not a fingerprint — callers must treat 0 as "not comparable".
    assert na.simhash("short") == 0


#: Synthetic text used to document SimHash's real behaviour on short documents.
_SIM_BASE = (
    "Acme Cement Company reported a record quarterly profit of ten billion rupees "
    "driven by higher cement dispatches and improved pricing across the northern region"
)
_SIM_UNRELATED = (
    "The central bank left its benchmark policy rate unchanged at the monetary policy "
    "committee meeting citing a stable inflation outlook and external account position"
)


def test_simhash_treats_identical_text_as_a_duplicate():
    assert na.hamming_distance(na.simhash(_SIM_BASE), na.simhash(_SIM_BASE)) == 0
    assert na.is_near_duplicate(na.simhash(_SIM_BASE), na.simhash(_SIM_BASE), threshold=3)


def test_simhash_separates_an_unrelated_story_at_the_default_threshold():
    # An unrelated story lands tens of bits away, which is exactly why it is
    # safe: SimHash at a threshold of 3 never produces a false positive here.
    assert not na.is_near_duplicate(
        na.simhash(_SIM_BASE), na.simhash(_SIM_UNRELATED), threshold=3
    )


def test_simhash_is_too_coarse_for_a_one_word_edit_on_short_text():
    """A documented limitation, asserted so it cannot silently regress.

    Summing +/-1 votes over ~40 shingles means one removed word already moves
    the fingerprint by ~11 bits — comparable to the distance to an unrelated
    story. This is precisely why near-duplicate suppression decides on the
    MinHash signature instead (see `test_minhash_*`), and SimHash is kept only
    as a cheap corroborating signal.
    """
    edited = _SIM_BASE.replace("a record", "record").replace("the northern", "northern")
    distance = na.hamming_distance(na.simhash(_SIM_BASE), na.simhash(edited))
    assert distance > 3


def test_is_near_duplicate_rejects_zero_fingerprints():
    assert na.is_near_duplicate(0, 0) is False
    assert na.is_near_duplicate(12345, 0) is False


def test_hamming_distance_symmetry():
    a, b = na.simhash("one two three four five"), na.simhash("one two three four six")
    assert na.hamming_distance(a, b) == na.hamming_distance(b, a)


def test_signed_round_trip_preserves_the_full_64_bits():
    # SQLite INTEGER is signed; the stored form must survive a round trip.
    for fingerprint in (0, 1, (1 << 63) - 1, 1 << 63, (1 << 64) - 1):
        assert na.to_unsigned64(na.to_signed64(fingerprint)) == fingerprint
        assert -(1 << 63) <= na.to_signed64(fingerprint) < (1 << 63)


def test_simhash_index_finds_a_fingerprint_it_was_given():
    index = na.SimHashIndex(bands=4, threshold=3)
    fingerprint = na.simhash(_SIM_BASE)
    index.add(fingerprint, "original")
    assert index.find_duplicate(fingerprint) == "original"


def test_simhash_index_returns_none_for_a_different_story():
    index = na.SimHashIndex(bands=4, threshold=3)
    index.add(na.simhash(_SIM_BASE), "original")
    assert index.find_duplicate(na.simhash(_SIM_UNRELATED)) is None


# --------------------------------------------------------------------------
# MinHash — the signal near-duplicate suppression actually decides on
# --------------------------------------------------------------------------

_MINHASH_BASE = _SIM_BASE
_MINHASH_UNRELATED = "Foreign exchange reserves increased by two hundred million dollars this week"


def test_minhash_signature_is_deterministic_and_fixed_length():
    assert na.minhash_signature(_MINHASH_BASE) == na.minhash_signature(_MINHASH_BASE)
    assert len(na.minhash_signature(_MINHASH_BASE)) == na._MINHASH_ROWS


def test_minhash_signature_empty_for_too_little_text():
    assert na.minhash_signature("two words") == []


def test_minhash_estimates_full_similarity_for_identical_text():
    assert na.signature_similarity(
        na.minhash_signature(_MINHASH_BASE), na.minhash_signature(_MINHASH_BASE)
    ) == pytest.approx(1.0)


def test_minhash_estimates_near_zero_for_unrelated_text():
    estimate = na.signature_similarity(
        na.minhash_signature(_MINHASH_BASE), na.minhash_signature(_MINHASH_UNRELATED)
    )
    assert estimate < 0.2


def test_minhash_keeps_a_one_word_edit_well_above_the_unrelated_baseline():
    # The whole reason MinHash is here: the same edit that defeats SimHash still
    # scores dramatically higher than an unrelated story.
    edited = _MINHASH_BASE.replace("a record", "record").replace("the northern", "northern")
    edited_score = na.signature_similarity(
        na.minhash_signature(_MINHASH_BASE), na.minhash_signature(edited)
    )
    unrelated_score = na.signature_similarity(
        na.minhash_signature(_MINHASH_BASE), na.minhash_signature(_MINHASH_UNRELATED)
    )
    assert edited_score > unrelated_score
    assert edited_score > 0.5
    assert unrelated_score < 0.2


def test_minhash_detects_a_long_article_with_one_number_changed():
    paragraph = (
        "The company said the plant expansion would be completed next year and would "
        "raise capacity by two million tons of cement annually "
    ) * 6
    edited = paragraph.replace("two million tons", "2.5 million tons")
    assert na.signature_similarity(
        na.minhash_signature(paragraph), na.minhash_signature(edited)
    ) >= 0.8


def test_signature_similarity_rejects_mismatched_lengths():
    assert na.signature_similarity([1, 2, 3], [1, 2]) == 0.0
    assert na.signature_similarity([], []) == 0.0


def test_signature_encode_decode_round_trip():
    signature = na.minhash_signature(_MINHASH_BASE)
    encoded = na.encode_signature(signature)
    assert na.decode_signature(encoded) == signature
    assert na.decode_signature(None) == []
    assert na.decode_signature("") == []
    assert na.decode_signature("not-hex,zzz") == []


def test_minhash_index_finds_a_duplicate_before_and_after_a_round_trip():
    index = na.MinHashIndex(rows=24, band_rows=4, threshold=0.8)
    signature = na.minhash_signature(_MINHASH_BASE)
    index.add(na.decode_signature(na.encode_signature(signature)), "article-1")
    assert index.find_duplicate(signature) == "article-1"


def test_minhash_index_returns_none_for_unrelated_text():
    index = na.MinHashIndex(rows=24, band_rows=4, threshold=0.8)
    index.add(na.minhash_signature(_MINHASH_BASE), "article-1")
    assert index.find_duplicate(na.minhash_signature(_MINHASH_UNRELATED)) is None


def test_minhash_index_ignores_wrong_length_signatures():
    index = na.MinHashIndex(rows=24, band_rows=4)
    index.add([1, 2, 3], "x")
    assert len(index) == 0
    assert index.find_duplicate([1, 2, 3]) is None


def test_minhash_index_requires_an_even_band_split():
    with pytest.raises(ValueError):
        na.MinHashIndex(rows=24, band_rows=5)


def test_simhash_index_rejects_an_impossible_configuration():
    with pytest.raises(ValueError):
        na.SimHashIndex(bands=3, threshold=3)


def test_simhash_index_len_counts_distinct_payloads():
    index = na.SimHashIndex()
    assert len(index) == 0
    index.add(na.simhash("a b c d e f g h"), "p1")
    index.add(0, "ignored")  # zero fingerprints are not indexable
    assert len(index) == 1


# --------------------------------------------------------------------------
# headline-level duplicate detection
# --------------------------------------------------------------------------

def test_normalize_title_is_punctuation_insensitive():
    assert na.normalize_title("PSX: KSE-100 hits record!") == na.normalize_title("psx kse 100 hits record")


def test_is_duplicate_title_catches_truncation():
    # Overlap coefficient, not Jaccard: a truncated headline is still the same story.
    assert na.is_duplicate_title(
        "Acme Cement posts record quarterly profit and declares dividend",
        "Acme Cement posts record quarterly profit",
    )


def test_is_duplicate_title_rejects_unrelated_headlines():
    assert not na.is_duplicate_title(
        "Acme Cement posts record quarterly profit",
        "Central bank holds policy rate unchanged",
    )


def test_overlap_coefficient_bounds():
    assert na.overlap_coefficient("", "anything") == 0.0
    assert na.overlap_coefficient("alpha beta", "alpha beta") == pytest.approx(1.0)


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------

_DOCS = [
    (1, "Acme Cement posts record profit", "cement dispatches rose while costs fell"),
    (2, "Central bank holds policy rate", "monetary policy committee kept the benchmark rate"),
    (3, "Cement demand weakens in the north", "northern cement dispatches declined"),
]


def test_bm25_ranks_headline_match_first():
    index = na.BM25Index(_DOCS, title_boost=2.5)
    ranked = index.search("cement", fuzzy=False)
    assert ranked and ranked[0][0] in {1, 3}


def test_bm25_ignores_documents_with_no_query_term():
    index = na.BM25Index(_DOCS)
    assert all(doc_id != 2 for doc_id, _ in index.search("cement", fuzzy=False))


def test_bm25_empty_query_returns_nothing():
    assert na.BM25Index(_DOCS).search("   ") == []


def test_bm25_fuzzy_expansion_recovers_from_a_typo():
    index = na.BM25Index(_DOCS)
    assert index.search("cemment", fuzzy=False) == []
    assert index.search("cemment", fuzzy=True)


def test_bm25_expand_terms_leaves_short_tokens_alone():
    index = na.BM25Index(_DOCS)
    assert index.expand_terms(["ceed"]) == ["ceed"]


def test_bm25_scores_are_ordered_descending():
    scores = [score for _, score in na.BM25Index(_DOCS).search("cement profit")]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------
# entity linking (spec H: never link an unknown symbol)
# --------------------------------------------------------------------------

def test_extract_symbols_keeps_only_the_real_psx_universe():
    found = na.extract_symbols("OGDC and HBL moved while OILGASX stayed flat")
    assert "OGDC" in found and "HBL" in found
    assert "OILGASX" not in found


def test_extract_symbols_ignores_lowercase_words_that_look_like_tickers():
    # "pol" / "all" / "isl" appear in ordinary prose and must not become tickers.
    assert na.extract_symbols("pol and all isl in the north") == []


def test_extract_symbols_resolves_company_names():
    found = na.extract_symbols("Habib Bank and Meezan Bank both reported results")
    assert "HBL" in found and "MEBL" in found


def test_extract_symbols_is_deduplicated_and_capped():
    text = "OGDC " * 20
    found = na.extract_symbols(text, max_symbols=3)
    assert found == ["OGDC"]


def test_every_company_alias_maps_to_a_real_symbol():
    from app.symbols import PSX_SYMBOLS
    unknown = {name: symbol for name, symbol in na.COMPANY_ALIASES.items()
               if symbol not in PSX_SYMBOLS}
    assert unknown == {}


def test_extract_indices_normalises_variants():
    assert na.extract_indices("KSE-100 rises") == ["KSE100"]
    assert na.extract_indices("kse100 rises") == ["KSE100"]
    assert na.extract_indices("no index mentioned") == []


def test_extract_topics_orders_by_hit_count():
    topics = na.extract_topics("SBP policy rate decision on monetary policy and inflation")
    assert topics[0] in {"monetary-policy", "inflation"}


def test_extract_entities_shape():
    entities = na.extract_entities("OGDC gains as KSE-100 rises on monetary policy")
    kinds = {e.type for e in entities}
    assert {"SYMBOL", "INDEX", "TOPIC"} <= kinds
    assert all(set(e.as_dict()) == {"type", "value", "label"} for e in entities)


# --------------------------------------------------------------------------
# event classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Company announces final dividend of five rupees", "DIVIDEND"),
    ("Board approves rights issue at a premium", "RIGHT_ISSUE"),
    ("Firm completes acquisition of a rival mill", "MERGER_ACQUISITION"),
    ("Quarterly results show profit after tax rising", "EARNINGS"),
    ("Regulator issues show cause notice to broker", "REGULATORY"),
    ("Monetary policy committee raises policy rate", "MONETARY_POLICY"),
    ("Inflation eases as CPI slows", "MACRO_DATA"),
    ("Nothing in particular happened today", "GENERAL"),
])
def test_detect_event(text, expected):
    assert na.detect_event(text) == expected


def test_detect_event_is_case_insensitive():
    assert na.detect_event("FINAL DIVIDEND ANNOUNCED") == "DIVIDEND"


# --------------------------------------------------------------------------
# impact scoring
# --------------------------------------------------------------------------

def test_impact_score_components_sum_to_the_total():
    result = na.impact_score(
        title="Acme posts record dividend",
        excerpt="record profit and a dividend",
        publisher="Dawn",
        published_at=datetime.now(timezone.utc),
        sentiment_score=0.8,
        symbols=["LUCK"],
        event_type="DIVIDEND",
    )
    assert result["score"] == pytest.approx(sum(result["components"].values()), abs=0.01)


def test_impact_score_never_exceeds_one_hundred():
    result = na.impact_score(
        title=" ".join(na.HIGH_IMPACT_TERMS),
        excerpt=" ".join(na.HIGH_IMPACT_TERMS),
        publisher="psx",
        data_source="psx",
        published_at=datetime.now(timezone.utc),
        sentiment_score=1.0,
        symbols=["OGDC", "HBL", "LUCK"],
        event_type="DIVIDEND",
        source_type="PSX_FILING",
    )
    assert 0.0 <= result["score"] <= 100.0


def test_impact_score_decays_with_age():
    now = datetime.now(timezone.utc)
    fresh = na.impact_score(title="Acme profit", published_at=now, now=now)
    old = na.impact_score(title="Acme profit", published_at=now - timedelta(days=5), now=now)
    assert fresh["score"] > old["score"]
    assert old["components"]["recency"] < fresh["components"]["recency"]


def test_impact_score_without_timestamp_gets_no_recency_credit():
    result = na.impact_score(title="Acme profit", published_at=None)
    assert result["components"]["recency"] == 0.0


def test_impact_score_orders_a_dividend_above_a_market_wrap():
    dividend = na.impact_score(title="Dividend approved", event_type="DIVIDEND",
                               publisher="Dawn", published_at=datetime.now(timezone.utc))
    wrap = na.impact_score(title="Stocks end mixed", event_type="MARKET_UPDATE",
                           publisher="Dawn", published_at=datetime.now(timezone.utc))
    assert dividend["score"] > wrap["score"]


def test_source_tier_is_case_and_substring_insensitive():
    assert na.source_tier("Dawn") > na.source_tier("Unknown Blog")
    assert na.source_tier("business recorder") == pytest.approx(na.SOURCE_TIERS["brecorder"])
    assert na.source_tier(None, None) == na.DEFAULT_SOURCE_TIER


@pytest.mark.parametrize("score,expected", [
    (0, "LOW"), (37.9, "LOW"), (38, "NORMAL"), (64.9, "NORMAL"), (65, "HIGH"), (100, "HIGH"),
])
def test_priority_thresholds(score, expected):
    assert na.priority_from_impact(score) == expected


# --------------------------------------------------------------------------
# content stats
# --------------------------------------------------------------------------

def test_content_stats_counts_words():
    assert na.content_stats("one two three")["word_count"] == 3


def test_content_stats_empty_text_reports_zero_not_one_minute():
    assert na.content_stats("") == {"word_count": 0, "reading_time_minutes": 0}


def test_content_stats_minimum_reading_time_is_one_minute():
    assert na.content_stats("hello")["reading_time_minutes"] == 1


# --------------------------------------------------------------------------
# clustering
# --------------------------------------------------------------------------

def _article(article_id, title, excerpt="", **overrides):
    base = {
        "id": article_id, "title": title, "excerpt": excerpt, "content": "",
        "published_at": datetime.now(timezone.utc), "related_symbols": [],
        "event_type": "GENERAL", "impact_score": 40.0,
    }
    base.update(overrides)
    return base


def test_cluster_articles_groups_the_same_story():
    articles = [
        _article(1, "Acme Cement posts record quarterly profit of ten billion rupees"),
        _article(2, "Acme Cement reports record quarterly profit of ten billion rupees"),
        _article(3, "Acme Cement quarterly profit hits record ten billion rupees"),
        _article(4, "Central bank holds the benchmark policy rate unchanged"),
    ]
    clusters = na.cluster_articles(articles, threshold=0.3)
    sizes = sorted((c.size for c in clusters), reverse=True)
    assert sizes[0] == 3
    grouped = next(c for c in clusters if c.size == 3)
    assert sorted(grouped.article_ids) == [1, 2, 3]


def test_cluster_articles_empty_input():
    assert na.cluster_articles([]) == []


def test_cluster_carries_publishers_symbols_and_dates():
    when = datetime.now(timezone.utc) - timedelta(hours=2)
    articles = [
        _article(1, "Acme Cement posts record quarterly profit", publisher="Dawn",
                 published_at=when, related_symbols=["LUCK"], impact_score=70.0),
        _article(2, "Acme Cement posts record quarterly profit too", publisher="Tribune",
                 published_at=when + timedelta(minutes=30), related_symbols=["LUCK"], impact_score=55.0),
    ]
    cluster = na.cluster_articles(articles, threshold=0.3)[0]
    assert set(cluster.publishers) == {"Dawn", "Tribune"}
    assert cluster.symbols == ["LUCK"]
    assert cluster.max_impact == 70.0
    assert cluster.first_seen == when
    payload = cluster.as_dict()
    assert payload["size"] == 2 and payload["first_seen"] and payload["terms"]


def test_cluster_respects_max_clusters():
    # Twelve different stories, so the cap (not the similarity threshold) is
    # what determines how many clusters come back.
    topics = [
        "cement exports rise sharply",
        "refinery maintenance shutdown scheduled",
        "insurance premiums increase this quarter",
        "textile orders recover from Europe",
        "steel rebar prices climb again",
        "pharmaceutical approvals slow down",
        "shipping rates fall on new capacity",
        "automobile sales jump in the month",
        "fertilizer off-take weakens in the north",
        "power tariff adjustment approved by regulator",
        "telecom subscriber base expands rapidly",
        "airline adds new regional routes",
    ]
    articles = [_article(i, f"Report number {i}: {topic}") for i, topic in enumerate(topics)]
    capped = na.cluster_articles(articles, threshold=0.5, max_clusters=5)
    assert len(capped) == 5
    assert len(na.cluster_articles(articles, threshold=0.5, max_clusters=50)) == len(topics)


# --------------------------------------------------------------------------
# trending
# --------------------------------------------------------------------------

def test_trending_weights_recent_mentions_higher():
    now = datetime.now(timezone.utc)
    articles = [
        _article(1, "recent", published_at=now, related_symbols=["OGDC"]),
        _article(2, "older", published_at=now - timedelta(hours=48), related_symbols=["HBL"]),
    ]
    result = na.trending_entities(articles, window_hours=72, half_life_hours=12, now=now)
    by_value = {e["value"]: e for e in result["entities"]}
    assert by_value["OGDC"]["trend_score"] > by_value["HBL"]["trend_score"]
    assert by_value["OGDC"]["count"] == 1


def test_trending_excludes_mentions_outside_the_window():
    now = datetime.now(timezone.utc)
    articles = [_article(1, "old", published_at=now - timedelta(days=30), related_symbols=["OGDC"])]
    assert na.trending_entities(articles, window_hours=24, now=now)["entities"] == []


def test_trending_reports_average_sentiment_per_entity():
    now = datetime.now(timezone.utc)
    articles = [
        _article(1, "a", published_at=now, related_symbols=["OGDC"], sentiment_score=1.0),
        _article(2, "b", published_at=now, related_symbols=["OGDC"], sentiment_score=0.0),
    ]
    entity = na.trending_entities(articles, now=now)["entities"][0]
    assert entity["avg_sentiment"] == pytest.approx(0.5)
    assert entity["count"] == 2
    assert entity["latest_mention"]


def test_trending_includes_topics_and_indices():
    now = datetime.now(timezone.utc)
    articles = [
        _article(1, "a", published_at=now, topics=["monetary-policy"], related_indices=["KSE100"]),
    ]
    kinds = {e["type"] for e in na.trending_entities(articles, now=now)["entities"]}
    assert kinds == {"TOPIC", "INDEX"}


def test_trending_top_n_is_respected():
    now = datetime.now(timezone.utc)
    articles = [_article(i, "x", published_at=now, related_symbols=[s])
                for i, s in enumerate(["OGDC", "HBL", "LUCK", "MCB", "PSO"])]
    assert len(na.trending_entities(articles, top_n=3, now=now)["entities"]) == 3


# --------------------------------------------------------------------------
# the one-call enricher
# --------------------------------------------------------------------------

def test_enrich_emits_a_decodable_shingle_signature():
    enriched = na.enrich({
        "title": "Acme Cement announces final dividend on record profit for the year",
        "excerpt": "The board approved the payout after quarterly results were published.",
        "published_at": datetime.now(timezone.utc),
    })
    decoded = na.decode_signature(enriched["shingle_signature"])
    assert len(decoded) == na._MINHASH_ROWS


def test_fingerprint_text_bounds_the_length():
    long_text = "word " * (na.FINGERPRINT_TOKEN_LIMIT + 500)
    assert len(na.tokenize_all(na.fingerprint_text(long_text))) == na.FINGERPRINT_TOKEN_LIMIT


def test_fingerprint_text_leaves_short_text_untouched():
    assert na.fingerprint_text("short text") == "short text"


def test_enrich_sets_every_analytics_field():
    enriched = na.enrich({
        "title": "Acme Cement announces final dividend on record profit",
        "excerpt": "The board approved a payout after quarterly results.",
        "content": "Body text.",
        "publisher": "Dawn",
        "data_source": "rss:dawn_business",
        "published_at": datetime.now(timezone.utc),
        "related_symbols": [],
        "related_indices": [],
        "sentiment_score": 0.5,
    })
    assert enriched["event_type"] == "DIVIDEND"
    assert enriched["priority"] in {"HIGH", "NORMAL", "LOW"}
    assert enriched["impact_score"] > 0
    assert set(enriched["impact_components"]) == {"event", "source", "entities", "signal", "recency"}
    assert enriched["simhash"] != 0
    assert enriched["entities"]
    assert enriched["topics"]


def test_enrich_keeps_a_supplied_valid_symbol():
    enriched = na.enrich({
        "title": "Company reports results",
        "related_symbols": ["OGDC"],
        "published_at": datetime.now(timezone.utc),
    })
    assert "OGDC" in enriched["related_symbols"]


def test_enrich_drops_an_invalid_supplied_symbol():
    enriched = na.enrich({
        "title": "Company reports results",
        "related_symbols": ["NOTATICKER"],
        "published_at": datetime.now(timezone.utc),
    })
    assert enriched["related_symbols"] == []


def test_enrich_does_not_mutate_its_input():
    original = {"title": "Acme profit", "related_symbols": [], "published_at": datetime.now(timezone.utc)}
    snapshot = dict(original)
    na.enrich(original)
    assert original == snapshot


def test_enrich_uses_the_corpus_when_given_one():
    corpus = na.TfIdfCorpus([
        "cement company profit",
        "cement company profit",
        "refinery maintenance shutdown",
    ])
    enriched = na.enrich(
        {"title": "cement company profit refinery maintenance shutdown",
         "published_at": datetime.now(timezone.utc)},
        corpus=corpus,
    )
    assert enriched["keywords"]
