"""
Phase 21C §19 (spec §50) — rate limiting for the esports surface.

Two layers, both additive to the app-wide per-IP limiter:

  * :class:`EsportsRateLimitMiddleware` — a stricter bucket for the esports REST
    paths (``/api/esports`` and ``/api/v1/esports``). It is HTTP-only: Starlette's
    ``BaseHTTPMiddleware`` ignores ``websocket`` scopes, so it never interferes
    with the live stream.
  * :func:`ws_connection_allowed` — a guard applied when a WebSocket connection
    is *created*. A client that opens sockets in a tight loop is refused before a
    subscription is registered, which is what stops a connection storm at the
    source.

Both back onto the project's existing :class:`app.security.RateLimiter` — a
sliding window, so no new dependency and no shared state to lose on restart.
Over-limit REST requests get ``429``; an over-limit socket is closed with code
``1013`` ("try again later").
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.security import RateLimiter

#: Paths that carry the stricter esports bucket.
ESPORTS_REST_PREFIXES: Tuple[str, ...] = ("/api/esports", "/api/v1/esports")

rest_limiter = RateLimiter(
    max_requests=int(getattr(settings, "esports_rate_limit_max_requests", 240)),
    window_seconds=int(getattr(settings, "esports_rate_limit_window_seconds", 60)),
)
ws_limiter = RateLimiter(
    max_requests=int(getattr(settings, "esports_ws_max_connections", 30)),
    window_seconds=int(getattr(settings, "esports_rate_limit_window_seconds", 60)),
)


def client_key(connection: Any) -> str:
    """Best-effort client identity for a Request/WebSocket."""
    client = getattr(connection, "client", None)
    host = getattr(client, "host", None) if client else None
    return host or "unknown"


class EsportsRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding window scoped to the esports REST prefixes."""

    def __init__(self, app, limiter: RateLimiter = rest_limiter, prefixes: Iterable[str] = ESPORTS_REST_PREFIXES):
        super().__init__(app)
        self.limiter = limiter
        self.prefixes = tuple(prefixes)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.prefixes):
            return await call_next(request)
        allowed, remaining = self.limiter.allow(client_key(request))
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Esports rate limit exceeded. Try again shortly."},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def ws_connection_allowed(websocket: WebSocket) -> bool:
    """True when this client may open another esports WebSocket right now."""
    allowed, _remaining = ws_limiter.allow(f"esports-ws:{client_key(websocket)}")
    return allowed


def limiter_stats() -> Dict[str, Any]:
    """Small health readout surfaced through the esports health route."""
    return {
        "rest_max_requests": rest_limiter.max_requests,
        "rest_window_seconds": rest_limiter.window_seconds,
        "ws_max_connections": ws_limiter.max_requests,
        "ws_window_seconds": ws_limiter.window_seconds,
    }
