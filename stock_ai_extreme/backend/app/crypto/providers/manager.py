"""
Provider manager: capability-aware fetching, failover and health (spec §52, §53).

The manager is the single place that knows *which* configured provider can
serve a given timeframe and how to obtain it:

  1. resolve the internal symbol to each provider's own symbol;
  2. prefer a provider that publishes the interval natively;
  3. for an ``ohlcv_rollup`` timeframe, fetch the real lower interval and roll
     it up with :func:`app.crypto.normalization.aggregate_candles` — the only
     transformation permitted, and one that never invents a candle;
  4. on failure, fail over to the next provider **only** when that provider can
     genuinely serve the same interval, and always report which source answered.

Fresh quotes and candle sets are cached through the project's shared
:class:`app.providers.cache.TTLCache`, so the module reuses one cache
implementation rather than introducing a second one. A total provider outage can
still serve the last good value from the same cache, labelled ``STALE``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.crypto.config import crypto_settings
from app.crypto.normalization import aggregate_candles, detect_gaps
from app.crypto.providers.base import (
    CandleSeries,
    CryptoMarketProvider,
    ProviderError,
    ProviderHealth,
    ProviderQuote,
)
from app.crypto.symbols import AssetMapping, symbol_service
from app.crypto.timeframes import AggregationMethod, TimeframeConfig, get_timeframe
from app.providers.cache import TTLCache

logger = logging.getLogger("neural_market.crypto.providers.manager")

#: Symbols never queried at full depth: rolling 24h stats come from the provider.
_QUOTE_CACHE_PREFIX = "crypto:quote:"
_CANDLE_CACHE_PREFIX = "crypto:candles:"
_STATS_CACHE_PREFIX = "crypto:stats:"
_META_CACHE_PREFIX = "crypto:meta:"


class CryptoMarketManager:
    """Orchestrates the configured crypto providers behind one interface."""

    def __init__(
        self,
        providers: Sequence[CryptoMarketProvider],
        *,
        cache: Optional[TTLCache] = None,
    ) -> None:
        if not providers:
            raise ValueError("At least one crypto provider is required.")
        self.providers: List[CryptoMarketProvider] = list(providers)
        self.cache = cache or TTLCache(default_ttl_seconds=crypto_settings.candles_cache_ttl_seconds)
        self._health: Dict[str, ProviderHealth] = {}
        self._failures: Dict[str, int] = {}
        self._successes: Dict[str, int] = {}

    # ------------------------------------------------------------------ resolve
    def resolve(self, symbol: str) -> AssetMapping:
        return symbol_service.resolve(symbol)

    def provider_symbol(self, provider: CryptoMarketProvider, asset: AssetMapping) -> Optional[str]:
        """Delegate to the adapter — it owns its own symbol convention (spec §51)."""
        return provider.symbol_for(asset)

    def _candidates(self, interval: str) -> List[CryptoMarketProvider]:
        """Providers that can serve ``interval`` natively, in configured order."""
        return [p for p in self.providers if interval in p.native_intervals]

    # ------------------------------------------------------------------ candles
    async def get_candles(
        self,
        symbol: str,
        timeframe_id: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        allow_stale: bool = True,
    ) -> CandleSeries:
        """
        Real OHLCV history for ``symbol`` at ``timeframe_id``.

        The returned series is always marked with the provider that answered, so
        the API can attribute it. An empty series (never a synthetic one) is
        returned when every provider fails and no cached value exists.
        """
        asset = self.resolve(symbol)
        timeframe = get_timeframe(timeframe_id)
        requested = self._clamp_limit(timeframe, limit)
        cache_key = f"{_CANDLE_CACHE_PREFIX}{timeframe.id}:{asset.internal}:{requested}"

        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        series, errors = await self._fetch(timeframe=timeframe, asset=asset, limit=requested)
        if series is not None and not series.empty:
            await self.cache.set(
                cache_key, series, ttl_seconds=self._candle_ttl(timeframe)
            )
            return series

        if allow_stale:
            stale = await self.cache.get_stale(cache_key)
            if stale is not None:
                stale.notes = list(stale.notes) + ["served from cache after provider failure"]
                return stale
        if series is None:
            return _empty_series(
                timeframe,
                asset,
                reason="no provider could serve this timeframe"
                + (f" ({'; '.join(errors)})" if errors else ""),
            )
        return series

    async def _fetch(
        self, *, timeframe: TimeframeConfig, asset: AssetMapping, limit: int
    ) -> Tuple[Optional[CandleSeries], List[str]]:
        errors: List[str] = []

        # Roll-up timeframes have no native interval: fetch the real source
        # interval and aggregate. The source is itself a supported interval, so
        # it goes through the same native path.
        if timeframe.aggregation_method is AggregationMethod.OHLCV_ROLLUP:
            source = get_timeframe(timeframe.source_interval)
            ratio = max(1, timeframe.duration_seconds // source.duration_seconds)
            source_limit = min(source.max_history_candles, limit * ratio)
            native = await self._fetch_native(source, asset, source_limit, errors)
            if native is None:
                return None, errors
            aggregated = aggregate_candles(native.candles, timeframe.duration_seconds)
            gaps = detect_gaps(
                aggregated, interval_seconds=timeframe.duration_seconds, timeframe=timeframe.id
            )
            series = CandleSeries(
                symbol=asset.internal,
                timeframe=timeframe.id,
                interval=timeframe.source_interval,
                candles=aggregated[-limit:] if limit else aggregated,
                stats={
                    **native.stats,
                    "aggregated_from": len(native.candles),
                    "aggregated_to": len(aggregated),
                    "missing_intervals": gaps.missing_intervals,
                },
                source=native.source,
                fetched_at=native.fetched_at,
                source_timestamp=native.source_timestamp,
                aggregated=True,
                notes=list(native.notes)
                + [
                    f"{timeframe.id} rolled up from {timeframe.source_interval} "
                    f"({len(native.candles)} → {len(aggregated)} buckets)"
                ],
            )
            return series, errors

        native_series = await self._fetch_native(timeframe, asset, limit, errors)
        return native_series, errors

    async def _fetch_native(
        self,
        timeframe: TimeframeConfig,
        asset: AssetMapping,
        limit: int,
        errors: List[str],
    ) -> Optional[CandleSeries]:
        candidates = self._candidates(timeframe.source_interval)
        if not candidates:
            errors.append(
                f"no configured provider publishes interval {timeframe.source_interval!r}"
            )
            return None

        for provider in candidates:
            provider_symbol = self.provider_symbol(provider, asset)
            if not provider_symbol:
                errors.append(f"{provider.name} has no mapping for {asset.internal}")
                continue
            try:
                series = await provider.get_historical_candles(
                    symbol=asset.internal,
                    provider_symbol=provider_symbol,
                    interval=timeframe.source_interval,
                    limit=min(limit, crypto_settings.max_history_candles),
                )
            except ProviderError as exc:
                self._note_failure(provider.name)
                errors.append(f"{provider.name}: {exc.message}")
                logger.info("crypto provider %s failed for %s: %s", provider.name, asset.internal, exc.message)
                continue
            except Exception as exc:  # never let one adapter break the request
                self._note_failure(provider.name)
                errors.append(f"{provider.name}: unexpected {type(exc).__name__}")
                logger.warning("crypto provider %s raised unexpectedly: %s", provider.name, exc)
                continue

            self._note_success(provider.name)
            if errors:
                series.notes = list(series.notes) + [f"failover: {'; '.join(errors)}"]
            return series
        return None

    # -------------------------------------------------------------------- quote
    async def get_quote(self, symbol: str, *, allow_stale: bool = True) -> ProviderQuote:
        asset = self.resolve(symbol)
        cache_key = f"{_QUOTE_CACHE_PREFIX}{asset.internal}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached

        errors: List[str] = []
        for provider in self.providers:
            provider_symbol = self.provider_symbol(provider, asset)
            if not provider_symbol:
                continue
            try:
                quote = await provider.get_quote(asset.internal, provider_symbol)
            except ProviderError as exc:
                self._note_failure(provider.name)
                errors.append(f"{provider.name}: {exc.message}")
                continue
            except Exception as exc:
                self._note_failure(provider.name)
                errors.append(f"{provider.name}: unexpected {type(exc).__name__}")
                logger.warning("crypto quote provider %s raised: %s", provider.name, exc)
                continue
            self._note_success(provider.name)
            quote.errors = list(errors)
            await self.cache.set(
                cache_key, quote, ttl_seconds=crypto_settings.quote_cache_ttl_seconds
            )
            return quote

        if allow_stale:
            stale = await self.cache.get_stale(cache_key)
            if stale is not None:
                return stale
        raise ProviderError("manager", "no provider could supply a quote: " + "; ".join(errors))

    # ------------------------------------------------------------- market stats
    async def get_market_stats(self, symbol: str) -> Optional[Dict[str, Any]]:
        asset = self.resolve(symbol)
        cache_key = f"{_STATS_CACHE_PREFIX}{asset.internal}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached
        for provider in self.providers:
            try:
                stats = await provider.get_market_stats(asset.internal, asset.coingecko_id)
            except ProviderError as exc:
                self._note_failure(provider.name)
                logger.debug("market stats unavailable from %s: %s", provider.name, exc.message)
                continue
            except Exception:
                self._note_failure(provider.name)
                continue
            if stats:
                self._note_success(provider.name)
                await self.cache.set(
                    cache_key, stats, ttl_seconds=crypto_settings.market_cache_ttl_seconds
                )
                return stats
        return None

    # ------------------------------------------------------- classification data
    async def _cached_metadata(self, key: str, fetch) -> Optional[Any]:
        """Cache an optional metadata read; ``None`` when the source has no answer.

        Metadata is never fabricated: if no configured provider implements the
        call, or every one fails, the result is ``None`` and the caller reports
        UNAVAILABLE.
        """
        cache_key = f"{_META_CACHE_PREFIX}{key}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached
        for provider in self.providers:
            handler = getattr(provider, fetch, None)
            if handler is None:
                continue
            try:
                value = await handler()
            except ProviderError as exc:
                self._note_failure(provider.name)
                logger.debug("metadata %s unavailable from %s: %s", fetch, provider.name, exc.message)
                continue
            except Exception:
                self._note_failure(provider.name)
                continue
            if value:
                self._note_success(provider.name)
                await self.cache.set(
                    cache_key, value, ttl_seconds=crypto_settings.market_cache_ttl_seconds * 5
                )
                return value
        return None

    async def get_categories(self) -> Optional[List[Dict[str, Any]]]:
        """Real provider category taxonomy (industry metadata)."""
        return await self._cached_metadata("categories", "get_categories")

    async def get_trending(self) -> Optional[List[Dict[str, Any]]]:
        """Real observed search-interest ranking."""
        return await self._cached_metadata("trending", "get_trending")

    async def get_public_treasury(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Publicly disclosed corporate holdings for one asset (spec §43)."""
        asset = self.resolve(symbol)
        if not asset.coingecko_id:
            return None
        cache_key = f"{_META_CACHE_PREFIX}treasury:{asset.internal}"
        cached = await self.cache.get(cache_key)
        if cached is not None:
            return cached
        for provider in self.providers:
            handler = getattr(provider, "get_public_treasury", None)
            if handler is None:
                continue
            try:
                value = await handler(asset.coingecko_id)
            except ProviderError as exc:
                self._note_failure(provider.name)
                logger.debug("treasury unavailable from %s: %s", provider.name, exc.message)
                continue
            except Exception:
                self._note_failure(provider.name)
                continue
            if value:
                self._note_success(provider.name)
                value["symbol"] = asset.internal
                await self.cache.set(
                    cache_key, value, ttl_seconds=crypto_settings.market_cache_ttl_seconds * 10
                )
                return value
        return None

    # ---------------------------------------------------------------- streaming
    def streaming_provider(self) -> Optional[CryptoMarketProvider]:
        """First configured provider that supports a real-time stream."""
        for provider in self.providers:
            if provider.supports_streaming():
                return provider
        return None

    # ------------------------------------------------------------------- health
    async def health(self, *, probe: bool = True) -> List[ProviderHealth]:
        results: List[ProviderHealth] = []
        for provider in self.providers:
            if probe:
                try:
                    health = await provider.health()
                except Exception as exc:
                    health = ProviderHealth(
                        provider=provider.name,
                        available=False,
                        checked_at=datetime.now(timezone.utc),
                        detail=f"{type(exc).__name__}",
                    )
            else:
                health = self._health.get(provider.name) or ProviderHealth(
                    provider=provider.name,
                    available=False,
                    checked_at=datetime.now(timezone.utc),
                    detail="not probed yet",
                )
            self._health[provider.name] = health
            results.append(health)
        return results

    def health_snapshot(self) -> List[Dict[str, Any]]:
        """Last known health without issuing a probe (for cheap status reads)."""
        return [
            (
                self._health[provider.name].to_dict()
                if provider.name in self._health
                else {
                    "provider": provider.name,
                    "available": None,
                    "status": "UNKNOWN",
                    "latency_ms": None,
                    "detail": "not probed yet",
                }
            )
            for provider in self.providers
        ]

    # -------------------------------------------------------------------- stats
    def stats(self) -> Dict[str, Any]:
        providers = []
        for provider in self.providers:
            entry: Dict[str, Any] = {
                "provider": provider.name,
                "successes": self._successes.get(provider.name, 0),
                "failures": self._failures.get(provider.name, 0),
                "native_intervals": sorted(provider.native_intervals),
                "streaming": provider.supports_streaming(),
            }
            if hasattr(provider, "stats"):
                entry["provider_stats"] = provider.stats()  # type: ignore[attr-defined]
            providers.append(entry)
        return {
            "providers": providers,
            "cache_backend": "in-process-ttl",
            "cache_entries": self.cache.size(),
            "health": self.health_snapshot(),
        }

    async def close(self) -> None:
        for provider in self.providers:
            try:
                await provider.close()
            except Exception:  # pragma: no cover - best-effort shutdown
                pass

    # ------------------------------------------------------------------ helpers
    def _clamp_limit(self, timeframe: TimeframeConfig, limit: Optional[int]) -> int:
        requested = limit if limit and limit > 0 else timeframe.max_history_candles
        return max(10, min(requested, timeframe.max_history_candles, crypto_settings.max_history_candles))

    def _candle_ttl(self, timeframe: TimeframeConfig) -> int:
        """
        Cache a live timeframe only briefly; a slow one can be held longer.

        Never longer than one bar: a cached 5m series must not outlive the bar it
        describes, or the API would report an outdated candle as current.
        """
        base = crypto_settings.candles_cache_ttl_seconds
        return int(max(5, min(base, max(5, timeframe.duration_seconds // 4))))

    def _note_success(self, provider: str) -> None:
        self._successes[provider] = self._successes.get(provider, 0) + 1
        self._failures[provider] = 0

    def _note_failure(self, provider: str) -> None:
        self._failures[provider] = self._failures.get(provider, 0) + 1


def _empty_series(timeframe: TimeframeConfig, asset: AssetMapping, *, reason: str) -> CandleSeries:
    """An explicitly empty series — the honest answer when no source responded."""
    return CandleSeries(
        symbol=asset.internal,
        timeframe=timeframe.id,
        interval=timeframe.source_interval,
        candles=[],
        stats={"received": 0, "accepted": 0, "malformed": 0, "invalid_invariant": 0, "duplicates": 0, "out_of_order": 0},
        source="unavailable",
        fetched_at=datetime.now(timezone.utc),
        notes=[reason],
    )
