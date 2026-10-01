"""
Phase 21C §16/§19 — provider circuit breaker tests.

The breaker is deterministic here: time is injected, so OPEN→HALF_OPEN→CLOSED
transitions are asserted exactly rather than with sleeps.
"""

from __future__ import annotations

import pytest

from app.esports.providers.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    GuardedProvider,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_opens_after_threshold_then_half_opens_and_closes():
    clock = _Clock()
    breaker = CircuitBreaker("csapi.de", failure_threshold=3, cooldown_seconds=10, clock=clock)

    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request() is True

    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert breaker.allow_request() is False
    assert breaker.retry_after_seconds == pytest.approx(10)

    clock.advance(10)
    assert breaker.allow_request() is True  # single half-open probe
    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.allow_request() is False  # only one probe at a time

    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.snapshot()["consecutive_failures"] == 0


def test_half_open_probe_failure_reopens_the_circuit():
    clock = _Clock()
    breaker = CircuitBreaker("x", failure_threshold=1, cooldown_seconds=5, clock=clock)
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    clock.advance(5)
    assert breaker.allow_request() is True
    breaker.record_failure()  # the probe failed
    assert breaker.state is CircuitState.OPEN
    assert breaker.allow_request() is False
    assert breaker.snapshot()["tripped_count"] == 2


def test_registry_returns_one_breaker_per_provider():
    registry = CircuitBreakerRegistry(failure_threshold=2, cooldown_seconds=30)
    a = registry.for_provider("csapi.de")
    assert a is registry.for_provider("csapi.de")
    assert registry.for_provider("opendota.com") is not a
    assert set(registry.snapshot()) == {"csapi.de", "opendota.com"}


@pytest.mark.asyncio
async def test_guarded_provider_short_circuits_without_calling_upstream():
    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        def get_provider_name(self) -> str:
            return "csapi.de"

        async def get_games(self):
            self.calls += 1
            raise RuntimeError("upstream down")

    provider = Provider()
    breaker = CircuitBreaker("csapi.de", failure_threshold=2, cooldown_seconds=100)
    guarded = GuardedProvider(provider, breaker)

    # Sync accessors pass straight through.
    assert guarded.get_provider_name() == "csapi.de"

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await guarded.get_games()
    assert breaker.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await guarded.get_games()
    assert provider.calls == 2  # the refused call never reached the upstream
