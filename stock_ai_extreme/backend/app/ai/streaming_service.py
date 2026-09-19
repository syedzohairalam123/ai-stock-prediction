"""
Streaming Service

Provides Server-Sent Events (SSE) streaming for real-time AI responses.
Implements proper error handling, cancellation, and state management.
"""
from typing import AsyncIterator, Dict, List, Optional
import json
import asyncio
from datetime import datetime
import structlog

from .errors import classify_provider_error, public_error_message
from .providers import AIProvider
from .prompt_builder import PromptBuilder

logger = structlog.get_logger(__name__)


class StreamingService:
    """
    Service for streaming AI responses using Server-Sent Events (SSE).
    
    Handles:
    - Real-time response streaming
    - Error handling during streaming
    - Cancellation support
    - Progress indicators
    """
    
    def __init__(self, provider: AIProvider):
        self.provider = provider
        self.prompt_builder = PromptBuilder()
    
    async def stream_response(
        self,
        user_question: str,
        context: Dict,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        request_id: Optional[str] = None,
        conversation_id: Optional[int] = None,
        citations: Optional[List[Dict]] = None,
    ) -> AsyncIterator[Dict]:
        """
        Stream an AI response as structured events.

        Each item is ``{"event": <type>, "data": {...}}`` so the transport
        layer owns serialization and the caller can accumulate the answer
        without re-parsing SSE strings.

        Event types: ``status`` (thinking/streaming), ``chunk``, ``complete``,
        ``error``. The context id and the source list are carried on every event
        so a client that connects mid-stream can still resolve the conversation.
        """
        started = datetime.utcnow()
        full_content = ""
        chunk_count = 0

        def envelope(event: str, data: Dict, status: str) -> Dict:
            """Wrap a payload with its SSE event name and semantic lifecycle state.

            ``status`` is the lifecycle value the client switches on
            (``thinking`` / ``streaming`` / ``complete`` / ``error``); it is
            deliberately separate from the event name so the two can never be
            confused.
            """
            return {"event": event, "data": {"status": status, **data}}

        try:
            # Send initial "thinking" event
            yield envelope("status", {"conversation_id": conversation_id}, "thinking")

            # Build messages
            messages = self.prompt_builder.build_messages(
                user_question=user_question,
                context=context,
                conversation_history=conversation_history,
            )

            # Send "streaming" status
            yield envelope("status", {"conversation_id": conversation_id}, "streaming")

            async for chunk in self.provider.chat_completion_stream(
                messages=messages,
                temperature=temperature,
            ):
                if not chunk:
                    continue
                full_content += chunk
                chunk_count += 1
                yield envelope("chunk", {"content": chunk}, "streaming")

            processing_time = int((datetime.utcnow() - started).total_seconds() * 1000)

            yield envelope(
                "complete",
                {
                    "conversation_id": conversation_id,
                    "full_content": full_content,
                    "chunk_count": chunk_count,
                    "processing_time_ms": processing_time,
                    "model": self.provider.get_model_name(),
                    "citations": citations or [],
                    "stopped": False,
                },
                "complete",
            )

            logger.info(
                "streaming_completed",
                request_id=request_id,
                conversation_id=conversation_id,
                provider=self.provider.__class__.__name__,
                model=self.provider.get_model_name(),
                chunks=chunk_count,
                latency_ms=processing_time,
                content_length=len(full_content),
                success=True,
            )

        except asyncio.CancelledError:
            # The client went away (Stop generating / navigation). Surface what
            # was generated so the caller can persist the partial answer.
            logger.info(
                "streaming_cancelled",
                request_id=request_id,
                conversation_id=conversation_id,
                chunks=chunk_count,
                content_length=len(full_content),
            )
            yield envelope(
                "complete",
                {
                    "conversation_id": conversation_id,
                    "full_content": full_content,
                    "chunk_count": chunk_count,
                    "processing_time_ms": int((datetime.utcnow() - started).total_seconds() * 1000),
                    "model": self.provider.get_model_name(),
                    "citations": citations or [],
                    "stopped": True,
                },
                "complete",
            )

        except Exception as e:
            category = classify_provider_error(e)
            logger.error(
                "streaming_error",
                request_id=request_id,
                conversation_id=conversation_id,
                provider=self.provider.__class__.__name__,
                model=self.provider.get_model_name(),
                latency_ms=int((datetime.utcnow() - started).total_seconds() * 1000),
                error_category=category,
                error_type=type(e).__name__,
                success=False,
            )
            yield envelope(
                "error",
                {
                    "error": public_error_message(category, e),
                    "error_type": type(e).__name__,
                    "category": category,
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                },
                "error",
            )
    
    async def get_non_streaming_response(
        self,
        user_question: str,
        context: Dict,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
    ) -> Dict:
        """
        Get complete (non-streaming) AI response.
        
        Args:
            user_question: User's question
            context: Context from ContextBuilder
            conversation_history: Previous conversation messages
            temperature: Sampling temperature
            
        Returns:
            Complete response dict with content, model, usage, etc.
        """
        try:
            start_time = datetime.utcnow()
            
            # Build messages
            messages = self.prompt_builder.build_messages(
                user_question=user_question,
                context=context,
                conversation_history=conversation_history,
            )
            
            # Get completion
            response = await self.provider.chat_completion(
                messages=messages,
                temperature=temperature,
            )
            
            processing_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            result = {
                "content": response["content"],
                "model": response["model"],
                "usage": response.get("usage", {}),
                "processing_time_ms": processing_time,
                "finish_reason": response.get("finish_reason", "stop"),
            }
            
            logger.info(
                "non_streaming_completed",
                processing_time_ms=processing_time,
                content_length=len(response["content"]),
                tokens=response.get("usage", {}).get("total_tokens", 0),
            )
            
            return result
            
        except Exception as e:
            logger.error("non_streaming_error", error=str(e))
            raise
    
    @staticmethod
    def format_sse_event(event_type: str, data: Dict) -> str:
        """
        Format data as Server-Sent Event.
        
        Args:
            event_type: Event type (status, chunk, complete, error)
            data: Event data
            
        Returns:
            SSE-formatted string
        """
        # SSE format:
        # event: <type>
        # data: <json>
        # \n
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


class StreamingContext:
    """
    Context manager for streaming sessions.
    
    Tracks active streams and provides cancellation support.
    """
    
    def __init__(self):
        self.active_streams: Dict[str, asyncio.Task] = {}
    
    def register_stream(self, stream_id: str, task: asyncio.Task):
        """Register an active stream."""
        self.active_streams[stream_id] = task
        logger.info("stream_registered", stream_id=stream_id)
    
    def cancel_stream(self, stream_id: str) -> bool:
        """
        Cancel an active stream.
        
        Returns:
            True if stream was found and cancelled, False otherwise
        """
        if stream_id in self.active_streams:
            task = self.active_streams[stream_id]
            task.cancel()
            del self.active_streams[stream_id]
            logger.info("stream_cancelled", stream_id=stream_id)
            return True
        return False
    
    def unregister_stream(self, stream_id: str):
        """Unregister a completed stream."""
        if stream_id in self.active_streams:
            del self.active_streams[stream_id]
            logger.info("stream_unregistered", stream_id=stream_id)
    
    def get_active_count(self) -> int:
        """Get number of active streams."""
        return len(self.active_streams)
    
    async def cancel_all_streams(self):
        """Cancel all active streams."""
        for stream_id in list(self.active_streams.keys()):
            self.cancel_stream(stream_id)
        logger.info("all_streams_cancelled", count=len(self.active_streams))


# Global streaming context (singleton)
_streaming_context = StreamingContext()


def get_streaming_context() -> StreamingContext:
    """Get global streaming context."""
    return _streaming_context
