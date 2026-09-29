"""
Phase 21C §13, §16 — analytics store.

Three responsibilities, all bounded:

  * **Interest signals** this application actually records (a game page viewed,
    a search performed, a game followed). These are the only "engagement"
    numbers the trending engine is allowed to use — nothing is scraped or
    invented, exactly like the Phase 19 discovery counters.
  * **Aggregate cache** with TTL, so expensive historical analytics are computed
    once and reused until a real event invalidates them.
  * **Dirty set** marking which games/entities need recomputation after a match
    completes or fires a live event, which is what keeps §13's "recompute only
    the affected metrics" promise honest.

In-memory here, like every other cache in this project (``providers.cache``
documents the identical swap-in point): the only methods callers use are
``cache_get``/``cache_set``/``invalidate``, so a Redis-backed implementation can
replace this class without touching a single caller.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from typing import Any, Deque, Dict, Iterable, Optional, Set, Tuple

MAX_INTEREST_EVENTS = 5000
INTEREST_KINDS = ("view", "search", "follow")


class AnalyticsStore:
    def __init__(self, max_interest_events: int = MAX_INTEREST_EVENTS) -> None:
        self._lock = threading.Lock()
        self._interest: Deque[Tuple[float, str, Optional[str], str]] = deque(maxlen=max_interest_events)
        self._totals: Counter = Counter()
        self._per_game: Counter = Counter()  # (game_id, kind) -> count
        self._dirty_games: Set[str] = set()
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0
        # Events this process actually observed, per match and per game. Used by
        # the trending engine so "match activity" is a measured count rather
        # than an assumption.
        self._event_counts: Counter = Counter()
        self._event_counts_by_game: Counter = Counter()
        self._start_counts: Counter = Counter()

    # ---- interest signals -------------------------------------------------
    def record_interest(self, game_id: str, kind: str, match_id: Optional[str] = None) -> bool:
        """
        Record one real interest event. Unknown kinds are rejected rather than
        bucketed into a catch-all, so the signal set stays meaningful.
        """
        if kind not in INTEREST_KINDS or not game_id:
            return False
        with self._lock:
            self._interest.append((time.monotonic(), game_id, match_id, kind))
            self._totals[kind] += 1
            self._per_game[(game_id, kind)] += 1
        return True

    def interest_counts(self, window_seconds: int = 3600) -> Dict[str, Dict[str, int]]:
        """Per-game counts inside a rolling window (real recorded events only)."""
        cutoff = time.monotonic() - window_seconds
        result: Dict[str, Dict[str, int]] = {}
        with self._lock:
            for timestamp, game_id, _match_id, kind in self._interest:
                if timestamp < cutoff:
                    continue
                bucket = result.setdefault(game_id, {k: 0 for k in INTEREST_KINDS})
                bucket[kind] += 1
        return result

    def totals(self) -> Dict[str, int]:
        with self._lock:
            return {kind: int(self._totals.get(kind, 0)) for kind in INTEREST_KINDS}

    # ---- observed event/start counters (measured activity) --------------
    def record_event(self, match_id: Optional[str], game_id: Optional[str], event_type: str = "") -> None:
        with self._lock:
            if match_id:
                self._event_counts[match_id] += 1
            if game_id:
                self._event_counts_by_game[game_id] += 1
            if event_type in ("MATCH_STARTED", "MAP_STARTED") and match_id:
                self._start_counts[match_id] += 1

    def event_counts(self) -> Dict[str, int]:
        with self._lock:
            return {k: int(v) for k, v in self._event_counts.items()}

    def event_counts_by_game(self) -> Dict[str, int]:
        with self._lock:
            return {k: int(v) for k, v in self._event_counts_by_game.items()}

    def start_counts(self) -> Dict[str, int]:
        with self._lock:
            return {k: int(v) for k, v in self._start_counts.items()}

    # ---- dirty set (incremental recompute) --------------------------------
    def mark_dirty(self, game_id: Optional[str]) -> None:
        if not game_id:
            return
        with self._lock:
            self._dirty_games.add(game_id)

    def mark_all_dirty(self, game_ids: Iterable[str]) -> None:
        with self._lock:
            self._dirty_games.update(game_ids)

    def take_dirty(self) -> Set[str]:
        with self._lock:
            dirty = set(self._dirty_games)
            self._dirty_games.clear()
            return dirty

    def dirty_count(self) -> int:
        with self._lock:
            return len(self._dirty_games)

    # ---- cache ------------------------------------------------------------
    def cache_get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, value = entry
            if expires_at < now:
                # Expired-but-present: keep it for a stale fallback, count a miss.
                self._misses += 1
                return None
            self._hits += 1
            return value

    def cache_get_stale(self, key: str) -> Optional[Any]:
        """Last good value even if expired — for a provider outage, still labelled."""
        with self._lock:
            entry = self._cache.get(key)
            return entry[1] if entry else None

    def cache_set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._cache[key] = (time.monotonic() + ttl_seconds, value)

    def invalidate(self, prefix: Optional[str] = None) -> int:
        with self._lock:
            if prefix is None:
                removed = len(self._cache)
                self._cache.clear()
                return removed
            keys = [k for k in self._cache if k.startswith(prefix)]
            for key in keys:
                del self._cache[key]
            return len(keys)

    # ---- maintenance ------------------------------------------------------
    def prune(self, max_age_seconds: float = 7200.0) -> int:
        """Drop expired cache rows that are older than the stale-fallback grace."""
        cutoff = time.monotonic() - max_age_seconds
        removed = 0
        with self._lock:
            for key in [k for k, (expires, _v) in self._cache.items() if expires < cutoff]:
                del self._cache[key]
                removed += 1
        return removed

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "cache_entries": len(self._cache),
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "interest_events_retained": len(self._interest),
                "dirty_games": len(self._dirty_games),
                "totals": {kind: int(self._totals.get(kind, 0)) for kind in INTEREST_KINDS},
                "events_observed": int(sum(self._event_counts.values())),
                "matches_with_events": len(self._event_counts),
                "backend": "in-process-async-ttl",
            }


#: Process-wide singleton.
analytics_store = AnalyticsStore()
