"""
Phase 10: AI Financial Assistant

Comprehensive AI system for context-aware financial assistance with:
- Provider abstraction (OpenAI, OpenRouter, Anthropic)
- Context building from application state
- Structured prompt construction
- Specialized financial agents
- Conversation management
- Real-time streaming
- Citation extraction and provider error classification
"""

from .citations import extract_citations, summarise_citations
from .context_builder import ContextBuilder, build_comparison_context
from .conversation_service import ConversationService
from .errors import classify_provider_error, http_status_for, public_error_message
from .prompt_builder import PromptBuilder
from .providers import (
    AIProvider,
    AnthropicProvider,
    OpenAIProvider,
    OpenRouterProvider,
    get_ai_provider,
)
from .streaming_service import StreamingService

__all__ = [
    "AIProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "AnthropicProvider",
    "ContextBuilder",
    "PromptBuilder",
    "ConversationService",
    "StreamingService",
    "get_ai_provider",
    "build_comparison_context",
    "extract_citations",
    "summarise_citations",
    "classify_provider_error",
    "public_error_message",
    "http_status_for",
]
