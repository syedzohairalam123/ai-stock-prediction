"""
AI Controller (Phase 10)

REST + SSE endpoints for the AI Financial Assistant.

Endpoints
    POST   /api/ai/chat                          one-shot answer
    POST   /api/ai/stream                        streamed answer (SSE)
    GET    /api/ai/conversations                 list conversations
    POST   /api/ai/conversations                 create a conversation
    GET    /api/ai/conversations/{id}            read one conversation
    PUT    /api/ai/conversations/{id}            rename a conversation
    DELETE /api/ai/conversations/{id}            delete a conversation
    GET    /api/ai/conversations/{id}/messages   read a conversation's messages
    POST   /api/ai/suggested-prompts             context-aware prompt ideas
    GET    /api/ai/agent-tasks                   agent task history
    GET    /api/ai/status                        provider status

Design notes
    * API keys never leave the backend: the provider is constructed here only.
    * Every request gets a request id that appears in the structured logs, on
      the response header, and in any error payload (spec X).
    * Each question is classified by intent and recorded in the agent-task
      history (spec O/P) — bookkeeping is best-effort and can never fail a chat.
    * Answers carry a citations list built from the context that was actually
      sent, so sources are attributable and never invented (spec T).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .ai.agents import AgentRouter
from .ai.citations import extract_citations, summarise_citations
from .ai.context_builder import ContextBuilder
from .ai.conversation_service import ConversationService
from .ai.errors import classify_provider_error, http_status_for, public_error_message
from .ai.prompt_builder import PromptBuilder
from .ai.providers import get_ai_provider
from .ai.streaming_service import StreamingService
from .config import settings
from .db import async_session_scope
from .models import AgentTask

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/ai", tags=["AI Assistant"])

#: Intent → (task type, agent name) for the task history (spec O).
INTENT_TASKS: Dict[str, Tuple[str, str]] = {
    "market": ("MARKET_ANALYSIS", "MarketDataAgent"),
    "stock": ("STOCK_ANALYSIS", "StockAnalysisAgent"),
    "news": ("NEWS_SUMMARY", "NewsAgent"),
    "announcement": ("ANNOUNCEMENT_ANALYSIS", "AnnouncementAgent"),
    "sentiment": ("SENTIMENT_ANALYSIS", "SentimentAgent"),
    "portfolio": ("PORTFOLIO_ANALYSIS", "PortfolioAgent"),
    "comparison": ("STOCK_COMPARISON", "ComparisonAgent"),
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request for a chat answer."""

    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[int] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    temperature: float = Field(default=0.4, ge=0.0, le=1.0)
    stream: bool = False


class CitationModel(BaseModel):
    kind: str
    title: str
    source: Optional[str] = None
    published_at: Optional[str] = None
    url: Optional[str] = None
    symbol: Optional[str] = None
    detail: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int
    content: str
    model: str
    usage: Optional[Dict[str, Any]] = None
    processing_time_ms: int
    context_used: Dict[str, Any]
    citations: List[CitationModel] = Field(default_factory=list)


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    context_snapshot: Optional[Dict[str, Any]] = None


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class SuggestedPromptsRequest(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)


class ConversationListResponse(BaseModel):
    conversations: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Naive UTC timestamp, matching the DateTime columns and the rest of the app."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_request_id() -> str:
    return uuid4().hex[:12]


def _provider_or_503() -> Any:
    """Build the configured provider, or fail with an actionable 503."""
    try:
        return get_ai_provider()
    except Exception as error:  # missing key, unknown provider name, etc.
        logger.warning("ai_provider_unavailable", error_type=type(error).__name__)
        raise HTTPException(
            http_status_for("unavailable"),
            public_error_message("unavailable", error),
        )


def _context_kwargs(context: Dict[str, Any]) -> Dict[str, Any]:
    """Map the client context payload onto ContextBuilder arguments."""
    return {
        "route": context.get("route", "/"),
        "symbol": context.get("symbol"),
        "entity_type": context.get("entity_type"),
        "timeframe": context.get("timeframe"),
        "include_news": context.get("include_news", True),
        "include_announcements": context.get("include_announcements", True),
        "include_sentiment": context.get("include_sentiment", True),
        "include_portfolio": bool(context.get("include_portfolio", False)),
        "user_id": context.get("user_id"),
    }


async def _record_task_start(
    db: Any,
    question: str,
    context: Dict[str, Any],
    conversation_id: Optional[int],
    request_id: str,
) -> Tuple[Optional[int], str, datetime]:
    """
    Record that an agent is about to handle this request (spec O).

    Only non-sensitive routing facts are stored: the page type, the public
    symbol and the timeframe. The question text and any portfolio values stay
    out of the task log (spec X).
    """
    started = _utcnow()
    try:
        intent = AgentRouter(db).detect_intent(question, context)
        task_type, agent_name = INTENT_TASKS.get(intent, ("QUESTION_ANSWER", "AssistantRouter"))

        task = AgentTask(
            conversation_id=conversation_id,
            task_type=task_type,
            agent_name=agent_name,
            status="RUNNING",
            input_params={
                "page_type": context.get("page_type"),
                "symbol": context.get("symbol"),
                "entity_type": context.get("entity_type"),
                "timeframe": context.get("timeframe"),
                "request_id": request_id,
            },
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task.id, intent, started
    except Exception as error:  # bookkeeping must never break the answer
        logger.warning("agent_task_record_failed", request_id=request_id, error_type=type(error).__name__)
        return None, "unknown", started


async def _record_task_finish(
    db: Any,
    task_id: Optional[int],
    status: str,
    started: datetime,
    request_id: str,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    """Mark an agent task COMPLETED or FAILED. Best-effort, never raises."""
    if task_id is None:
        return
    try:
        task = await db.get(AgentTask, task_id)
        if task is None:
            return
        task.status = status
        task.completed_at = _utcnow()
        task.execution_time_ms = int((task.completed_at - started).total_seconds() * 1000)
        if error is not None:
            task.error = error[:1000]
        if result is not None:
            task.result = result
        await db.commit()
    except Exception as db_error:
        logger.warning("agent_task_finish_failed", request_id=request_id, error_type=type(db_error).__name__)


def _serialise_message(message: Any) -> Dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "context_used": message.context_used,
        "citations": message.citations or [],
        "token_usage": message.token_usage,
        "model": message.model,
        "processing_time_ms": message.processing_time_ms,
        "created_at": message.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Chat (non-streaming)
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, response: Response) -> ChatResponse:
    """Answer one question in a single response."""
    request_id = new_request_id()
    response.headers["X-Request-ID"] = request_id
    provider = _provider_or_503()

    try:
        async with async_session_scope() as db:
            conversations = ConversationService(db)
            streaming = StreamingService(provider)
            builder = ContextBuilder(db)

            if request.conversation_id:
                conversation = await conversations.get_conversation(request.conversation_id)
                if conversation is None:
                    raise HTTPException(404, "Conversation not found")
            else:
                conversation = await conversations.create_conversation(
                    context_snapshot=request.context
                )

            context = await builder.build_context(**_context_kwargs(request.context))
            citations = extract_citations(context)
            history = await conversations.get_recent_messages_for_context(conversation.id)

            await conversations.add_message(
                conversation_id=conversation.id,
                role="user",
                content=request.question,
                context_used=context,
            )
            if not history:
                await conversations.auto_generate_title(conversation.id, request.question)

            task_id, intent, started = await _record_task_start(
                db, request.question, context, conversation.id, request_id
            )

            try:
                answer = await streaming.get_non_streaming_response(
                    user_question=request.question,
                    context=context,
                    conversation_history=history,
                    temperature=request.temperature,
                )
            except Exception as error:
                category = classify_provider_error(error)
                await _record_task_finish(
                    db,
                    task_id,
                    "FAILED",
                    started,
                    request_id,
                    error=f"{category}: {type(error).__name__}",
                )
                logger.error(
                    "chat_failed",
                    request_id=request_id,
                    conversation_id=conversation.id,
                    provider=provider.__class__.__name__,
                    error_category=category,
                    success=False,
                )
                raise HTTPException(http_status_for(category), public_error_message(category, error))

            if not (answer.get("content") or "").strip():
                await _record_task_finish(db, task_id, "FAILED", started, request_id, error="empty_response")
                raise HTTPException(
                    http_status_for("empty_response"),
                    public_error_message("empty_response"),
                )

            assistant_message = await conversations.add_message(
                conversation_id=conversation.id,
                role="assistant",
                content=answer["content"],
                context_used=context,
                citations=citations,
                token_usage=answer.get("usage"),
                model=answer["model"],
                processing_time_ms=answer["processing_time_ms"],
            )

            await _record_task_finish(
                db,
                task_id,
                "COMPLETED",
                started,
                request_id,
                result={
                    "intent": intent,
                    "model": answer["model"],
                    "citations": len(citations),
                    "content_length": len(answer["content"]),
                },
            )

            logger.info(
                "chat_completed",
                request_id=request_id,
                conversation_id=conversation.id,
                provider=provider.__class__.__name__,
                model=answer["model"],
                latency_ms=answer["processing_time_ms"],
                tokens=(answer.get("usage") or {}).get("total_tokens"),
                citations=summarise_citations(citations),
                intent=intent,
                success=True,
            )

            return ChatResponse(
                conversation_id=conversation.id,
                message_id=assistant_message.id,
                content=answer["content"],
                model=answer["model"],
                usage=answer.get("usage"),
                processing_time_ms=answer["processing_time_ms"],
                context_used=context,
                citations=[CitationModel(**citation) for citation in citations],
            )

    except HTTPException:
        raise
    except Exception as error:
        logger.error("chat_endpoint_error", request_id=request_id, error_type=type(error).__name__)
        raise HTTPException(
            http_status_for("backend"),
            "The assistant could not complete that request. Retry to try again.",
        )


# ---------------------------------------------------------------------------
# Chat (streaming)
# ---------------------------------------------------------------------------


@router.post("/stream")
async def stream_chat(request: ChatRequest):
    """Stream an answer as Server-Sent Events (spec L)."""
    request_id = new_request_id()
    provider = _provider_or_503()
    streaming = StreamingService(provider)
    request_started = _utcnow()

    async def generate_stream():
        """SSE generator.

        Ordering matters: the answer row is persisted *before* the `complete`
        event goes out, so the id the client receives is the id it can later
        fetch, rename or cite. A disconnect mid-answer keeps the partial text
        that was already streamed.
        """
        task_id: Optional[int] = None
        task_started = request_started
        conversation_id: Optional[int] = request.conversation_id
        context: Dict[str, Any] = {}
        citations: List[Dict[str, Any]] = []
        full_content = ""
        prompt_built = False

        try:
            async with async_session_scope() as session:
                conversations = ConversationService(session)
                builder = ContextBuilder(session)

                if request.conversation_id:
                    conversation = await conversations.get_conversation(request.conversation_id)
                    if conversation is None:
                        yield StreamingService.format_sse_event(
                            "error",
                            {
                                "error": "That conversation no longer exists. Start a new one.",
                                "category": "backend",
                                "request_id": request_id,
                                "retryable": False,
                            },
                        )
                        return
                else:
                    conversation = await conversations.create_conversation(
                        context_snapshot=request.context
                    )

                conversation_id = conversation.id
                context = await builder.build_context(**_context_kwargs(request.context))
                citations = extract_citations(context)
                history = await conversations.get_recent_messages_for_context(conversation.id)

                await conversations.add_message(
                    conversation_id=conversation.id,
                    role="user",
                    content=request.question,
                    context_used=context,
                )
                if not history:
                    await conversations.auto_generate_title(conversation.id, request.question)

                task_id, intent, task_started = await _record_task_start(
                    session, request.question, context, conversation.id, request_id
                )
                prompt_built = True

                async for event in streaming.stream_response(
                    user_question=request.question,
                    context=context,
                    conversation_history=history,
                    temperature=request.temperature,
                    request_id=request_id,
                    conversation_id=conversation.id,
                    citations=citations,
                ):
                    event_type = event["event"]
                    data = event["data"]

                    if event_type == "chunk":
                        full_content += data.get("content", "")
                        yield StreamingService.format_sse_event("chunk", data)
                        continue

                    if event_type == "error":
                        yield StreamingService.format_sse_event("error", data)
                        await _record_task_finish(
                            session,
                            task_id,
                            "FAILED",
                            task_started,
                            request_id,
                            error=f"{data.get('category')}: {data.get('error_type')}",
                        )
                        logger.error(
                            "stream_chat_failed",
                            request_id=request_id,
                            conversation_id=conversation.id,
                            provider=provider.__class__.__name__,
                            error_category=data.get("category"),
                            success=False,
                        )
                        return

                    if event_type == "complete":
                        content = (data.get("full_content") or full_content).strip()
                        message_id: Optional[int] = None

                        if content:
                            message = await conversations.add_message(
                                conversation_id=conversation.id,
                                role="assistant",
                                content=content,
                                context_used=context,
                                citations=citations,
                                model=data.get("model") or provider.get_model_name(),
                                processing_time_ms=data.get("processing_time_ms"),
                            )
                            message_id = message.id

                        yield StreamingService.format_sse_event(
                            "complete",
                            {**data, "full_content": content, "message_id": message_id, "citations": citations},
                        )

                        await _record_task_finish(
                            session,
                            task_id,
                            "COMPLETED" if content else "FAILED",
                            task_started,
                            request_id,
                            error=None if content else "empty_response",
                            result={
                                "intent": intent,
                                "model": data.get("model"),
                                "citations": len(citations),
                                "content_length": len(content),
                                "stopped": bool(data.get("stopped")),
                            },
                        )

                        logger.info(
                            "stream_chat_completed",
                            request_id=request_id,
                            conversation_id=conversation.id,
                            provider=provider.__class__.__name__,
                            model=data.get("model"),
                            latency_ms=int((_utcnow() - request_started).total_seconds() * 1000),
                            content_length=len(content),
                            citations=summarise_citations(citations),
                            intent=intent,
                            stopped=bool(data.get("stopped")),
                            success=bool(content),
                        )
                        return

                    # status events (thinking / streaming)
                    yield StreamingService.format_sse_event(event_type, data)

        except BaseException as error:  # cancellation must not vanish silently
            if isinstance(error, GeneratorExit):
                raise

            logger.info(
                "stream_chat_interrupted",
                request_id=request_id,
                conversation_id=conversation_id,
                content_length=len(full_content),
                reason=type(error).__name__,
            )

            # Best-effort: keep the partial answer that was already on screen.
            # The streaming session is already closed at this point, so this
            # opens its own short-lived session — the answer the reader has
            # already seen must survive a Stop or a dropped connection.
            if prompt_built and conversation_id is not None and full_content.strip():
                try:
                    async with async_session_scope() as recovery_session:
                        await ConversationService(recovery_session).add_message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=full_content.strip(),
                            context_used=context or None,
                            citations=citations,
                            model=provider.get_model_name(),
                        )
                        await _record_task_finish(
                            recovery_session,
                            task_id,
                            "FAILED",
                            task_started,
                            request_id,
                            error="interrupted",
                        )
                except Exception:
                    logger.warning("stream_partial_save_failed", request_id=request_id)
            raise

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    user_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
):
    """List conversations, newest first."""
    try:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        async with async_session_scope() as db:
            service = ConversationService(db)
            conversations, total = await service.list_conversations(
                user_id=user_id,
                limit=page_size,
                offset=(page - 1) * page_size,
            )

            return ConversationListResponse(
                conversations=[
                    {
                        "id": conversation.id,
                        "title": conversation.title,
                        "context_snapshot": conversation.context_snapshot,
                        "created_at": conversation.created_at.isoformat(),
                        "updated_at": conversation.updated_at.isoformat(),
                    }
                    for conversation in conversations
                ],
                total=total,
                page=page,
                page_size=page_size,
            )
    except Exception as error:
        logger.error("list_conversations_error", error_type=type(error).__name__)
        raise HTTPException(500, "Could not load conversation history.")


@router.post("/conversations")
async def create_conversation(request: ConversationCreateRequest):
    """Create an empty conversation (the client does this on the first turn)."""
    try:
        async with async_session_scope() as db:
            conversation = await ConversationService(db).create_conversation(
                title=request.title,
                context_snapshot=request.context_snapshot,
            )
            return {
                "id": conversation.id,
                "title": conversation.title,
                "context_snapshot": conversation.context_snapshot,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
            }
    except Exception as error:
        logger.error("create_conversation_error", error_type=type(error).__name__)
        raise HTTPException(500, "Could not start a new conversation.")


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    """Read one conversation with its stats."""
    try:
        async with async_session_scope() as db:
            service = ConversationService(db)
            conversation = await service.get_conversation(conversation_id)
            if conversation is None:
                raise HTTPException(404, "Conversation not found")

            stats = await service.get_conversation_stats(conversation_id)
            return {
                "id": conversation.id,
                "title": conversation.title,
                "context_snapshot": conversation.context_snapshot,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "stats": stats,
            }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("get_conversation_error", error_type=type(error).__name__, conversation_id=conversation_id)
        raise HTTPException(500, "Could not load that conversation.")


@router.put("/conversations/{conversation_id}")
async def update_conversation(conversation_id: int, request: ConversationUpdateRequest):
    """Rename a conversation."""
    try:
        async with async_session_scope() as db:
            success = await ConversationService(db).update_conversation_title(
                conversation_id=conversation_id,
                new_title=request.title.strip(),
            )
            if not success:
                raise HTTPException(404, "Conversation not found")
            return {"success": True, "message": "Conversation renamed"}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("update_conversation_error", error_type=type(error).__name__, conversation_id=conversation_id)
        raise HTTPException(500, "Could not rename that conversation.")


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    """Delete a conversation and its messages."""
    try:
        async with async_session_scope() as db:
            success = await ConversationService(db).delete_conversation(conversation_id)
            if not success:
                raise HTTPException(404, "Conversation not found")
            return {"success": True, "message": "Conversation deleted"}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("delete_conversation_error", error_type=type(error).__name__, conversation_id=conversation_id)
        raise HTTPException(500, "Could not delete that conversation.")


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(conversation_id: int):
    """Read every message in a conversation."""
    try:
        async with async_session_scope() as db:
            messages = await ConversationService(db).get_conversation_messages(conversation_id)
            return {
                "conversation_id": conversation_id,
                "messages": [_serialise_message(message) for message in messages],
            }
    except Exception as error:
        logger.error("get_messages_error", error_type=type(error).__name__, conversation_id=conversation_id)
        raise HTTPException(500, "Could not load that conversation's messages.")


# ---------------------------------------------------------------------------
# Suggested prompts / task history / status
# ---------------------------------------------------------------------------


@router.post("/suggested-prompts")
async def get_suggested_prompts(request: SuggestedPromptsRequest):
    """Context-aware question suggestions for the current page (spec J)."""
    try:
        async with async_session_scope() as db:
            builder = ContextBuilder(db)
            route = request.context.get("route", "/")
            page_type = builder._determine_page_type(route)
            prompts = PromptBuilder().build_suggested_prompts(
                {
                    "page_type": page_type,
                    "route": route,
                    "symbol": request.context.get("symbol"),
                    "entity_type": request.context.get("entity_type"),
                    "timeframe": request.context.get("timeframe"),
                }
            )
            return {"prompts": prompts}
    except Exception as error:
        logger.error("suggested_prompts_error", error_type=type(error).__name__)
        raise HTTPException(500, "Could not prepare suggestions.")


@router.get("/agent-tasks")
async def list_agent_tasks(conversation_id: Optional[int] = None, limit: int = 50):
    """Agent task history (spec O)."""
    try:
        from sqlalchemy import desc, select

        limit = max(1, min(limit, 200))
        async with async_session_scope() as db:
            query = select(AgentTask).order_by(desc(AgentTask.created_at)).limit(limit)
            if conversation_id:
                query = query.where(AgentTask.conversation_id == conversation_id)

            result = await db.execute(query)
            tasks = result.scalars().all()

            return {
                "tasks": [
                    {
                        "id": task.id,
                        "conversation_id": task.conversation_id,
                        "task_type": task.task_type,
                        "agent_name": task.agent_name,
                        "status": task.status,
                        "input_params": task.input_params,
                        "result": task.result,
                        "error": task.error,
                        "execution_time_ms": task.execution_time_ms,
                        "created_at": task.created_at.isoformat(),
                        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    }
                    for task in tasks
                ]
            }
    except Exception as error:
        logger.error("list_tasks_error", error_type=type(error).__name__)
        raise HTTPException(500, "Could not load agent task history.")


@router.get("/status")
async def ai_status():
    """Report whether the assistant is usable, without exposing any key."""
    try:
        provider = get_ai_provider()
        return {
            "available": True,
            "provider": settings.ai_provider,
            "model": provider.get_model_name(),
            "streaming_enabled": settings.ai_enable_streaming,
            "voice_enabled": settings.ai_enable_voice,
            "max_conversation_messages": settings.ai_max_conversation_messages,
        }
    except Exception as error:
        logger.info("ai_status_unavailable", error_type=type(error).__name__)
        return {
            "available": False,
            "error": "not_configured",
            "message": public_error_message("unavailable", error),
        }
