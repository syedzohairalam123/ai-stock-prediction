"""
Phase 19 — basic API rate limiting + input validation.

The rate limiter is deliberately a simple in-memory sliding window, not
Redis-backed — it doesn't need to survive a restart (unlike Phase 3's
database), it just needs to stop a script from hammering this API (and,
transitively, hammering rate-limited free upstream providers like Alpha
Vantage). No new dependency needed for this.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

TICKER_PATTERN = re.compile(r"^[A-Za-z0-9.\-=^]{1,15}$")  # covers plain tickers, BRK.B, EURUSD=X, ^GSPC, GC=F, etc.


def validate_ticker(ticker: str) -> str:
    """Raises ValueError for anything that clearly isn't a ticker symbol —
    the point isn't to guess every valid symbol format perfectly, it's to
    reject obviously malformed/oversized input before it reaches a provider
    call or gets used to build a cache key."""
    if not ticker or not TICKER_PATTERN.match(ticker):
        raise ValueError(f"{ticker!r} doesn't look like a valid ticker symbol.")
    return ticker.upper()


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        q = self._hits[key]
        cutoff = now - self.window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= self.max_requests:
            return False, 0
        q.append(now)
        return True, self.max_requests - len(q)

    def cleanup(self, max_idle_seconds: int | None = None) -> int:
        """Drop buckets that haven't been touched in a while — otherwise the
        in-memory dict grows forever as distinct client IPs accumulate.
        Called periodically by the background maintenance loop; safe to call
        any time (a bucket whose last hit is older than the window contributes
        nothing to rate limiting anyway)."""
        idle = max_idle_seconds or max(self.window_seconds * 4, 300)
        cutoff = time.monotonic() - idle
        dead = [k for k, q in self._hits.items() if not q or q[-1] < cutoff]
        for k in dead:
            del self._hits[k]
        return len(dead)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter, exempt_prefixes: tuple[str, ...] = ("/docs", "/openapi", "/health")):
        super().__init__(app)
        self.limiter = limiter
        self.exempt_prefixes = exempt_prefixes

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in self.exempt_prefixes):
            return await call_next(request)
        client_key = request.client.host if request.client else "unknown"
        allowed, remaining = self.limiter.allow(client_key)
        if not allowed:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again shortly."})
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
