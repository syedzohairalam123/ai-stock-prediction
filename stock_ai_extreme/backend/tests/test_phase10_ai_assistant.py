"""
Phase 10 — AI Financial Assistant tests.

Covers the assistant's deterministic surface — everything that must be right
regardless of which model provider is configured:

  * prompt construction, including regressions for the two KeyErrors that made
    every market and portfolio prompt fail to build (``change_pct`` and
    ``value`` were read from context keys the builder never produced);
  * citation extraction (attributable, de-duplicated, http(s)-only URLs);
  * provider error classification and its HTTP mapping;
  * the PSE session window read on the PKT clock (it previously compared UTC
    hours against a PKT schedule, reporting the market open five hours early);
  * intent routing into the agent architecture;
  * both answer paths end-to-end with a stubbed provider: happy path, provider
    failure, empty answer, and a client Stop mid-answer.

No network calls: the provider, the conversation service and the database
session are all stubbed, so these tests are hermetic.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone

import pytest

from app.ai.citations import extract_citations, summarise_citations
from app.ai.context_builder import _market_status
from app.ai.errors import classify_provider_error, http_status_for, public_error_message
from app.ai.prompt_builder import PromptBuilder


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

PKT = timezone(offset=__import__("datetime").timedelta(hours=5))


@pytest.fixture()
def prompts() -> PromptBuilder:
    return PromptBuilder()


def _market_context() -> dict:
    return {
        "page_type": "market_overview",
        "route": "/",
        "market_status": "CLOSED",
        "market_context": {
            "market_status": "CLOSED",
            "indices": {
                "KSE100": {"last": 78000.5, "change_percent": 1.234, "last_date": "2026-09-16"},
                "KSE30": {"last": None, "change_percent": None, "status": "UNAVAILABLE"},
            },
        },
        "portfolio_context": {
            "positions_count": 2,
            "total_cost_basis": 100000.0,
            "total_value": 110000.0,
            "total_pnl": 10000.0,
            "total_pnl_pct": 10.0,
            "holdings": [
                {
                    "symbol": "OGDC",
                    "shares": 100,
                    "avg_cost": 95.0,
                    "market_value": 9800.0,
                    "pnl": 300.0,
                    "pnl_pct": 3.157,
                    "note": None,
                },
                {
                    "symbol": "PPL",
                    "shares": 50,
                    "avg_cost": 120.0,
                    "market_value": None,
                    "pnl": None,
                    "pnl_pct": None,
                    "note": "core",
                },
            ],
        },
    }


def _stock_context() -> dict:
    return {
        "symbol": "OGDC",
        "stock_context": {
            "symbol": "OGDC",
            "price": 95.5,
            "previous_close": 97.8,
            "change_percent": -2.35,
            "last_date": "2026-09-16",
            "market_status": "CLOSED",
            "recent_news": [
                {
                    "title": "OGDC announces gas discovery",
                    "publisher": "Business Recorder",
                    "published_at": "2026-09-16T10:00:00",
                    "url": "https://example.test/ogdc",
                    "sentiment": "POSITIVE",
                }
            ],
            "recent_announcements": [
                {
                    "title": "Board meeting scheduled",
                    "date": "2026-09-15",
                    "type": "filing",
                    "company": "OGDC",
                    "url": "javascript:alert(1)",
                }
            ],
            "sentiment": {
                "label": "POSITIVE",
                "score": 0.4,
                "confidence": 0.4,
                "source": "db_news_articles",
                "article_count": 3,
            },
        },
        "portfolio_context": {"positions_count": 2, "total_cost_basis": 100000.0},
    }


# ---------------------------------------------------------------------------
# prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    def test_system_message_carries_labels_and_sources_rule(self, prompts):
        messages = prompts.build_messages("Explain the market", _market_context())
        system = messages[0]["content"]
        assert "[FACT]" in system
        assert "[INTERPRETATION]" in system
        assert "Sources:" in system
        # the system prompt itself must never be forwarded to the client
        assert messages[0]["role"] == "system"

    def test_market_context_renders_without_key_errors(self, prompts):
        """Regression: prompts used ``change_pct``, which the builder never emits."""
        user = prompts.build_messages("What is driving the market?", _market_context())[-1]["content"]
        assert "KSE100: 78000.5 (+1.23%)" in user
        assert "KSE30: UNAVAILABLE" in user
        assert "Exchange session window: CLOSED" in user

    def test_portfolio_renders_without_key_errors(self, prompts):
        """Regression: holdings were read via ``h['value']`` (they carry ``market_value``)."""
        user = prompts.build_messages("Analyse my portfolio", _market_context())[-1]["content"]
        assert "PKR 100,000.00" in user
        assert "PKR 10,000.00 (+10.00%)" in user
        assert "OGDC: 100 shares @ PKR 95.00 = PKR 9,800.00" in user
        # an unpriced holding must be labelled, never silently dropped or faked
        assert "current price unavailable" in user
        assert "note: core" in user

    def test_portfolio_is_omitted_when_not_authorized(self, prompts):
        context = {"page_type": "portfolio", "route": "/portfolio"}
        user = prompts.build_messages("How am I doing?", context)[-1]["content"]
        assert "PORTFOLIO" not in user
        assert "No additional context data available." in user

    def test_comparison_marks_unavailable_symbol(self, prompts):
        context = {
            "comparison_type": "stock_comparison",
            "symbols": ["HBL", "MEBL"],
            "data": {
                "HBL": {
                    "symbol": "HBL",
                    "price": {"price": 150.2, "change_percent": 0.8},
                    "sentiment": {"label": "POSITIVE"},
                    "recent_news": [{"title": "HBL results beat expectations"}],
                },
                "MEBL": {"symbol": "MEBL", "error": "no data"},
            },
        }
        user = prompts.build_messages("Compare HBL and MEBL", context)[-1]["content"]
        assert "HBL: price 150.2 (+0.80%)" in user
        assert "MEBL: DATA UNAVAILABLE" in user
        assert "do not compare this symbol" in user

    def test_missing_price_is_reported_not_invented(self, prompts):
        context = {
            "symbol": "XYZ",
            "stock_context": {"symbol": "XYZ", "recent_news": [], "sentiment": {}},
        }
        user = prompts.build_messages("What is XYZ trading at?", context)[-1]["content"]
        assert "QUOTE: UNAVAILABLE from the data provider" in user

    @pytest.mark.parametrize(
        "page_type",
        [
            "stock_detail",
            "index_detail",
            "market_overview",
            "portfolio",
            "watchlist",
            "news",
            "announcements",
            "sentiment",
            "screener",
            "comparison",
            "forex_commodities",
            "other",
        ],
    )
    def test_every_page_type_has_prompts(self, prompts, page_type):
        suggestions = prompts.build_suggested_prompts({"page_type": page_type, "symbol": "OGDC"})
        assert suggestions, f"{page_type} produced no suggestions"
        assert all(isinstance(item, str) and item.strip() for item in suggestions)


# ---------------------------------------------------------------------------
# citations (spec T)
# ---------------------------------------------------------------------------


class TestCitations:
    def test_extracts_attributable_sources(self):
        citations = extract_citations(_stock_context())
        kinds = sorted({citation["kind"] for citation in citations})
        assert kinds == ["announcement", "news", "portfolio", "quote", "sentiment"]

        news = next(c for c in citations if c["kind"] == "news")
        assert news["title"] == "OGDC announces gas discovery"
        assert news["source"] == "Business Recorder"
        assert news["url"] == "https://example.test/ogdc"

    def test_non_http_urls_are_dropped(self):
        citations = extract_citations(_stock_context())
        announcement = next(c for c in citations if c["kind"] == "announcement")
        assert announcement["url"] is None

    def test_no_context_means_no_citations(self):
        assert extract_citations(None) == []
        assert extract_citations({}) == []

    def test_unavailable_data_produces_no_citation(self):
        citations = extract_citations({"stock_context": {"symbol": "XYZ", "price": None}})
        assert citations == []

    def test_duplicates_collapse_and_summary_is_log_safe(self):
        context = {
            "stock_context": {
                "symbol": "OGDC",
                "price": 95.5,
                "recent_news": [
                    {"title": "Same headline", "publisher": "A"},
                    {"title": "same HEADLINE", "publisher": "B"},
                ],
            }
        }
        citations = extract_citations(context)
        assert len([c for c in citations if c["kind"] == "news"]) == 1
        assert summarise_citations(citations) == "news:1, quote:1"
        assert summarise_citations([]) == "none"


# ---------------------------------------------------------------------------
# error classification (spec V)
# ---------------------------------------------------------------------------


class TestErrorClassification:
    @pytest.mark.parametrize(
        "error,expected",
        [
            (ValueError("OpenAI API key not configured"), "unavailable"),
            (RuntimeError("429 rate limit exceeded"), "rate_limit"),
            (RuntimeError("Too many requests"), "rate_limit"),
            (TimeoutError("request timed out"), "timeout"),
            (RuntimeError("unexpected provider boom"), "backend"),
        ],
    )
    def test_categories(self, error, expected):
        assert classify_provider_error(error) == expected

    def test_http_status_mapping(self):
        assert http_status_for("unavailable") == 503
        assert http_status_for("rate_limit") == 429
        assert http_status_for("timeout") == 504
        assert http_status_for("backend") == 502

    def test_messages_never_leak_provider_internals(self):
        message = public_error_message("backend", RuntimeError("/v1/chat/completions 500 sk-live-abc"))
        assert "sk-live-abc" not in message
        assert "/v1/chat/completions" not in message


# ---------------------------------------------------------------------------
# market session window
# ---------------------------------------------------------------------------


class TestMarketSessionWindow:
    @pytest.mark.parametrize(
        "stamp,expected",
        [
            ("2026-09-16T11:00:00+05:00", "OPEN"),    # Wednesday mid-session
            ("2026-09-16T09:29:00+05:00", "CLOSED"),  # just before the bell
            ("2026-09-16T15:30:00+05:00", "CLOSED"),  # just after the close
            ("2026-09-16T02:00:00+05:00", "CLOSED"),  # 02:00 PKT — was reported OPEN before
            ("2026-09-19T11:00:00+05:00", "WEEKEND"),  # Saturday
        ],
    )
    def test_session_window_is_read_on_the_pkt_clock(self, stamp, expected):
        assert _market_status(datetime.fromisoformat(stamp)) == expected

    def test_utc_instant_is_converted(self):
        # 07:00 UTC == 12:00 PKT on a Wednesday -> inside the session
        assert _market_status(datetime(2026, 9, 16, 7, 0, tzinfo=timezone.utc)) == "OPEN"


# ---------------------------------------------------------------------------
# intent routing (spec P)
# ---------------------------------------------------------------------------


class TestIntentRouting:
    @pytest.mark.parametrize(
        "question,context,expected",
        [
            ("Compare HBL and MEBL", {}, "comparison"),
            ("HBL vs MEBL — which is stronger?", {}, "comparison"),
            ("What affected OGDC today?", {"symbol": "OGDC", "entity_type": "stock"}, "stock"),
            ("How did KSE100 close?", {"symbol": "KSE100", "entity_type": "index"}, "market"),
            ("What moved today?", {"page_type": "portfolio"}, "portfolio"),
            ("Summarise the latest announcements", {}, "announcement"),
            ("How is sentiment looking?", {}, "sentiment"),
            ("Which holding hurts my P&L most?", {}, "portfolio"),
            ("Any news on banks?", {}, "news"),
            ("What is driving the market?", {}, "market"),
        ],
    )
    def test_detect_intent(self, question, context, expected):
        from app.ai.agents import AgentRouter

        # detect_intent is pure: it never touches the database.
        assert AgentRouter.detect_intent(None, question, context) == expected


# ---------------------------------------------------------------------------
# endpoint behaviour with a stubbed provider
# ---------------------------------------------------------------------------

CITATIONS = [
    {
        "kind": "news",
        "title": "OGDC announces gas discovery",
        "source": "Business Recorder",
        "published_at": "2026-09-16",
        "url": "https://example.test/ogdc",
        "symbol": "OGDC",
        "detail": None,
    }
]


class _FakeConversation:
    def __init__(self, conversation_id: int):
        self.id = conversation_id


class _FakeMessage:
    _next_id = 100

    def __init__(self, **kwargs):
        _FakeMessage._next_id += 1
        self.id = _FakeMessage._next_id
        for key, value in kwargs.items():
            setattr(self, key, value)


class _Saved:
    """Records what the endpoints persisted."""

    def __init__(self):
        self.messages: list[dict] = []
        self.finished: list[tuple] = []


@pytest.fixture()
def ai_controller(monkeypatch):
    """Import the controller with every collaborator stubbed."""
    from app import ai_controller as controller

    saved = _Saved()

    class FakeConversationService:
        def __init__(self, db):
            pass

        async def get_conversation(self, conversation_id):
            return _FakeConversation(conversation_id)

        async def create_conversation(self, **kwargs):
            return _FakeConversation(7)

        async def get_recent_messages_for_context(self, conversation_id):
            return []

        async def auto_generate_title(self, *args, **kwargs):
            return True

        async def add_message(self, **kwargs):
            saved.messages.append(kwargs)
            return _FakeMessage(**kwargs)

    class FakeContextBuilder:
        def __init__(self, db):
            pass

        async def build_context(self, **kwargs):
            return {
                "route": kwargs.get("route"),
                "symbol": kwargs.get("symbol"),
                "market_status": "OPEN",
            }

    class FakeStreamingService:
        mode = "ok"
        format_sse_event = staticmethod(controller.StreamingService.format_sse_event)

        def __init__(self, provider):
            pass

        async def stream_response(self, **kwargs):
            yield {"event": "status", "data": {"status": "thinking", "conversation_id": kwargs.get("conversation_id")}}
            yield {"event": "status", "data": {"status": "streaming", "conversation_id": kwargs.get("conversation_id")}}
            if FakeStreamingService.mode == "error":
                yield {
                    "event": "error",
                    "data": {
                        "status": "error",
                        "error": "provider down",
                        "error_type": "RuntimeError",
                        "category": "backend",
                        "request_id": "req-test",
                    },
                }
                return
            yield {"event": "chunk", "data": {"content": "Hello "}}
            if FakeStreamingService.mode == "stop":
                raise asyncio.CancelledError()
            yield {"event": "chunk", "data": {"content": "world"}}
            yield {
                "event": "complete",
                "data": {
                    "status": "complete",
                    "full_content": "Hello world",
                    "model": "fake-model",
                    "processing_time_ms": 12,
                    "citations": kwargs.get("citations"),
                    "conversation_id": kwargs.get("conversation_id"),
                    "stopped": False,
                },
            }

        async def get_non_streaming_response(self, **kwargs):
            if FakeStreamingService.mode == "error":
                raise RuntimeError("429 rate limit exceeded")
            if FakeStreamingService.mode == "empty":
                return {"content": "   ", "model": "fake-model", "usage": {}, "processing_time_ms": 5}
            return {"content": "Answer", "model": "fake-model", "usage": {"total_tokens": 5}, "processing_time_ms": 5}

    class FakeProvider:
        def get_model_name(self):
            return "fake-model"

    async def fake_task_start(db, question, context, conversation_id, request_id):
        return 11, "market", datetime.now(timezone.utc)

    async def fake_task_finish(db, task_id, status, started, request_id, error=None, result=None):
        saved.finished.append((task_id, status, error, result))

    @contextlib.asynccontextmanager
    async def fake_session_scope():
        yield object()

    monkeypatch.setattr(controller, "ConversationService", FakeConversationService)
    monkeypatch.setattr(controller, "ContextBuilder", FakeContextBuilder)
    monkeypatch.setattr(controller, "StreamingService", FakeStreamingService)
    monkeypatch.setattr(controller, "extract_citations", lambda context: CITATIONS)
    monkeypatch.setattr(controller, "get_ai_provider", lambda: FakeProvider())
    monkeypatch.setattr(controller, "_record_task_start", fake_task_start)
    monkeypatch.setattr(controller, "_record_task_finish", fake_task_finish)
    monkeypatch.setattr(controller, "async_session_scope", fake_session_scope)

    controller.fake_saved = saved
    controller.fake_streaming = FakeStreamingService
    return controller


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event, data = None, None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        events.append((event, data))
    return events


def _drain_stream(controller):
    response = asyncio.run(
        controller.stream_chat(
            controller.ChatRequest(
                question="What moved OGDC?",
                context={"route": "/stock/OGDC", "symbol": "OGDC"},
            )
        )
    )

    async def collect():
        body = ""
        async for chunk in response.body_iterator:
            body += chunk
        return body

    return _parse_sse(asyncio.run(collect()))


class TestStreamEndpoint:
    def test_happy_path_persists_then_completes(self, ai_controller):
        ai_controller.fake_streaming.mode = "ok"
        events = _drain_stream(ai_controller)

        assert [event for event, _ in events] == [
            "status",
            "status",
            "chunk",
            "chunk",
            "complete",
        ]

        complete = events[-1][1]
        assert complete["full_content"] == "Hello world"
        assert complete["conversation_id"] == 7
        assert complete["message_id"], "the persisted row id must reach the client"
        assert complete["citations"] == CITATIONS

        saved = ai_controller.fake_saved
        assert [message["role"] for message in saved.messages] == ["user", "assistant"]
        assert saved.messages[1]["citations"] == CITATIONS
        assert saved.finished[-1][1] == "COMPLETED"

    def test_provider_error_keeps_no_assistant_row(self, ai_controller):
        ai_controller.fake_streaming.mode = "error"
        events = _drain_stream(ai_controller)

        assert events[-1][0] == "error"
        assert events[-1][1]["category"] == "backend"

        saved = ai_controller.fake_saved
        assert [message["role"] for message in saved.messages] == ["user"]
        assert saved.finished[-1][1] == "FAILED"

    def test_stop_keeps_the_partial_answer(self, ai_controller):
        """A client Stop must never discard text the reader already saw."""
        ai_controller.fake_streaming.mode = "stop"

        with pytest.raises(asyncio.CancelledError):
            _drain_stream(ai_controller)

        saved = ai_controller.fake_saved
        assert [message["role"] for message in saved.messages] == ["user", "assistant"]
        assert saved.messages[1]["content"] == "Hello"


class TestSseContract:
    """The event vocabulary the browser switches on (spec L).

    These tests keep the *real* StreamingService and PromptBuilder in the path
    and stub only the provider, so a change to the event envelope cannot slip
    past the UI again. An earlier revision emitted ``"status": "status"`` on
    the lifecycle events, which left the composer stuck on "thinking".
    """

    @pytest.fixture()
    def live_stream(self, monkeypatch):
        from app import ai_controller as controller
        from app.ai.providers import AIProvider

        saved = _Saved()

        class StreamingProvider(AIProvider):
            def get_model_name(self):
                return "fake-stream-model"

            async def chat_completion(self, messages, temperature=0.7, max_tokens=None):
                return {"content": "whole answer", "model": self.get_model_name(), "usage": {}, "finish_reason": "stop"}

            async def chat_completion_stream(self, messages, temperature=0.7, max_tokens=None):
                for piece in ("OGDC ", "closed ", "lower."):
                    yield piece

        class FakeConversationService:
            def __init__(self, db):
                pass

            async def get_conversation(self, conversation_id):
                return _FakeConversation(conversation_id)

            async def create_conversation(self, **kwargs):
                return _FakeConversation(3)

            async def get_recent_messages_for_context(self, conversation_id):
                return []

            async def auto_generate_title(self, *args, **kwargs):
                return True

            async def add_message(self, **kwargs):
                saved.messages.append(kwargs)
                return _FakeMessage(**kwargs)

        class FakeContextBuilder:
            def __init__(self, db):
                pass

            async def build_context(self, **kwargs):
                return {"route": "/stock/OGDC", "symbol": "OGDC", "market_status": "OPEN"}

        async def fake_task_start(db, question, context, conversation_id, request_id):
            return None, "stock", datetime.now(timezone.utc)

        async def fake_task_finish(*args, **kwargs):
            return None

        @contextlib.asynccontextmanager
        async def fake_session_scope():
            yield object()

        monkeypatch.setattr(controller, "ConversationService", FakeConversationService)
        monkeypatch.setattr(controller, "ContextBuilder", FakeContextBuilder)
        monkeypatch.setattr(controller, "get_ai_provider", lambda: StreamingProvider())
        monkeypatch.setattr(controller, "_record_task_start", fake_task_start)
        monkeypatch.setattr(controller, "_record_task_finish", fake_task_finish)
        monkeypatch.setattr(controller, "async_session_scope", fake_session_scope)

        return controller, saved

    def test_lifecycle_statuses_are_semantic(self, live_stream):
        controller, saved = live_stream
        events = _drain_stream(controller)

        statuses = [data["status"] for event, data in events if event == "status"]
        assert statuses == ["thinking", "streaming"], statuses

        chunks = [data["content"] for event, data in events if event == "chunk"]
        assert chunks == ["OGDC ", "closed ", "lower."]

        complete = events[-1]
        assert complete[0] == "complete"
        assert complete[1]["status"] == "complete"
        assert complete[1]["full_content"] == "OGDC closed lower."
        assert complete[1]["message_id"] and complete[1]["conversation_id"] == 3

        # the full answer — not the last chunk — is what gets persisted
        assert saved.messages[-1]["content"] == "OGDC closed lower."


class TestChatEndpoint:
    def test_happy_path(self, ai_controller):
        ai_controller.fake_streaming.mode = "ok"

        class _Response:
            headers: dict = {}

        response = asyncio.run(
            ai_controller.chat(
                ai_controller.ChatRequest(question="Hi", context={"route": "/"}),
                _Response(),
            )
        )

        assert response.content == "Answer"
        assert response.model == "fake-model"
        assert [citation.model_dump() for citation in response.citations] == CITATIONS
        assert ai_controller.fake_saved.finished[-1][1] == "COMPLETED"

    def test_rate_limit_maps_to_429(self, ai_controller):
        from fastapi import HTTPException

        ai_controller.fake_streaming.mode = "error"

        class _Response:
            headers: dict = {}

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(
                ai_controller.chat(
                    ai_controller.ChatRequest(question="Hi", context={"route": "/"}),
                    _Response(),
                )
            )

        assert excinfo.value.status_code == 429
        assert ai_controller.fake_saved.finished[-1][1] == "FAILED"

    def test_empty_answer_is_reported(self, ai_controller):
        from fastapi import HTTPException

        ai_controller.fake_streaming.mode = "empty"

        class _Response:
            headers: dict = {}

        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(
                ai_controller.chat(
                    ai_controller.ChatRequest(question="Hi", context={"route": "/"}),
                    _Response(),
                )
            )

        assert excinfo.value.status_code == 502
