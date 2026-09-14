"""
PSX Announcements, Filings & AI Intelligence (Phase 4).

REAL DATA FIRST — this module fetches live company announcements from the
public PSX-announcement mirror ksestocks.com (server-rendered HTML of the
official exchange feed; no API key, no JS rendering). It exists so the app
ships a REAL announcements feed today while keeping a single, documented
swap-in point for the official PSX Data Portal (dps.psx.com.pk) API.

HONESTY RULES (enforced in code, mirrored in the UI):
  * The feed reports `source_status: LIVE` when the mirror was reachable,
    `UNAVAILABLE` when it was not. We never serve a fabricated "live" feed.
  * Event category & sentiment come from deterministic, rule-based
    classification of the REAL announcement text — clearly labeled as
    AI/heuristic ANALYSIS, never presented as an official PSX statement.
  * Structured fields (EPS, dividend, shares, price, dates...) are only
    emitted when the source text actually contains them. Missing fields
    stay None. NOTHING is ever inferred into existence.
  * The `simulated` source is a clearly-labeled demo dataset for UI
    development and testing. Tickers are real PSX symbols, but every
    announcement body is synthetic demo content — never a claim about a
    real company.

Public API:
    get_announcements_feed(filters) -> dict   # UI-ready, cache-backed
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

import httpx

from .logging_config import get_logger
from .security import validate_ticker

logger = get_logger("neural_market.announcements")

# ---------------------------------------------------------------------------
# Types (mirrored 1:1 in the frontend `lib/announcements.ts`)
# ---------------------------------------------------------------------------

AnnEvent = Literal[
    "RIGHTS_ISSUE", "BONUS_SHARES", "DIVIDEND", "AGM", "EGM",
    "INSIDER_SALE", "INSIDER_PURCHASE", "MANAGEMENT_CHANGE", "BOARD_CHANGE",
    "FINANCIAL_RESULTS", "PROFIT_WARNING", "ACQUISITION", "MERGER",
    "CONTRACT_AWARD", "CORPORATE_ACTION", "REGULATORY_NOTICE", "OTHER",
]
AnnSentiment = Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"]
AnnSource = Literal["company", "simulated"]
AnnSourceStatus = Literal["LIVE", "UNAVAILABLE", "SIMULATED"]

ANN_EVENTS: tuple[str, ...] = (
    "RIGHTS_ISSUE", "BONUS_SHARES", "DIVIDEND", "AGM", "EGM",
    "INSIDER_SALE", "INSIDER_PURCHASE", "MANAGEMENT_CHANGE", "BOARD_CHANGE",
    "FINANCIAL_RESULTS", "PROFIT_WARNING", "ACQUISITION", "MERGER",
    "CONTRACT_AWARD", "CORPORATE_ACTION", "REGULATORY_NOTICE", "OTHER",
)
ANN_SENTIMENTS: tuple[str, ...] = ("POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL")

#: icon + accessible label — the UI must never rely on color alone
SENTIMENT_META: dict[str, dict[str, str]] = {
    "POSITIVE": {"icon": "▲", "label": "Positive sentiment"},
    "NEGATIVE": {"icon": "▼", "label": "Negative sentiment"},
    "MIXED":    {"icon": "◆", "label": "Mixed sentiment"},
    "NEUTRAL":  {"icon": "●", "label": "Neutral sentiment"},
}

AI_DISCLAIMER = (
    "AI-generated analysis (deterministic rule-based extraction), not an "
    "official PSX statement. Always verify against the original filing."
)
SOURCE_DISCLAIMER = (
    "Announcement text sourced from a public PSX announcements mirror "
    "(ksestocks.com); verify against official PSX filings before acting."
)

# ---------------------------------------------------------------------------
# Live source: ksestocks.com/Announcements (verified server-rendered mirror)
# ---------------------------------------------------------------------------

_KSE_BASE = "https://www.ksestocks.com/Announcements"
_HTTP_TIMEOUT = 20.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y")


def _squash(text: Optional[str]) -> str:
    """Collapse whitespace; announce bodies arrive as <br>-separated lines."""
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_tags(html: str) -> str:
    """Tag-stripper that KEEPS <br> as newlines (announce bodies need them)."""
    html = re.sub(r"(?i)<br\s*/?>", "\n", html or "")
    html = re.sub(r"(?i)</p\s*>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    return html.replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')


def _parse_date(raw: str) -> Optional[date]:
    txt = _squash(raw)
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", txt)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    cleaned = re.sub(r"(\d)(st|nd|rd|th)", r"\1", txt)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _pk_today(now: Optional[datetime] = None) -> date:
    """Pakistan Calendar Date (UTC+5) — PSX publishes against the PKT clock."""
    return (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=5))).date()


async def _fetch_announcements_html(client: httpx.AsyncClient) -> str:
    """Fetch the live mirror page. Raises ProviderError-style RuntimeError on
    any failure so the caller can report UNAVAILABLE instead of guessing."""
    resp = await client.get(_KSE_BASE, headers={"User-Agent": _UA}, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    if "id=\"ans\"" not in resp.text:
        raise RuntimeError("announcements table missing from mirror page (layout change?)")
    return resp.text


def _parse_announcements_html(html: str) -> list[dict]:
    """Parse rows from <table id="ans">. Layout (verified live 2026-09):
    tr.data-tr > td: [company cell 'Name (TICKER)', date cell, body cell]."""
    table_m = re.search(r"<table[^>]*id=\"ans\"[^>]*>(.*?)</table>", html, re.S)
    if not table_m:
        return []
    rows = re.findall(r"<tr[^>]*class=\"data-tr\"[^>]*>(.*?)</tr>", table_m.group(1), re.S)
    records: list[dict] = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 3:
            continue
        company_cell = _strip_tags(cells[0])
        body_html = _strip_tags(cells[2])
        title = _title_from_body(body_html)
        if not title:
            continue
        name_m = re.match(r"\s*(.+?)\s*\(([^()]{1,12})\)\s*$", company_cell)
        company = _squash(name_m.group(1)) if name_m else company_cell
        ticker = _squash(name_m.group(2)).upper() if name_m else None
        published = _parse_date(_strip_tags(cells[1]))
        records.append({
            "company": company,
            "ticker": ticker,
            "published": published,
            "title": title,
            "body": body_html,
            "source_url": _KSE_BASE,
        })
    return records


def _title_from_body(body: str) -> str:
    """The mirror carries no separate title column; the first meaningful body
    line IS the announcement subject — derive it, never invent one."""
    for line in (body or "").split("\n"):
        line = _squash(line)
        if line:
            return line[:180]
    return ""


# ---------------------------------------------------------------------------
# Rule-based classification (deterministic; part of the labeled AI analysis)
# ---------------------------------------------------------------------------

#: ordered — first match wins; most specific patterns first
ANN_EVENT_PATTERNS: tuple[tuple[str, str], ...] = (
    # FINANCIAL_RESULTS outranks DIVIDEND/BONUS: result filings mention payouts,
    # but the filing's subject is the result (payout stays in structured fields).
    ("FINANCIAL_RESULTS", r"\bFINANCIAL\s+RESULT\b|\b(?:QUARTERLY|ANNUAL|HALF[- ]?YEARLY)\s+(?:REPORT|ACCOUNTS|RESULT)\b|\bEPS\b|\bUNAUDITED\b.*\bACCOUNTS\b"),
    ("RIGHTS_ISSUE", r"\bRIGHTS?(?:\s+SHARES?)?\b.*\bSUBSCRIPTION\b|\bISSUE\s+OF\s+RIGHTS?\b|\bRIGHTS?\b\s+(?:CIRCULAR|SUBSCRIPTION)"),
    ("BONUS_SHARES", r"\bBONUS\s+(?:SHARES|STOCK|ISSUE)\b|\bISSUE\s+OF\s+BONUS\b"),
    ("DIVIDEND", r"\bDIVIDEND\b|\bPAYOUT\b"),
    ("INSIDER_PURCHASE", r"\bINSIDER\b.*\b(PURCHASE\w*|BUY\w*|BOUGHT)\b|\bPURCHASED?\s+\d[\d,]*\s+SHARES\b"),
    ("INSIDER_SALE", r"\bINSIDER\b.*\b(SOLD|SALE|SELL\w*)\b|\bSOLD\s+\d[\d,]*\s+SHARES\b"),
    ("MANAGEMENT_CHANGE", r"\b(?:CEO|CFO|COO|CHIEF\s+EXECUTIVE|CHIEF\s+FINANCIAL|MANAGING\s+DIRECTOR|APPOINTMENT|RESIGNATION)\b"),
    ("BOARD_CHANGE", r"\bBOARD\s+(?:MEETING|OF\s+DIRECTORS)\b|\bDIRECTOR(?:S)?\s+(?:ELECT|APPOINTED|RESIGNED)\b|\bCHAIRMAN\b"),
    ("FINANCIAL_RESULTS", r"\bFINANCIAL\s+RESULT\b|\b(?:QUARTERLY|ANNUAL|HALF[- ]?YEARLY)\s+(?:REPORT|ACCOUNTS|RESULT)\b|\bEPS\b|\bUNAUDITED\b.*\bACCOUNTS\b"),
    ("PROFIT_WARNING", r"\bPROFIT\s+(?:WARNING|ALERT)\b|\bEXPECTS?\s+(?:A\s+)?LOSS\b|\bMATERIAL\s+DECLINE\b"),
    ("ACQUISITION", r"\bACQUISITION\b|\bACQUIRE\b"),
    ("MERGER", r"\bMERGER\b|\bAMALGAMATION\b|\bSCHEME\s+OF\s+ARRANGEMENT\b"),
    ("CONTRACT_AWARD", r"\bCONTRACT\s+(?:AWARD|WIN|SIGN)\b|\bAWARDED\b|\bLOI\b"),
    ("AGM", r"\bANNUAL\s+GENERAL\s+MEETING\b|\bAGM\b"),
    ("EGM", r"\bEXTRAORDINARY\s+GENERAL\s+MEETING\b|\bEOGM\b|\bEGM\b"),
    ("REGULATORY_NOTICE", r"\bSECP\b|\bSRO\b|\bCIRCULAR\b|\bNOTICE\s+FROM\s+REGULATOR\b|\bCOMPLIANCE\b"),
    ("CORPORATE_ACTION", r"\bBOOK\s+CLOSURE\b|\bSHARE\s+REGISTER\b|\bDELISTING\b|\bSUSPENSION\b|\bCAPITAL\s+REDUCTION\b"),
)


def classify_event(text: str) -> AnnEvent:
    up = (text or "").upper()
    for event, pattern in ANN_EVENT_PATTERNS:
        if re.search(pattern, up):
            return event  # type: ignore[return-value]
    return "OTHER"


_EVENT_PHRASE: dict[str, str] = {
    "RIGHTS_ISSUE": "rights subscription announced", "BONUS_SHARES": "bonus shares announced",
    "DIVIDEND": "dividend announced", "AGM": "annual general meeting scheduled",
    "EGM": "extraordinary general meeting scheduled", "INSIDER_SALE": "insider sale disclosed",
    "INSIDER_PURCHASE": "insider purchase disclosed", "MANAGEMENT_CHANGE": "management change announced",
    "BOARD_CHANGE": "board change announced", "FINANCIAL_RESULTS": "financial results published",
    "PROFIT_WARNING": "profit warning issued", "ACQUISITION": "acquisition announced",
    "MERGER": "merger / scheme of arrangement announced", "CONTRACT_AWARD": "contract awarded",
    "CORPORATE_ACTION": "corporate action announced", "REGULATORY_NOTICE": "regulatory notice received",
    "OTHER": "announcement filed",
}

_EVENT_SENTIMENT: dict[str, str] = {
    "BONUS_SHARES": "POSITIVE", "DIVIDEND": "POSITIVE", "CONTRACT_AWARD": "POSITIVE",
    "FINANCIAL_RESULTS": "POSITIVE", "INSIDER_PURCHASE": "POSITIVE", "ACQUISITION": "MIXED",
    "MERGER": "MIXED", "RIGHTS_ISSUE": "MIXED", "PROFIT_WARNING": "NEGATIVE",
    "INSIDER_SALE": "NEGATIVE",
}


def detect_sentiment(text: str, event: AnnEvent) -> AnnSentiment:
    """Event prior + word-level adjustments. Same spirit as app/news.py's
    lexicon heuristic — deliberately simple and honestly labeled."""
    up = (text or "").upper()
    base = _EVENT_SENTIMENT.get(event, "NEUTRAL")
    score = {"POSITIVE": 1, "MIXED": 0, "NEUTRAL": 0, "NEGATIVE": -1}[base]
    if re.search(r"\bLOSS\b|\bDECLINE\b|\bDROP(?:PED)?\b|\bFALL\b|\bDOWN\b", up):
        score -= 1
    if re.search(r"\bPROFIT\b|\bGROWTH\b|\bRECORD\b|\bINCREASE\b|\bUP\s?\d|\bHIGHER\b|\bSURPLUS\b", up):
        score += 1
    return "POSITIVE" if score >= 1 else "NEGATIVE" if score <= -1 else "MIXED" if base == "MIXED" else "NEUTRAL"


# ---------------------------------------------------------------------------
# Structured extraction — ONLY fields literally present in the source text
# ---------------------------------------------------------------------------

_PK_NUM = r"(\d[\d,]*(?:\.\d+)?)"
#: capture-free numeric token for composing multi-number patterns
_PK_NUM_NC = r"\d[\d,]*(?:\.\d+)?"
_RS = r"(?:RS\.?|PKR)\s*"
_RS_OPT = r"(?:(?:RS\.?|PKR)\s*)?"


def _fmt_int(v: str) -> str:
    return f"{int(float(v.replace(',', ''))):,}"


def _fmt_pkr(v: str) -> str:
    num = float(v.replace(",", ""))
    return f"PKR {num:,.2f}"


def extract_structured_fields(text: str) -> dict:
    """Regex extraction from the REAL body. Every field stays None unless the
    source literally contains it — no inference, no fabrication."""
    t = text or ""
    up = t.upper()
    out: dict = {
        "eps": None, "dividend": None, "bonus": None, "rights": None,
        "person": None, "action": None, "shares": None, "price": None,
        "total_value": None, "effective_date": None,
        "book_closure_from": None, "book_closure_to": None,
    }
    if m := re.search(rf"\bEPS\s*=?\s*{_RS_OPT}{_PK_NUM}", up) or re.search(rf"\bEPS\b[: ]+{_RS_OPT}{_PK_NUM}", up):
        out["eps"] = _squash(m.group(1))
    if m := re.search(r"\bDIVIDEND\s*=\s*([^\n]{0,40})", up):
        out["dividend"] = _squash(m.group(1))
    else:
        m = re.search(rf"\b(?:INTERIM|FINAL|CASH)\s+DIVIDEND\b[^\n]*?{_RS_OPT}{_PK_NUM}\s*%", up)
        if m:
            out["dividend"] = _squash(m.group(0))
    if m := re.search(r"\bBONUS[^\n]{0,60}?(\d[\d,]*(?:\.\d+)?)\s*%", up):
        out["bonus"] = f"{_squash(m.group(1))}%"
    if m := re.search(rf"\bRIGHTS?[^\n]{0,60}?(\d[\d,]*(?:\.\d+)?)\s*%[^\n]*?@\s*{_RS_OPT}{_PK_NUM}", up):
        out["rights"] = f"{_squash(m.group(1))}% @ PKR {m.group(2)}"
    if m := re.search(r"(?:\bMR\.?|\bM\/S|\bMRS\.?|\bSYED|\bMUHAMMAD|\bMUHAMMAD)\s+([A-Z][A-Za-z. ]{2,60})", t):
        out["person"] = _squash(m.group(0))
    if re.search(r"\bSOLD\b", up):
        out["action"] = "Sold"
    elif re.search(r"\bPURCHASED?\b|\bBOUGHT\b", up):
        out["action"] = "Purchased"
    if m := re.search(rf"({_PK_NUM_NC})\s*(?:SHARES?|SCRIPTS?)\s*(?:@|AT|VIA|THROUGH)?\s*{_RS_OPT}({_PK_NUM_NC})?", up):
        out["shares"] = _fmt_int(m.group(1))
        if m.group(2) and float(m.group(2).replace(",", "")) > 0.01:
            out["price"] = _fmt_pkr(m.group(2))
            try:
                out["total_value"] = f"PKR {float(m.group(1).replace(',', '')) * float(m.group(2).replace(',', '')):,.2f}"
            except (ValueError, OverflowError):
                pass
    for key, pat in (("effective_date", r"\b(?:ANNUAL\s+GENERAL\s+MEETING|AGM|EXTRAORDINARY\s+GENERAL\s+MEETING|EOGM|EGM)\b[^\n]{0,60}?ON\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})"),
                     ("book_closure_from", r"\bBOOK\s+CLOSURE\s+FROM\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})"),
                     ("book_closure_to", r"\bBOOK\s+CLOSURE\s+TO\s+(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})")):
        if m := re.search(pat, up):
            out[key] = m.group(1)
    return out


def build_highlights(text: str, event: AnnEvent, fields: dict) -> list[str]:
    """Bullet highlights — the important facts, dates and figures found in the
    body. Deterministic; drawn ONLY from source text."""
    highlights: list[str] = []
    if fields.get("eps"):
        highlights.append(f"EPS reported at {fields['eps']}")
    if fields.get("dividend"):
        highlights.append(f"Dividend: {fields['dividend']}")
    if fields.get("bonus"):
        highlights.append(f"Bonus issue: {fields['bonus']}")
    if fields.get("rights"):
        highlights.append(f"Rights issue: {fields['rights']}")
    if fields.get("effective_date"):
        highlights.append(f"Meeting/effective date: {fields['effective_date']}")
    if fields.get("book_closure_from"):
        bc = f"Book closure {fields['book_closure_from']}"
        if fields.get("book_closure_to"):
            bc += f" to {fields['book_closure_to']}"
        highlights.append(bc)
    if fields.get("shares"):
        shares_txt = f"{fields['shares']} shares"
        if fields.get("price"):
            shares_txt += f" at {fields['price']}"
        if fields.get("total_value"):
            shares_txt += f" (total {fields['total_value']})"
        if fields.get("person"):
            highlights.append(f"{fields['person']} — {fields['action'] or 'trade'}: {shares_txt}")
        else:
            highlights.append(shares_txt)
    if not highlights:
        highlights.append(_squash(_title_from_body(text))[:160] or f"{_EVENT_PHRASE[event].capitalize()}")
    return highlights[:6]


def summarize_announcement(text: str) -> dict:
    """Rule-based AI summary. Same philosophy as app/news.py: deterministic,
    dependency-free, and ALWAYS labeled as AI analysis in the UI."""
    event = classify_event(text)
    sentiment = detect_sentiment(text, event)
    fields = extract_structured_fields(text)
    return {
        "event": event,
        "sentiment": sentiment,
        "sentiment_meta": SENTIMENT_META[sentiment],
        "highlights": build_highlights(text, event, fields),
        "structured": fields,
        "engine": "rule-based-v1",
        "disclaimer": AI_DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Simulated (demo) dataset — clearly labeled, never a claim about real firms
# ---------------------------------------------------------------------------

def _sim_records() -> list[dict]:
    """Synthetic demo records spanning many categories. Tickers are real PSX
    symbols so UI linking works; ALL announcement content is fabricated demo
    text for interface development only."""
    def days_ago(n: int) -> date:
        return _pk_today() - timedelta(days=n)
    return [
        {"company": "Demo Fertilizer Ltd", "ticker": "FFC", "published": days_ago(1), "source_url": _KSE_BASE,
         "title": "DEMO — FINANCIAL RESULT FOR THE YEAR ENDED 30/06",
         "body": "DEMO RECORD — SIMULATED CONTENT\nFINANCIAL RESULT FOR THE YEAR ENDED 30/06\nPROFIT BEFORE TAXATION RS. IN MILLION 4,250.10\nEPS = 18.42\nDIVIDEND = 250%(F)\nANNUAL GENERAL MEETING WILL BE HELD ON 21/10\nBOOK CLOSURE FROM 15/10\nBOOK CLOSURE TO 21/10"},
        {"company": "Demo Bank PLC", "ticker": "HBL", "published": days_ago(1), "source_url": _KSE_BASE,
         "title": "DEMO — UNAUDITED QUARTERLY ACCOUNTS",
         "body": "DEMO RECORD — SIMULATED CONTENT\nUNAUDITED QUARTERLY ACCOUNTS FOR THE PERIOD ENDED 30/09\nPROFIT AFTER TAXATION RS. IN MILLION 9,800.00\nEPS = 7.55\nNO DIVIDEND"},
        {"company": "Demo Fertilizers Ltd", "ticker": "EFERT", "published": days_ago(1), "source_url": _KSE_BASE,
         "title": "DEMO — CASH DIVIDEND ANNOUNCEMENT",
         "body": "DEMO RECORD — SIMULATED CONTENT\nCASH DIVIDEND\nTHE BOARD HAS DECLARED AN INTERIM CASH DIVIDEND OF RS. 8.00 PER SHARE i.e. 80%"},
        {"company": "Demo Cement Company", "ticker": "CHCC", "published": days_ago(2), "source_url": _KSE_BASE,
         "title": "DEMO — NOTICE OF ANNUAL GENERAL MEETING",
         "body": "DEMO RECORD — SIMULATED CONTENT\nNOTICE OF ANNUAL GENERAL MEETING\nANNUAL GENERAL MEETING WILL BE HELD ON 27/10/2026 AT THE REGISTERED OFFICE"},
        {"company": "Demo Cement Company", "ticker": "LUCK", "published": days_ago(2), "source_url": _KSE_BASE,
         "title": "DEMO — ISSUE OF BONUS SHARES",
         "body": "DEMO RECORD — SIMULATED CONTENT\nISSUE OF BONUS SHARES\nTHE BOARD HAS RECOMMENDED ISSUE OF 20% BONUS SHARES"},
        {"company": "Demo E&P Corporation", "ticker": "OGDC", "published": days_ago(2), "source_url": _KSE_BASE,
         "title": "DEMO — INSIDER DEALING PURCHASE OF SHARES",
         "body": "DEMO RECORD — SIMULATED CONTENT\nINSIDER DEALING\nMR. DEMO EXECUTIVE PURCHASED 50,000 SHARES @ RS. 212.50"},
        {"company": "Demo Refinery Ltd", "ticker": "PRL", "published": days_ago(3), "source_url": _KSE_BASE,
         "title": "DEMO — INSIDER DEALING SALE OF SHARES",
         "body": "DEMO RECORD — SIMULATED CONTENT\nINSIDER DEALING\nMRS. DEMO DIRECTOR SOLD 25,000 SHARES @ RS. 24.10"},
        {"company": "Demo Power Company", "ticker": "HUBC", "published": days_ago(3), "source_url": _KSE_BASE,
         "title": "DEMO — ISSUE OF RIGHTS SHARES",
         "body": "DEMO RECORD — SIMULATED CONTENT\nISSUE OF RIGHTS SHARES\nRIGHT SUBSCRIPTION OF 25% @ RS. 95.00 PER SHARE"},
        {"company": "Demo Technology Systems", "ticker": "SYS", "published": days_ago(4), "source_url": _KSE_BASE,
         "title": "DEMO — CONTRACT AWARD",
         "body": "DEMO RECORD — SIMULATED CONTENT\nCONTRACT AWARD\nTHE COMPANY HAS BEEN AWARDED A CONTRACT WORTH RS. 1.2 BILLION"},
        {"company": "Demo Chemical Industries", "ticker": "ICI", "published": days_ago(5), "source_url": _KSE_BASE,
         "title": "DEMO — APPOINTMENT OF CHIEF FINANCIAL OFFICER",
         "body": "DEMO RECORD — SIMULATED CONTENT\nAPPOINTMENT OF CFO\nMR. DEMO PERSON HAS BEEN APPOINTED AS CHIEF FINANCIAL OFFICER EFFECTIVE IMMEDIATELY"},
        {"company": "Demo Gas Utility", "ticker": "SNGP", "published": days_ago(5), "source_url": _KSE_BASE,
         "title": "DEMO — PROFIT WARNING",
         "body": "DEMO RECORD — SIMULATED CONTENT\nPROFIT WARNING\nTHE COMPANY EXPECTS A LOSS FOR THE CURRENT QUARTER DUE TO GAS CURTAILMENT"},
        {"company": "Demo Textile Mills", "ticker": "NML", "published": days_ago(6), "source_url": _KSE_BASE,
         "title": "DEMO — EXTRAORDINARY GENERAL MEETING",
         "body": "DEMO RECORD — SIMULATED CONTENT\nEXTRAORDINARY GENERAL MEETING (EOGM) WILL BE HELD ON 12/11\nTO APPROVE SCHEME OF ARRANGEMENT"},
        {"company": "Demo Petroleum Ltd", "ticker": "PPL", "published": days_ago(7), "source_url": _KSE_BASE,
         "title": "DEMO — ACQUISITION OF EXPLORATION BLOCK",
         "body": "DEMO RECORD — SIMULATED CONTENT\nACQUISITION\nTHE COMPANY SIGNED AN AGREEMENT TO ACQUIRE WORKING INTEREST IN AN EXPLORATION BLOCK"},
        {"company": "Demo Telecom Services", "ticker": "TRG", "published": days_ago(8), "source_url": _KSE_BASE,
         "title": "DEMO — BOARD MEETING AGENDA",
         "body": "DEMO RECORD — SIMULATED CONTENT\nBOARD MEETING\nBOARD OF DIRECTORS MEETING SCHEDULED TO REVIEW QUARTERLY ACCOUNTS"},
        {"company": "Demo Insurance Company", "ticker": "TPL", "published": days_ago(9), "source_url": _KSE_BASE,
         "title": "DEMO — REGULATORY NOTICE FROM SECP",
         "body": "DEMO RECORD — SIMULATED CONTENT\nREGULATORY NOTICE\nSECP CIRCULAR RECEIVED REGARDING COMPLIANCE REPORTING"},
        {"company": "Demo Sugar Mills", "ticker": "NCL", "published": days_ago(10), "source_url": _KSE_BASE,
         "title": "DEMO — CORPORATE ACTION: SHARE REGISTER CLOSURE",
         "body": "DEMO RECORD — SIMULATED CONTENT\nSHARE REGISTER CLOSURE\nBOOK CLOSURE FROM 05/11\nBOOK CLOSURE TO 08/11"},
    ]


def build_simulated_announcements() -> list[dict]:
    """Wrap demo records in the same shape as live records (analysis included,
    same labeling rules). Timestamps tick with the PKT clock, content stable."""
    records: list[dict] = []
    for r in _sim_records():
        analysis = summarize_announcement(r["body"])
        records.append({
            "id": _ann_id(r["ticker"] or "", r["title"], str(r["published"])),
            "company": r["company"], "ticker": r["ticker"], "ticker_confident": bool(r["ticker"]),
            "published": r["published"].isoformat(), "title": r["title"], "body": r["body"],
            "event": analysis["event"], "sentiment": analysis["sentiment"],
            "sentiment_meta": analysis["sentiment_meta"], "highlights": analysis["highlights"],
            "structured": analysis["structured"], "analysis_engine": analysis["engine"],
            "source": "simulated", "source_status": "SIMULATED",
            "source_url": r["source_url"], "pdf_url": None, "image_url": None,
        })
    return records


# ---------------------------------------------------------------------------
# Feed assembly, filtering, pagination, caching
# ---------------------------------------------------------------------------

def _ann_id(ticker: str, title: str, day: str) -> str:
    h = hashlib.sha1(f"{ticker}|{title}|{day}".encode("utf-8")).hexdigest()[:12]
    return f"ann-{h}"


def _assembled(records: list[dict], source: str, source_status: str) -> list[dict]:
    """Attach analysis + identity to raw parsed records."""
    out: list[dict] = []
    seen: set[str] = set()
    for r in records:
        ticker_norm = None
        if r.get("ticker"):
            try:
                ticker_norm = validate_ticker(r["ticker"])
            except Exception:
                ticker_norm = r["ticker"].upper()
        analysis = summarize_announcement(r["body"])
        day = r["published"].isoformat() if r.get("published") else "unknown"
        ann_id = _ann_id(ticker_norm or r["company"], r["title"], day)
        if ann_id in seen:
            continue
        seen.add(ann_id)
        out.append({
            "id": ann_id,
            "company": r["company"],
            "ticker": ticker_norm,
            "ticker_confident": bool(ticker_norm and re.fullmatch(r"[A-Z]{2,6}", ticker_norm)),
            "published": day,
            "title": r["title"],
            "body": r["body"],
            "event": analysis["event"],
            "sentiment": analysis["sentiment"],
            "sentiment_meta": analysis["sentiment_meta"],
            "highlights": analysis["highlights"],
            "structured": analysis["structured"],
            "analysis_engine": analysis["engine"],
            "source": source,
            "source_status": source_status,
            "source_url": r["source_url"],
            "pdf_url": None,   # official DPS attachments arrive with the DPS swap-in
            "image_url": None,
        })
    return out


class AnnouncementFiltersModel:
    """Filter/query model shared by the API route and the service."""

    def __init__(
        self,
        source: AnnSource = "company",
        event: Optional[str] = None,
        sentiment: Optional[str] = None,
        ticker: Optional[str] = None,
        company: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ):
        if source not in ("company", "simulated"):
            raise ValueError("source must be 'company' (real) or 'simulated' (demo)")
        if event and event != "ALL" and event not in ANN_EVENTS:
            raise ValueError(f"unknown event category: {event}")
        if sentiment and sentiment != "ALL" and sentiment not in ANN_SENTIMENTS:
            raise ValueError(f"unknown sentiment: {sentiment}")
        if page < 1:
            raise ValueError("page must be >= 1")
        self.source: AnnSource = source
        self.event = None if (not event or event == "ALL") else event
        self.sentiment = None if (not sentiment or sentiment == "ALL") else sentiment
        self.ticker = ticker.upper() if ticker else None
        self.company = company if company and company != "ALL" else None
        self.search = (search or "").strip() or None
        self.date_from = date_from
        self.date_to = date_to
        self.page = max(1, int(page))
        self.page_size = max(1, min(int(page_size), 50))


def apply_filters(items: list[dict], f: AnnouncementFiltersModel) -> list[dict]:
    """Filter in one pass — company/ticker/event/sentiment/date/search."""
    out: list[dict] = []
    q = f.search.lower() if f.search else None
    df = date.fromisoformat(f.date_from) if f.date_from else None
    dt = date.fromisoformat(f.date_to) if f.date_to else None
    for a in items:
        if f.ticker and (a.get("ticker") or "") != f.ticker:
            continue
        # Company filter is a case-insensitive substring match so the UI can
        # offer a usable "filter by company" box (ticker stays exact).
        if f.company and f.company.lower() not in (a.get("company") or "").lower():
            continue
        if f.event and a["event"] != f.event:
            continue
        if f.sentiment and a["sentiment"] != f.sentiment:
            continue
        if df or dt:
            try:
                d = date.fromisoformat(a["published"])
            except (KeyError, ValueError):
                continue
            if df and d < df:
                continue
            if dt and d > dt:
                continue
        if q:
            hay = " ".join([a.get("company") or "", a.get("ticker") or "", a.get("title") or "",
                            a["event"], a["sentiment"], a.get("body") or ""]).lower()
            if q not in hay:
                continue
        out.append(a)
    return out


def _paginate(items: list[dict], f: AnnouncementFiltersModel) -> dict:
    total = len(items)
    total_pages = max(1, -(-total // f.page_size))
    page = min(f.page, total_pages)
    start = (page - 1) * f.page_size
    page_items = items[start:start + f.page_size]
    return {
        "items": page_items,
        "page": page,
        "page_size": f.page_size,
        "total": total,
        "total_pages": total_pages,
        "has_more": page < total_pages,
        "next_page": page + 1 if page < total_pages else None,
        "prev_page": page - 1 if page > 1 else None,
    }


_CACHE: dict[str, dict] = {}
_CACHE_TTL_SECONDS = 300.0
_CACHE_LOCK = asyncio.Lock()


async def get_announcements_feed(f: AnnouncementFiltersModel) -> dict:
    """UI-ready feed. Live source with TTL cache + last-good fallback;
    'simulated' source serves the labeled demo dataset."""
    if f.source == "simulated":
        items = build_simulated_announcements()
        filtered = apply_filters(items, f)
        return {
            "source": "simulated",
            "source_status": "SIMULATED",
            "mode": "demo",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "ai_disclaimer": AI_DISCLAIMER,
            "source_disclaimer": "Demo dataset — synthetic records for UI development; not real filings.",
            **_paginate(filtered, f),
        }

    async with _CACHE_LOCK:
        entry = _CACHE.get("company")
        fresh = entry and (time.time() - entry["ts"]) < _CACHE_TTL_SECONDS
        if not fresh:
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    html = await _fetch_announcements_html(client)
                records = _parse_announcements_html(html)
                if not records:
                    raise RuntimeError("mirror returned zero parseable announcements")
                status = "LIVE"
            except Exception as exc:
                logger.warning("PSX announcements mirror fetch failed: %s", exc)
                status = "UNAVAILABLE"
                records = None
            if records is not None:
                _CACHE["company"] = {"ts": time.time(), "items": _assembled(records, "company", status)}
                entry = _CACHE["company"]
            elif entry:
                entry = dict(entry, status_note="stale cache served; upstream unreachable")
            else:
                return {
                    "source": "company", "source_status": "UNAVAILABLE", "mode": "live",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "items": [], "page": 1, "page_size": f.page_size, "total": 0, "total_pages": 1,
                    "has_more": False, "next_page": None, "prev_page": None,
                    "ai_disclaimer": AI_DISCLAIMER,
                    "source_disclaimer": SOURCE_DISCLAIMER,
                    "error": "PSX announcements mirror unreachable right now — no data is fabricated to fill the gap. Retry shortly.",
                }

    items = (entry or {}).get("items") or []
    filtered = apply_filters(items, f)
    return {
        "source": "company",
        "source_status": entry.get("status_note") and "STALE" or (items[0]["source_status"] if items else "LIVE"),
        "mode": "live",
        "fetched_at": datetime.fromtimestamp(entry["ts"], tz=timezone.utc).isoformat() if entry else None,
        "ai_disclaimer": AI_DISCLAIMER,
        "source_disclaimer": entry.get("status_note") and
            "Served from last-good cache — upstream mirror temporarily unreachable." or SOURCE_DISCLAIMER,
        **_paginate(filtered, f),
    }
