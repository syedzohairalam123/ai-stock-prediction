"""Phase 4 — announcements service tests. No network in tests: the parser,
classifier, extractor, filters and pagination are exercised against a frozen
snapshot of the real mirror layout (verified live 2026-09-09)."""
import asyncio
from datetime import date

import pytest

from app.announcements import (
    AI_DISCLAIMER,
    ANN_EVENTS,
    ANN_SENTIMENTS,
    AnnouncementFiltersModel,
    _assembled,
    _paginate,
    apply_filters,
    build_simulated_announcements,
    classify_event,
    detect_sentiment,
    extract_structured_fields,
    get_announcements_feed,
    summarize_announcement,
)

MIRROR_SNAPSHOT = """
<table id="ans">
<tr class="data-tr">
 <td class="title text-pink">Pakistan Paper Products Limited<br>(PPP)</td>
 <td class="plain">September 9th, 2026</td>
 <td>FINANCIAL RESULT FOR THE YEAR ENDED 30/06/2026<br>
     PROFIT/LOSS BEFORE TAXATION RS. IN MILLION 225.277<br>
     PROFIT/LOSS AFTER TAXATION RS. IN MILLION 165.862<br>
     EPS = 20.73<br>DIVIDEND = 80%(F)<br>
     ANNUAL GENERAL MEETING WILL BE HELD ON 21/10/2026<br>
     BOOK CLOSURE FROM 19/10/2026<br>BOOK CLOSURE TO 21/10/2026</td>
</tr>
<tr class="data-tr">
 <td>Synthetic Chem Ltd (SCL)</td>
 <td>September 8th, 2026</td>
 <td>INSIDER DEALING<br>MR. AHMED KHAN SOLD 25,000 SHARES @ RS. 24.10</td>
</tr>
<tr class="data-tr">
 <td>Big Bank (HBL)</td>
 <td>08-09-2026</td>
 <td>ISSUE OF BONUS SHARES<br>THE BOARD HAS RECOMMENDED ISSUE OF 20% BONUS SHARES</td>
</tr>
</table>
"""


def _parsed():
    from app.announcements import _parse_announcements_html
    return _parse_announcements_html(MIRROR_SNAPSHOT)


def test_parse_real_mirror_layout():
    rows = _parsed()
    assert len(rows) == 3
    first = rows[0]
    assert first["ticker"] == "PPP"
    assert "Pakistan Paper" in first["company"]
    assert first["published"] == date(2026, 9, 9)
    assert first["title"].startswith("FINANCIAL RESULT")
    assert "EPS = 20.73" in first["body"]


def test_classify_events():
    assert classify_event("FINANCIAL RESULT FOR THE YEAR ENDED 30/06/2026 EPS = 20.73") == "FINANCIAL_RESULTS"
    assert classify_event("ANNUAL GENERAL MEETING WILL BE HELD ON 21/10/2026") == "AGM"
    assert classify_event("ISSUE OF BONUS SHARES 20%") == "BONUS_SHARES"
    assert classify_event("INSIDER DEALING MR X SOLD 25,000 SHARES @ RS. 24.10") == "INSIDER_SALE"
    assert classify_event("ISSUE OF RIGHTS SHARES SUBSCRIPTION 25% @ RS. 95") == "RIGHTS_ISSUE"
    assert classify_event("EOGM WILL BE HELD ON 12/11") == "EGM"
    assert classify_event("SECP CIRCULAR RECEIVED") == "REGULATORY_NOTICE"
    assert classify_event("BOOK CLOSURE FROM 19/10/2026") == "CORPORATE_ACTION"
    assert classify_event("PROFIT WARNING — COMPANY EXPECTS A LOSS") == "PROFIT_WARNING"
    assert classify_event("CONTRACT AWARDED WORTH RS 1.2 BILLION") == "CONTRACT_AWARD"
    assert classify_event("APPOINTMENT OF CHIEF FINANCIAL OFFICER") == "MANAGEMENT_CHANGE"
    assert classify_event("ACQUISITION OF EXPLORATION BLOCK") == "ACQUISITION"
    assert classify_event("SCHEME OF ARRANGEMENT APPROVED") == "MERGER"
    assert classify_event("HELLO WORLD") == "OTHER"


def test_sentiment_labeled_and_consistent():
    for text in ["EPS = 20.73 DIVIDEND = 80%(F)", "COMPANY EXPECTS A LOSS", "AGM ON 21/10"]:
        s = detect_sentiment(text, classify_event(text))
        assert s in ANN_SENTIMENTS
    assert detect_sentiment("DIVIDEND = 250%(F)", "DIVIDEND") == "POSITIVE"
    assert detect_sentiment("EXPECTS A LOSS", "PROFIT_WARNING") == "NEGATIVE"


def test_structured_extraction_never_fabricates():
    f = extract_structured_fields(
        "FINANCIAL RESULT EPS = 20.73\nDIVIDEND = 80%(F)\n"
        "ANNUAL GENERAL MEETING WILL BE HELD ON 21/10/2026\n"
        "BOOK CLOSURE FROM 19/10/2026\nBOOK CLOSURE TO 21/10/2026"
    )
    assert f["eps"] == "20.73"
    assert f["dividend"] == "80%(F)"
    assert f["effective_date"] == "21/10/2026"
    assert f["book_closure_from"] == "19/10/2026"
    assert f["book_closure_to"] == "21/10/2026"
    assert f["shares"] is None and f["price"] is None

    g = extract_structured_fields("INSIDER DEALING MR. AHMED KHAN SOLD 25,000 SHARES @ RS. 24.10")
    assert g["shares"] == "25,000"
    assert g["price"] == "PKR 24.10"
    assert g["total_value"] == "PKR 602,500.00"
    assert g["action"] == "Sold"
    assert "AHMED" in (g["person"] or "").upper()
    assert g["eps"] is None  # absent field stays None — never invented


def test_summarize_labels_ai_content():
    out = summarize_announcement("FINANCIAL RESULT EPS = 5.0")
    assert out["event"] == "FINANCIAL_RESULTS"
    assert out["sentiment_meta"]["icon"] and out["sentiment_meta"]["label"]
    assert out["disclaimer"] == AI_DISCLAIMER
    assert out["engine"].startswith("rule-based")


def test_assembled_records_shape():
    items = _assembled(_parsed(), "company", "LIVE")
    assert len(items) == 3
    a = items[0]
    assert a["id"].startswith("ann-")
    assert a["source_status"] == "LIVE"
    assert a["ticker_confident"] is True
    assert a["event"] in ANN_EVENTS
    assert a["structured"]["eps"] == "20.73"
    # dedup: assembling twice yields same ids
    assert [x["id"] for x in _assembled(_parsed(), "company", "LIVE")] == [x["id"] for x in items]


def test_filters_search_event_sentiment_date():
    items = _assembled(_parsed(), "company", "LIVE")
    f = AnnouncementFiltersModel(search="bonus")
    hits = apply_filters(items, f)
    assert len(hits) == 1 and hits[0]["ticker"] == "HBL"

    f = AnnouncementFiltersModel(event="INSIDER_SALE")
    assert len(apply_filters(items, f)) == 1

    f = AnnouncementFiltersModel(sentiment="POSITIVE")
    assert all(a["sentiment"] == "POSITIVE" for a in apply_filters(items, f))

    f = AnnouncementFiltersModel(ticker="PPP")
    assert len(apply_filters(items, f)) == 1 and apply_filters(items, f)[0]["ticker"] == "PPP"

    f = AnnouncementFiltersModel(date_from="2026-09-09", date_to="2026-09-09")
    assert len(apply_filters(items, f)) == 1

    f = AnnouncementFiltersModel(page=2, page_size=2)
    pg = _paginate(apply_filters(items, f), f)
    assert pg["page"] == 2 and pg["total_pages"] == 2 and pg["has_more"] is False


def test_company_filter_is_case_insensitive_partial_match():
    items = _assembled(_parsed(), "company", "LIVE")
    hits = apply_filters(items, AnnouncementFiltersModel(company="paper"))
    assert len(hits) == 1 and hits[0]["ticker"] == "PPP"
    assert apply_filters(items, AnnouncementFiltersModel(company="PAPER"))[0]["ticker"] == "PPP"
    assert apply_filters(items, AnnouncementFiltersModel(company="no such company")) == []


def test_filters_model_validation():
    with pytest.raises(ValueError):
        AnnouncementFiltersModel(source="bogus")
    with pytest.raises(ValueError):
        AnnouncementFiltersModel(event="NOT_AN_EVENT")
    with pytest.raises(ValueError):
        AnnouncementFiltersModel(sentiment="NOPE")
    with pytest.raises(ValueError):
        AnnouncementFiltersModel(page=0)


def test_simulated_dataset_is_labeled_demo():
    items = build_simulated_announcements()
    assert len(items) >= 12
    assert all(a["source"] == "simulated" and a["source_status"] == "SIMULATED" for a in items)
    assert all("DEMO" in a["title"] for a in items)
    events = {a["event"] for a in items}
    assert {"FINANCIAL_RESULTS", "BONUS_SHARES", "INSIDER_SALE", "INSIDER_PURCHASE",
            "RIGHTS_ISSUE", "PROFIT_WARNING", "CONTRACT_AWARD"} <= events
    f = AnnouncementFiltersModel(source="simulated", sentiment="NEGATIVE")
    neg = apply_filters(items, f)
    assert neg and all(a["sentiment"] == "NEGATIVE" for a in neg)


def test_feed_simulated_end_to_end():
    async def run():
        return await get_announcements_feed(AnnouncementFiltersModel(source="simulated", page_size=5))
    out = asyncio.run(run())
    assert out["source_status"] == "SIMULATED"
    assert out["page_size"] == 5 and len(out["items"]) == 5
    assert out["total_pages"] >= 3
    assert out["ai_disclaimer"] == AI_DISCLAIMER
