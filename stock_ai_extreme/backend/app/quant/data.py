"""
Phase 21 — real data acquisition for the analytics layer.

This module is the *only* place the quant package touches the network, and it
touches it exclusively through the Phase 2 `MarketDataManager` (injected via
`quant.state`). Consequences worth stating explicitly:

* No new provider, no new API key, no new HTTP client, no new cache.
* Every block returns the provider's own `source` and `status`, so the API can
  label a result LIVE / DELAYED / STALE / UNAVAILABLE instead of implying
  freshness it does not have.
* A failed fetch yields **no series**, never a synthetic one. Downstream
  analytics then report "insufficient data" with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from ..config import settings
from ..logging_config import get_logger
from .series import ReturnSeries, build_return_series
from .state import get_manager

logger = get_logger("neural_market.quant.data")


@dataclass
class PriceBundle:
    """Real OHLC-derived closes for one symbol, plus the provenance to trust them."""

    symbol: str
    provider_symbol: str
    closes: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    timestamps: list[datetime] = field(default_factory=list)
    source: Optional[str] = None
    status: Optional[str] = None
    #: None when the fetch failed outright — distinguishably different from [].
    error: Optional[str] = None
    interval: str = "1d"

    @property
    def available(self) -> bool:
        return bool(self.closes) and self.error is None

    @property
    def observations(self) -> int:
        return len(self.closes)

    def return_series(self, *, use_log: bool = True) -> ReturnSeries:
        return build_return_series(
            self.closes,
            self.timestamps,
            source=f"{self.source or 'unknown'} ({self.provider_symbol}, {self.interval})",
            is_real_data=self.error is None and bool(self.closes),
            use_log=use_log,
        )

    def as_timestamped(self) -> dict[datetime, float]:
        """`{timestamp: close}` for `series.align_returns`."""
        out: dict[datetime, float] = {}
        for ts, close in zip(self.timestamps, self.closes):
            out[ts] = close
        return out

    def describe(self) -> dict:
        return {
            "symbol": self.symbol,
            "providerSymbol": self.provider_symbol,
            "observations": self.observations,
            "interval": self.interval,
            "source": self.source,
            "status": self.status,
            "start": self.timestamps[0].isoformat() if self.timestamps else None,
            "end": self.timestamps[-1].isoformat() if self.timestamps else None,
            "error": self.error,
        }


def _coerce_frame(frame: Any, bundle: PriceBundle) -> None:
    """Extract honest columns from a provider DataFrame.

    Uses only columns the provider actually returned; a missing High/Low/Volume
    column leaves the corresponding list empty rather than being back-filled
    with the close price, because a fabricated high would corrupt Parkinson-style
    volatility and range statistics downstream.
    """
    if frame is None or getattr(frame, "empty", True):
        return

    def _numeric(column: str) -> list[float]:
        if column not in getattr(frame, "columns", []):
            return []
        try:
            values = frame[column].tolist()
        except Exception:  # pragma: no cover - defensive
            return []
        out: list[float] = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number == number and abs(number) != float("inf"):  # reject NaN/Inf
                out.append(number)
        return out

    closes = _numeric("Close")
    highs = _numeric("High")
    lows = _numeric("Low")
    volumes = _numeric("Volume")

    stamps: list[datetime] = []
    try:
        for index in frame.index:
            try:
                stamp = index.to_pydatetime()
            except AttributeError:
                stamp = index if isinstance(index, datetime) else None
            if stamp is None:
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamps.append(stamp.astimezone(timezone.utc))
    except Exception:  # pragma: no cover - defensive
        stamps = []

    # Only keep closes whose timestamp we could read, so indices stay aligned.
    if stamps and len(stamps) == len(closes):
        bundle.closes = closes
        bundle.timestamps = stamps
    elif closes:
        # Timestamps unusable: keep the closes (statistics do not need dates)
        # but leave timestamps empty rather than inventing them.
        bundle.closes = closes
        bundle.timestamps = []

    if highs and len(highs) == len(bundle.closes):
        bundle.highs = highs
    if lows and len(lows) == len(bundle.closes):
        bundle.lows = lows
    if volumes and len(volumes) == len(bundle.closes):
        bundle.volumes = volumes


async def fetch_prices(
    symbol: str,
    *,
    provider_symbol: Optional[str] = None,
    lookback_days: Optional[int] = None,
    interval: str = "1d",
) -> PriceBundle:
    """Fetch real daily bars for one symbol through the shared provider manager."""
    from ..paper.config import paper_settings

    days = lookback_days or paper_settings.paper_volatility_lookback_days * 2
    target = (provider_symbol or symbol or "").strip().upper()
    bundle = PriceBundle(symbol=(symbol or "").strip().upper(), provider_symbol=target, interval=interval)
    if not target:
        bundle.error = "no symbol supplied"
        return bundle

    manager = get_manager()
    if manager is None:
        bundle.error = "the market-data provider layer is not configured on the server"
        return bundle

    end = date.today()
    start = end - timedelta(days=int(days))
    try:
        frame, source, status = await manager.history(target, start, end, interval)
    except Exception as exc:
        logger.debug("price history unavailable for %s: %s", target, exc)
        bundle.error = f"the provider could not return history for {target}: {exc}"
        return bundle

    bundle.source = source
    bundle.status = getattr(status, "value", None) or (str(status) if status is not None else None)
    _coerce_frame(frame, bundle)
    if not bundle.closes:
        bundle.error = f"the provider returned no usable bars for {target} over the last {days} days"
    return bundle


async def fetch_series(
    symbol: str,
    *,
    provider_symbol: Optional[str] = None,
    lookback_days: Optional[int] = None,
    interval: str = "1d",
    use_log: bool = True,
) -> tuple[PriceBundle, ReturnSeries]:
    """Convenience: real prices plus their prepared return series."""
    bundle = await fetch_prices(
        symbol,
        provider_symbol=provider_symbol,
        lookback_days=lookback_days,
        interval=interval,
    )
    return bundle, bundle.return_series(use_log=use_log)


async def fetch_aligned(
    symbol_a: str,
    symbol_b: str,
    *,
    lookback_days: Optional[int] = None,
    interval: str = "1d",
    use_log: bool = True,
) -> dict:
    """Fetch two real series and align them on shared timestamps.

    Alignment happens on real dated observations via `series.align_returns`, so a
    beta is never computed across mismatched calendars (a PSX symbol trading
    Friday and a US symbol trading Monday are *not* the same interval).
    """
    from .series import align_returns

    bundle_a = await fetch_prices(symbol_a, lookback_days=lookback_days, interval=interval)
    bundle_b = await fetch_prices(symbol_b, lookback_days=lookback_days, interval=interval)

    result: dict = {
        "a": bundle_a.describe(),
        "b": bundle_b.describe(),
        "aligned": False,
        "observations": 0,
        "timestamps": [],
    }
    if not bundle_a.available or not bundle_b.available:
        result["reason"] = (
            f"cannot align: {bundle_a.symbol} {'ok' if bundle_a.available else 'unavailable'}, "
            f"{bundle_b.symbol} {'ok' if bundle_b.available else 'unavailable'}"
        )
        return result

    ra, rb, ts = align_returns(bundle_a.as_timestamped(), bundle_b.as_timestamped(), use_log=use_log)
    result.update({
        "aligned": bool(ra),
        "observations": len(ra),
        "returnsA": ra,
        "returnsB": rb,
        "timestamps": [t.isoformat() for t in ts[:400]],
    })
    if not ra:
        result["reason"] = (
            f"{bundle_a.symbol} and {bundle_b.symbol} share no common dated observations, "
            "so no paired statistic can be computed"
        )
    return result


async def fetch_benchmark(lookback_days: Optional[int] = None, interval: str = "1d") -> PriceBundle:
    """The app's configured benchmark index/ETF, used as the market factor."""
    configured = (getattr(settings, "quant_benchmark_symbol", None) or getattr(settings, "benchmark_symbol", None) or "SPY")
    return await fetch_prices(str(configured), lookback_days=lookback_days, interval=interval)
