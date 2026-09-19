"""
Provider error classification (Phase 10, spec V / X)

One place that turns an exception from a model provider into:
  * a stable category the frontend can act on, and
  * a message that is safe to show a user (no stack traces, no key material,
    no provider internals).

Categories mirror the frontend's ``ChatErrorCategory`` so the UI can pick the
right recovery affordance (retry vs. "not configured" vs. wait-and-retry).
"""
from __future__ import annotations

import asyncio
from typing import Optional

UNAVAILABLE = "unavailable"
RATE_LIMIT = "rate_limit"
TIMEOUT = "timeout"
BACKEND = "backend"
EMPTY_RESPONSE = "empty_response"

#: Message shown for each category — written for a user, not a developer.
_CATEGORY_MESSAGES = {
    UNAVAILABLE: (
        "The assistant is not configured on this server. Set AI_PROVIDER and the matching "
        "API key, then restart the API."
    ),
    RATE_LIMIT: "The AI provider is rate-limiting requests. Wait a moment, then retry.",
    TIMEOUT: "The AI provider took too long to respond. Retry, or ask a narrower question.",
    BACKEND: "The AI provider returned an error. Retrying usually clears it.",
    EMPTY_RESPONSE: "The assistant returned an empty answer. Retry to generate a new one.",
}

_UNAVAILABLE_HINTS = (
    "api key",
    "api_key",
    "not configured",
    "unauthorized",
    "invalid_api_key",
    "no api key",
    "missing credentials",
    "authentication",
)
_RATE_LIMIT_HINTS = ("rate limit", "rate_limit", "too many requests", "429", "quota")
_TIMEOUT_HINTS = ("timeout", "timed out", "time out", "deadline")


def classify_provider_error(error: BaseException) -> str:
    """Map a provider exception onto a stable category string."""
    if isinstance(error, asyncio.TimeoutError):
        return TIMEOUT

    name = type(error).__name__.lower()
    text = f"{name} {error}".lower()

    # OpenAI SDK exposes typed errors; match their names as well as the text.
    if "authentication" in name or "permission" in name:
        return UNAVAILABLE
    if "ratelimit" in name or "rate_limit" in name:
        return RATE_LIMIT
    if "timeout" in name:
        return TIMEOUT

    if any(hint in text for hint in _UNAVAILABLE_HINTS):
        return UNAVAILABLE
    if any(hint in text for hint in _RATE_LIMIT_HINTS):
        return RATE_LIMIT
    if any(hint in text for hint in _TIMEOUT_HINTS):
        return TIMEOUT

    return BACKEND


def public_error_message(category: str, error: Optional[BaseException] = None) -> str:
    """
    Return a user-facing message for a category.

    The provider's own text is deliberately NOT forwarded: it routinely contains
    request payloads, key fragments and internal endpoints.
    """
    message = _CATEGORY_MESSAGES.get(category)
    if message:
        return message

    # Unknown category: stay useful without leaking internals.
    return "The assistant could not complete that request. Retry to try again."


def http_status_for(category: str) -> int:
    """HTTP status that best represents a category for non-streaming failures."""
    if category == UNAVAILABLE:
        return 503
    if category == RATE_LIMIT:
        return 429
    if category == TIMEOUT:
        return 504
    return 502
