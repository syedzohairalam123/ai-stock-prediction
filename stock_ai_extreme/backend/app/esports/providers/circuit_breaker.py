"""
Phase 21C §16/§19 — provider circuit breaker.

A flaky or rate-limiting upstream must not be hammered once per request (and a
10,000-user fan-out must never multiply into 10,000 upstream connections). The
breaker sits in front of each provider adapter and, after a run of consecutive
failures, stops calling that upstream for a cool-down window instead of
retrying into a wall. When the window elapses it admits a single half-open probe:
one success closes the circuit, one failure re-opens it.

Two pieces:

  * :class:`CircuitBreaker` — the state machine (CLOSED / OPEN / HALF_OPEN),
    injectable clock so it is deterministic under test.
  * :class:`GuardedProvider` — a transparent proxy around an
    ``EsportsDataProvider`` that applies the breaker to every async provider
    call. Sync accessors (``get_provider_name``) pass straight through.

When the circuit is open, guarded calls raise :class:`CircuitOpenError`. Callers
already treat a provider exception as "this source has nothing right now" and
fall through to the next provider / an empty result, so an open circuit simply
degrades that one source — it never breaks the request.
"""

from __future__ import annotations

import inspect
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when a call is refused because the provider's circuit is open."""

    def __init__(self, provider: str, retry_after_seconds: float) -> None:
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"[{provider}] circuit open — retry in {retry_after_seconds:.0f}s"
        )


class CircuitBreaker:
    """Consecutive-failure circuit breaker with a single half-open probe."""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        clock=time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._half_open_in_flight = False
        self._tripped_count = 0

    # ------------------------------------------------------------------ query
    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def _retry_after(self) -> float:
        if self._opened_at is None:
            return 0.0
        return max(0.0, self.cooldown_seconds - (self._clock() - self._opened_at))

    @property
    def retry_after_seconds(self) -> float:
        with self._lock:
            return self._retry_after()

    # ------------------------------------------------------------------- gate
    def allow_request(self) -> bool:
        """True if a call may proceed (advancing OPEN→HALF_OPEN when due)."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if self._retry_after() <= 0:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_in_flight = True
                    return True
                return False
            # HALF_OPEN — admit exactly one probe at a time.
            if self._half_open_in_flight:
                return False
            self._half_open_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    self._tripped_count += 1
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()
                self._half_open_in_flight = False

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "provider": self.name,
                "state": self._state.value,
                "consecutive_failures": self._failures,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "retry_after_seconds": round(self._retry_after(), 3),
                "tripped_count": self._tripped_count,
            }


class CircuitBreakerRegistry:
    """One breaker per provider name, created on first use."""

    def __init__(self, *, failure_threshold: int = 5, cooldown_seconds: float = 60.0, clock=time.monotonic) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._breakers: Dict[str, CircuitBreaker] = {}

    def for_provider(self, name: str) -> CircuitBreaker:
        with self._lock:
            breaker = self._breakers.get(name)
            if breaker is None:
                breaker = CircuitBreaker(
                    name,
                    failure_threshold=self.failure_threshold,
                    cooldown_seconds=self.cooldown_seconds,
                    clock=self._clock,
                )
                self._breakers[name] = breaker
            return breaker

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {name: breaker.snapshot() for name, breaker in self._breakers.items()}


class GuardedProvider:
    """
    Proxy that puts a provider's async methods behind its circuit breaker.

    Only coroutine functions are wrapped, and private/attribute access passes
    through untouched, so the proxy is a drop-in replacement for the adapter.
    """

    def __init__(self, inner: Any, breaker: CircuitBreaker) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_breaker", breaker)

    def __getattr__(self, item: str) -> Any:
        attr = getattr(object.__getattribute__(self, "_inner"), item)
        if item.startswith("_") or not inspect.iscoroutinefunction(attr):
            return attr
        breaker = object.__getattribute__(self, "_breaker")

        async def guarded(*args: Any, **kwargs: Any) -> Any:
            if not breaker.allow_request():
                raise CircuitOpenError(breaker.name, breaker.retry_after_seconds)
            try:
                result = await attr(*args, **kwargs)
            except Exception:
                breaker.record_failure()
                raise
            breaker.record_success()
            return result

        return guarded
