"""
Phase 21C §17 — observability for the esports pipeline.

Tracks the things the spec asks for, from real measurements taken inside the
running system:

  * provider latency            (per source)
  * event ingestion rate        (rolling window)
  * WebSocket broadcast latency (measured around the broadcast await)
  * connected clients           (read from the WebSocket manager)
  * event processing time       (per normalized event)
  * analytics job duration      (per worker run)
  * cache lag / database latency
  * error rate

Everything is bounded (ring buffers) so a long-running server cannot grow
memory just by being observed. Percentiles are computed from the retained
samples with NumPy.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional

import numpy as np

#: How many recent samples each latency series keeps, and the rate window.
MAX_SAMPLES = 512
RATE_WINDOW_SECONDS = 300

_lock = threading.Lock()


class _Series:
    """A bounded latency series with running percentiles."""

    def __init__(self, maxlen: int = MAX_SAMPLES):
        self.samples: Deque[float] = deque(maxlen=maxlen)
        self.count = 0
        self.total_ms = 0.0
        self.max_ms = 0.0

    def add(self, value_ms: float) -> None:
        if value_ms is None or value_ms < 0:
            return
        self.samples.append(float(value_ms))
        self.count += 1
        self.total_ms += float(value_ms)
        self.max_ms = max(self.max_ms, float(value_ms))

    def summary(self) -> Dict[str, Optional[float]]:
        if not self.samples:
            return {"count": self.count, "p50": None, "p95": None, "p99": None,
                    "avg": None, "max": None, "last": None}
        values = np.asarray(self.samples, dtype=float)
        return {
            "count": self.count,
            "p50": round(float(np.percentile(values, 50)), 3),
            "p95": round(float(np.percentile(values, 95)), 3),
            "p99": round(float(np.percentile(values, 99)), 3),
            "avg": round(float(np.mean(values)), 3),
            "max": round(float(np.max(values)), 3),
            "last": round(float(values[-1]), 3),
        }


class EsportsObservability:
    def __init__(self) -> None:
        self.provider_latency: Dict[str, _Series] = {}
        self.ws_broadcast = _Series()
        self.event_processing = _Series()
        self.analytics_job = _Series()
        self.db_write = _Series()
        self._event_times: Deque[float] = deque(maxlen=5000)
        self._error_times: Deque[float] = deque(maxlen=5000)
        self._events_by_game: Dict[str, int] = {}
        self._jobs: Dict[str, Dict[str, object]] = {}
        self.started_at = time.time()

    # ---- recorders -------------------------------------------------------
    def record_provider_latency(self, source: str, latency_ms: float) -> None:
        with _lock:
            self.provider_latency.setdefault(source, _Series()).add(latency_ms)

    def record_ws_broadcast(self, latency_ms: float) -> None:
        with _lock:
            self.ws_broadcast.add(latency_ms)

    def record_event_processing(self, latency_ms: float) -> None:
        with _lock:
            self.event_processing.add(latency_ms)

    def record_analytics_job(self, name: str, latency_ms: float) -> None:
        with _lock:
            self.analytics_job.add(latency_ms)
            entry = self._jobs.setdefault(name, {"runs": 0, "last_ms": None, "last_at": None, "total_ms": 0.0})
            entry["runs"] = int(entry["runs"]) + 1
            entry["last_ms"] = round(float(latency_ms), 3)
            entry["last_at"] = time.time()
            entry["total_ms"] = float(entry["total_ms"]) + float(latency_ms)

    def record_db_write(self, latency_ms: float) -> None:
        with _lock:
            self.db_write.add(latency_ms)

    def record_event_ingested(self, game_id: Optional[str]) -> None:
        now = time.time()
        with _lock:
            self._event_times.append(now)
            key = game_id or "unknown"
            self._events_by_game[key] = self._events_by_game.get(key, 0) + 1

    def record_error(self) -> None:
        with _lock:
            self._error_times.append(time.time())

    # ---- reads -----------------------------------------------------------
    def _rate(self, times: Deque[float], window: float, now: float) -> float:
        recent = sum(1 for t in times if now - t <= window)
        return round(recent / window, 4)

    def event_rate_per_second(self, window: float = RATE_WINDOW_SECONDS) -> float:
        now = time.time()
        with _lock:
            return self._rate(self._event_times, window, now)

    def error_rate_per_second(self, window: float = RATE_WINDOW_SECONDS) -> float:
        now = time.time()
        with _lock:
            return self._rate(self._error_times, window, now)

    def snapshot(self, *, connected_clients: Optional[int] = None, ws_channels: Optional[int] = None) -> Dict[str, object]:
        now = time.time()
        with _lock:
            event_rate = self._rate(self._event_times, RATE_WINDOW_SECONDS, now)
            error_rate = self._rate(self._error_times, RATE_WINDOW_SECONDS, now)
            providers = {name: series.summary() for name, series in self.provider_latency.items()}
            jobs = {
                name: {
                    "runs": int(entry["runs"]),
                    "last_ms": entry["last_ms"],
                    "avg_ms": round(float(entry["total_ms"]) / max(1, int(entry["runs"])), 3),
                }
                for name, entry in self._jobs.items()
            }
            events_by_game = dict(self._events_by_game)
        snapshot: Dict[str, object] = {
            "uptime_seconds": round(now - self.started_at, 1),
            "event_ingestion_rate_per_second": event_rate,
            "error_rate_per_second": error_rate,
            "events_recorded_by_game": events_by_game,
            "provider_latency_ms": providers,
            "websocket_broadcast_latency_ms": self.ws_broadcast.summary(),
            "event_processing_ms": self.event_processing.summary(),
            "analytics_job_ms": self.analytics_job.summary(),
            "analytics_jobs": jobs,
            "database_write_ms": self.db_write.summary(),
            "cache_lag_seconds": None,
            "captured_at": now,
        }
        if connected_clients is not None:
            snapshot["connected_clients"] = connected_clients
        if ws_channels is not None:
            snapshot["ws_channels_with_subscribers"] = ws_channels
        return snapshot


#: Process-wide singleton (mirrors the other managers in this codebase).
esports_metrics = EsportsObservability()


def reset() -> None:
    """Test helper — clears every series."""
    global esports_metrics
    with _lock:
        esports_metrics = EsportsObservability()
