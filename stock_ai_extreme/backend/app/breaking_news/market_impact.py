"""
Market impact association (spec §7–§10) and forecast probability movement (§8).

    news event -> affected entity -> market data before -> market data after
        -> observed movement

The wording matters and is enforced everywhere in this module: nothing here says
*"this news caused the price to move"*. Every record carries the note
"Price movement observed after publication" because that is exactly, and only,
what the data supports.

How the numbers are produced
---------------------------
* Real OHLCV bars are pulled through the existing Phase 2 provider layer
  (:class:`~..providers.MarketDataManager`) at an interval appropriate to each
  observation window (1m / 5m / 15m / 1h — see
  :attr:`~.config.BreakingNewsSettings.window_intervals`).
* A window is reported **only** when it holds at least
  ``min_bars_for_window`` real bars on *both* sides of the publication time.
  Otherwise the window is returned as unavailable with a reason. A five-minute
  window built from a single daily bar is not a five-minute window.
* ``correlation_score`` is deliberately *not* a statistical correlation. It is
  the observed move expressed in standard deviations of the symbol's own
  trailing return distribution — a magnitude ("how unusual was this move for
  this instrument?") and it is labelled as such.

Forecast probability movement comes from real CLOB trade history
(:mod:`..forecast_history`) for markets on the Phase 14 surface. A market whose
token never traded produces no row — never a synthetic before/after pair.
"""
from __future__ import annotations

import asyncio
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Optional

from ..logging_config import get_logger
from ..news_analytics import tokenize
from ..symbols import is_psx_symbol, to_yahoo_symbol
from .config import breaking_news_settings
from .schemas import ImpactMagnitude
from .timeutil import parse_datetime, to_naive_utc, utcnow

logger = get_logger("neural_market.breaking_news.market_impact")

#: Policy actors and institutions that move markets but are not instruments.
#: Resolving one to a provider symbol would be an invention (there is no ticker
#: for "the Fed"), so they are reported as non-priceable instead. Mirrored by
#: ``entities.NON_PRICEABLE_ENTITIES``, which is derived from this set.
POLICY_ENTITIES: frozenset[str] = frozenset({"FED", "ECB", "OPEC", "IMF", "SBP", "SECP"})

#: Window label -> length in minutes.
WINDOW_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "24h": 1440,
}

#: Index label -> provider symbol. PSX indices are not carried by the keyless
#: provider, so they resolve to ``None`` and are honestly reported UNAVAILABLE
#: instead of being approximated by something else.
INDEX_SYMBOLS: dict[str, Optional[str]] = {
    "SPX": "^GSPC",
    "SPX500": "^GSPC",
    "DJI": "^DJI",
    "NDAQ": "^IXIC",
    "FTSE": "^FTSE",
    "DAX": "^GDAXI",
    "N225": "^N225",
    "NIFTY": "^NSEI",
    "KSE100": None,
    "KSE30": None,
    "KMI30": None,
    "ALLSHR": None,
    "KSEALL": None,
}

#: Friendly asset names -> provider symbols, for commodity / FX / crypto entities
#: that a headline refers to by name ("gold", "crude", "bitcoin").
ASSET_SYMBOLS: dict[str, str] = {
    # commodities
    "GOLD": "GC=F", "SILVER": "SI=F", "OIL": "CL=F", "CRUDE": "CL=F",
    "WTI": "CL=F", "BRENT": "BZ=F", "NATURALGAS": "NG=F", "GAS": "NG=F",
    "COPPER": "HG=F", "PLATINUM": "PL=F", "WHEAT": "ZW=F", "CORN": "ZC=F",
    # crypto
    "BTC": "BTC-USD", "BITCOIN": "BTC-USD", "ETH": "ETH-USD", "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD", "SOLANA": "SOL-USD", "XRP": "XRP-USD", "ADA": "ADA-USD",
    "DOGE": "DOGE-USD", "DOGECOIN": "DOGE-USD",
    # fx
    "USD": "DX-Y.NYB", "DOLLAR": "DX-Y.NYB", "DXY": "DX-Y.NYB",
    "EUR": "EURUSD=X", "EURUSD": "EURUSD=X", "EUR/USD": "EURUSD=X",
    "GBP": "GBPUSD=X", "GBPUSD": "GBPUSD=X", "GBP/USD": "GBPUSD=X",
    "JPY": "USDJPY=X", "USDJPY": "USDJPY=X", "USD/JPY": "USDJPY=X",
    "PKR": "USDPKR=X", "USDPKR": "USDPKR=X", "USD/PKR": "USDPKR=X",
    "CHF": "USDCHF=X", "AUD": "AUDUSD=X",
}

#: Absolute percent move thresholds per asset class. Documented and overridable
#: through the constructor — a 1% move is large for an FX pair and small for a
#: small-cap equity, so one global threshold would be misleading.
DEFAULT_MAGNITUDE_THRESHOLDS: dict[str, tuple[tuple[float, str], ...]] = {
    "DEFAULT": ((2.0, "HIGH"), (0.75, "MEDIUM"), (0.15, "LOW")),
    "FOREX": ((0.6, "HIGH"), (0.25, "MEDIUM"), (0.05, "LOW")),
    "CRYPTO": ((4.0, "HIGH"), (1.5, "MEDIUM"), (0.4, "LOW")),
    "INDEX": ((1.5, "HIGH"), (0.5, "MEDIUM"), (0.1, "LOW")),
}

#: Reference standard-deviation scale for the abnormal-return score, per class.
_VOLATILITY_FLOOR = 1e-6


@dataclass
class Bar:
    timestamp: datetime
    close: float
    volume: Optional[float] = None


@dataclass
class HistoryBundle:
    """Real bars plus their provenance."""

    bars: list[Bar] = field(default_factory=list)
    source: Optional[str] = None
    status: Optional[str] = None
    requested_symbol: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.bars) and not self.error


#: signature of the injectable history fetcher the analyzer needs
HistoryFetcher = Callable[[str, date, date, str], "asyncio.Future | Any"]


class ProviderHistoryFetcher:
    """Adapts the Phase 2 provider manager into the analyzer's fetcher contract.

    Kept as its own class (rather than importing the manager into the analyzer)
    so the analyzer can be unit-tested against a deterministic fake fetcher — no
    network, no flakiness — while production still uses the real provider chain.
    """

    def __init__(self, manager: Any, *, cache_ttl_seconds: int = 120):
        self.manager = manager
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[tuple, tuple[float, HistoryBundle]] = {}

    async def fetch(self, symbol: str, start: date, end: date, interval: str) -> HistoryBundle:
        key = (symbol.upper(), start, end, interval)
        now = datetime.now().timestamp()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        try:
            frame, source, status = await self.manager.history(symbol, start, end, interval)
        except Exception as exc:
            bundle = HistoryBundle(requested_symbol=symbol, error=str(exc))
            self._cache[key] = (now + 10.0, bundle)
            return bundle

        bars = _frame_to_bars(frame)
        bundle = HistoryBundle(
            bars=bars,
            source=source,
            status=getattr(status, "value", str(status)),
            requested_symbol=symbol,
        )
        self._cache[key] = (now + self.cache_ttl_seconds, bundle)
        return bundle

    def purge(self, keep_seconds: float = 600.0) -> int:
        now = datetime.now().timestamp()
        expired = [k for k, (expiry, _) in self._cache.items() if expiry + keep_seconds < now]
        for key in expired:
            self._cache.pop(key, None)
        return len(expired)


def _frame_to_bars(frame: Any) -> list[Bar]:
    """Convert an OHLCV DataFrame into timestamped bars, dropping bad rows."""
    bars: list[Bar] = []
    if frame is None or getattr(frame, "empty", True):
        return bars
    try:
        for index, row in frame.iterrows():
            try:
                close = float(row["Close"])
            except (TypeError, ValueError, KeyError):
                continue
            if math.isnan(close):
                continue
            volume = row.get("Volume") if hasattr(row, "get") else None
            try:
                volume = float(volume) if volume is not None and not math.isnan(float(volume)) else None
            except (TypeError, ValueError):
                volume = None
            timestamp = parse_datetime(index)
            if timestamp is None:
                continue
            bars.append(Bar(timestamp=timestamp, close=close, volume=volume))
    except Exception as exc:  # a malformed frame must not break the run
        logger.warning("could not convert frame to bars: %s", exc)
        return []
    bars.sort(key=lambda b: b.timestamp)
    return bars


def resolve_entity(entity: str, entity_type: str = "AUTO") -> tuple[Optional[str], str]:
    """Resolve an entity to (provider symbol, resolved entity type).

    ``(None, type)`` means the entity is real but not priceable through the
    configured providers — the caller must report UNAVAILABLE rather than
    substitute a proxy.
    """
    name = (entity or "").strip().upper()
    kind = (entity_type or "AUTO").upper()
    if not name:
        return None, kind

    if name in POLICY_ENTITIES:
        # A rate-setting institution is not a price series. Reported so the caller
        # can label it UNAVAILABLE instead of asking a provider for "FED".
        return None, "POLICY"

    if kind == "AUTO":
        if name in INDEX_SYMBOLS:
            kind = "INDEX"
        elif name in ASSET_SYMBOLS:
            kind = _asset_kind(name)
        else:
            kind = "STOCK"

    if kind == "INDEX":
        return INDEX_SYMBOLS.get(name), "INDEX"
    if kind in {"COMMODITY", "FOREX", "CRYPTO"}:
        return ASSET_SYMBOLS.get(name, name if _looks_like_symbol(name) else None), kind
    if kind == "FORECAST":
        return None, "FORECAST"
    # STOCK: PSX symbols map onto their Yahoo listing; anything else is passed
    # through to the provider, which applies its own candidate chain.
    return (to_yahoo_symbol(name) if is_psx_symbol(name) else name), "STOCK"


def _asset_kind(name: str) -> str:
    if name in {"BTC", "BITCOIN", "ETH", "ETHEREUM", "SOL", "SOLANA", "XRP", "ADA", "DOGE", "DOGECOIN"}:
        return "CRYPTO"
    if any(ch in name for ch in ("=", "-")) or name.endswith("USD"):
        return "FOREX"
    if name in {"GOLD", "SILVER", "OIL", "CRUDE", "WTI", "BRENT", "NATURALGAS", "GAS", "COPPER", "PLATINUM", "WHEAT", "CORN"}:
        return "COMMODITY"
    return "FOREX"


def _looks_like_symbol(value: str) -> bool:
    return bool(value) and all(ch.isalnum() or ch in ".-=^/" for ch in value)


class MarketImpactAnalyzer:
    """Measures the market movement observed around a news publication."""

    def __init__(
        self,
        settings: Any = None,
        *,
        magnitude_thresholds: Optional[dict[str, tuple[tuple[float, str], ...]]] = None,
    ):
        self.settings = settings or breaking_news_settings
        self.window_minutes = dict(WINDOW_MINUTES)
        self.observation_windows = list(self.settings.observation_windows)
        self.magnitude_thresholds = magnitude_thresholds or DEFAULT_MAGNITUDE_THRESHOLDS

    # ------------------------------------------------------------------
    # single window
    # ------------------------------------------------------------------

    async def analyze_window(
        self,
        *,
        published_at: datetime,
        entity: str,
        entity_type: str,
        observation_window: str,
        fetcher: ProviderHistoryFetcher,
    ) -> Optional[dict]:
        """Observed movement for one entity in one window, or ``None``.

        ``None`` means the analyzer cannot answer (unknown entity, missing
        timestamp, provider failure). The caller turns that into an explicit
        UNAVAILABLE response — never a zero.
        """
        published = to_naive_utc(published_at)
        if published is None:
            return None
        if entity_type == "FORECAST":
            return None

        symbol, resolved_type = resolve_entity(entity, entity_type)
        if not symbol:
            return None

        window_minutes = self.window_minutes.get(observation_window, 60)
        interval = (self.settings.window_intervals or {}).get(observation_window, "5m")

        # A one-day pad absorbs weekends/holidays and the provider's own
        # timezone handling; the analysis then filters to the real window.
        start_date = (published - timedelta(minutes=window_minutes)).date() - timedelta(days=1)
        end_date = (published + timedelta(minutes=window_minutes)).date() + timedelta(days=1)

        bundle = await fetcher.fetch(symbol, start_date, end_date, interval)
        if not bundle.ok:
            logger.debug(
                "impact window unavailable for %s (%s): %s",
                symbol, observation_window, bundle.error or "no bars",
            )
            return None

        window_start = published - timedelta(minutes=window_minutes)
        window_end = published + timedelta(minutes=window_minutes)

        before = [b for b in bundle.bars if window_start <= b.timestamp <= published]
        after = [b for b in bundle.bars if published < b.timestamp <= window_end]
        # Bars strictly before the window feed the trailing-volatility estimate.
        trailing = [b for b in bundle.bars if b.timestamp < window_start]

        min_bars = int(self.settings.min_bars_for_window)
        available = len(before) >= min_bars and len(after) >= min_bars

        price_before = before[-1].close if before else None
        price_after = after[-1].close if after else None

        metrics = self._metrics(
            price_before=price_before,
            price_after=price_after,
            before=before,
            after=after,
            trailing=trailing,
            entity_type=resolved_type,
        )
        magnitude = self._magnitude(metrics.get("price_change_percent"), resolved_type)

        confidence = self._confidence(
            available=available,
            bars_before=len(before),
            bars_after=len(after),
            status=bundle.status,
        )

        series = [
            {"timestamp": b.timestamp.isoformat(), "close": round(b.close, 6), "volume": b.volume}
            for b in bundle.bars
            if window_start <= b.timestamp <= window_end
        ]

        return {
            "entity": entity.strip().upper(),
            "entity_type": resolved_type,
            "provider_symbol": symbol,
            "data_source": bundle.source,
            "news_published_at": published,
            "observation_window": observation_window,
            "observation_started_at": window_start,
            "observation_ended_at": window_end,
            "bars_before": len(before),
            "bars_after": len(after),
            "window_available": available,
            "market_data_before": _point(before[-1]) if before else None,
            "market_data_after": _point(after[-1]) if after else None,
            "series": series,
            **metrics,
            "impact_magnitude": magnitude.value if available else ImpactMagnitude.NONE.value,
            "confidence": confidence,
            "notes": (
                "Price movement observed after publication. Correlation does not imply causation."
                if available
                else (
                    f"Only {len(before)} bar(s) before and {len(after)} bar(s) after publication "
                    f"at {interval} resolution — not enough timestamped data to report a "
                    f"{observation_window} window."
                )
            ),
        }

    # ------------------------------------------------------------------
    # every window for one entity (spec §10)
    # ------------------------------------------------------------------

    async def analyze_all_windows(
        self,
        *,
        published_at: datetime,
        entity: str,
        entity_type: str = "AUTO",
        fetcher: ProviderHistoryFetcher,
        windows: Optional[Iterable[str]] = None,
    ) -> dict:
        """Analyse every configured window and report the unavailable ones."""
        wanted = list(windows or self.observation_windows)
        results = await asyncio.gather(
            *(
                self.analyze_window(
                    published_at=published_at,
                    entity=entity,
                    entity_type=entity_type,
                    observation_window=window,
                    fetcher=fetcher,
                )
                for window in wanted
            ),
            return_exceptions=True,
        )

        available: list[dict] = []
        unavailable: list[str] = []
        for window, result in zip(wanted, results):
            if isinstance(result, BaseException) or result is None:
                unavailable.append(window)
                continue
            if result.get("window_available"):
                available.append(result)
            else:
                unavailable.append(window)

        return {
            "entity": (entity or "").strip().upper(),
            "entity_type": entity_type,
            "news_published_at": to_naive_utc(published_at),
            "windows": available,
            "unavailable_windows": unavailable,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _metrics(
        self,
        *,
        price_before: Optional[float],
        price_after: Optional[float],
        before: list[Bar],
        after: list[Bar],
        trailing: list[Bar],
        entity_type: str,
    ) -> dict:
        if price_before is None or price_after is None or price_before == 0:
            return {
                "price_change": None,
                "price_change_percent": None,
                "volume_change": None,
                "volume_change_percent": None,
                "max_favorable_excursion_percent": None,
                "max_adverse_excursion_percent": None,
                "realized_volatility_percent": None,
                "correlation_score": None,
            }

        price_change = price_after - price_before
        price_change_percent = (price_change / price_before) * 100.0

        volume_before = _sum_volume(before)
        volume_after = _sum_volume(after)
        if volume_before is not None and volume_after is not None:
            volume_change = volume_after - volume_before
            volume_change_percent = (volume_change / volume_before * 100.0) if volume_before else None
        else:
            volume_change = None
            volume_change_percent = None

        after_closes = [b.close for b in after]
        excursions = [((value - price_before) / price_before) * 100.0 for value in after_closes]
        mfe = max(excursions) if excursions else None
        mae = min(excursions) if excursions else None

        realized_vol = _realized_volatility([b.close for b in (before + after)])

        # Abnormal-return score: the observed move in units of the symbol's own
        # trailing return volatility. Falls back to the in-window bars when there
        # is not enough trailing history. Labelled, never called "correlation".
        reference = trailing if len(trailing) >= 5 else before + after
        sigma = _realized_volatility([b.close for b in reference])
        if sigma is None or sigma < _VOLATILITY_FLOOR:
            abnormal = None
        else:
            abnormal = round(price_change_percent / sigma, 4)

        return {
            "price_change": round(price_change, 6),
            "price_change_percent": round(price_change_percent, 6),
            "volume_change": round(volume_change, 4) if volume_change is not None else None,
            "volume_change_percent": round(volume_change_percent, 4) if volume_change_percent is not None else None,
            "max_favorable_excursion_percent": round(mfe, 6) if mfe is not None else None,
            "max_adverse_excursion_percent": round(mae, 6) if mae is not None else None,
            "realized_volatility_percent": round(realized_vol, 6) if realized_vol is not None else None,
            "correlation_score": abnormal,
        }

    def _magnitude(self, change_percent: Optional[float], entity_type: str) -> ImpactMagnitude:
        if change_percent is None:
            return ImpactMagnitude.NONE
        thresholds = self.magnitude_thresholds.get(entity_type) or self.magnitude_thresholds["DEFAULT"]
        magnitude = abs(change_percent)
        for cutoff, label in thresholds:
            if magnitude >= cutoff:
                return ImpactMagnitude(label)
        return ImpactMagnitude.NONE

    @staticmethod
    def _confidence(*, available: bool, bars_before: int, bars_after: int, status: Optional[str]) -> float:
        """Confidence in the observation, from data quantity and quality only."""
        if not available:
            return 0.0
        score = 0.4
        score += min(bars_before, 20) / 20.0 * 0.2
        score += min(bars_after, 20) / 20.0 * 0.2
        if (status or "").upper() == "LIVE":
            score += 0.2
        elif (status or "").upper() in {"RECENT", "CACHED"}:
            score += 0.1
        return round(min(score, 1.0), 4)


def _point(bar: Bar) -> dict:
    return {
        "timestamp": bar.timestamp.isoformat(),
        "close": round(bar.close, 6),
        "volume": bar.volume,
    }


def _sum_volume(bars: list[Bar]) -> Optional[float]:
    values = [b.volume for b in bars if b.volume is not None]
    return sum(values) if values else None


def _realized_volatility(closes: list[float]) -> Optional[float]:
    """Standard deviation of log returns, in percent.

    Not annualised: an observation window is minutes to a day long, and
    annualising a five-minute sample would imply a precision the data does not
    have. The raw percent figure is what is reported.
    """
    if len(closes) < 3:
        return None
    returns = []
    for previous, current in zip(closes, closes[1:]):
        if previous > 0 and current > 0:
            returns.append(math.log(current / previous))
    if len(returns) < 2:
        return None
    try:
        return statistics.pstdev(returns) * 100.0
    except statistics.StatisticsError:
        return None


# ---------------------------------------------------------------------------
# Phase 14 forecast probability movement (spec §8)
# ---------------------------------------------------------------------------

class ProbabilityMovementAnalyzer:
    """Observed probability movement for Phase 14 forecast markets."""

    def __init__(self, settings: Any = None):
        self.settings = settings or breaking_news_settings

    # -- market matching -------------------------------------------------

    @staticmethod
    def match_score(article_text: str, market_text: str) -> float:
        """Cosine similarity of the two token sets — real text, no model needed."""
        left, right = set(tokenize(article_text)), set(tokenize(market_text))
        if not left or not right:
            return 0.0
        shared = left & right
        if not shared:
            return 0.0
        return len(shared) / math.sqrt(len(left) * len(right))

    def match_markets(
        self,
        article_text: str,
        markets: list[dict],
        *,
        threshold: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[tuple[dict, float]]:
        """Rank Phase 14 markets by textual overlap with an article.

        Every candidate is scored against the *market's own* question and
        description; only markets above the configured threshold are returned,
        so an unrelated headline produces no match rather than a random one.
        """
        cutoff = threshold if threshold is not None else self.settings.probability_match_threshold
        top = limit or self.settings.probability_max_markets

        scored: list[tuple[dict, float]] = []
        for market in markets or []:
            text = f"{market.get('title') or ''} {market.get('description') or ''} {market.get('category') or ''}"
            score = self.match_score(article_text, text)
            if score >= cutoff:
                scored.append((market, round(score, 4)))
        scored.sort(key=lambda kv: -kv[1])
        return scored[:top]

    # -- measurement -----------------------------------------------------

    @staticmethod
    def analyze_series(
        series: list[dict],
        *,
        published_at: datetime,
        observation_window: str,
    ) -> Optional[dict]:
        """Before/after probabilities from a real timestamped series.

        Returns ``None`` unless there is a real point at or before publication
        *and* a real point inside the window after it. Notably there is no
        interpolation between points: an absent observation is an absent
        observation.
        """
        published = to_naive_utc(published_at)
        if published is None or not series:
            return None

        window_minutes = WINDOW_MINUTES.get(observation_window, 60)
        window_end = published + timedelta(minutes=window_minutes)

        points: list[tuple[datetime, float]] = []
        for row in series:
            timestamp = parse_datetime(row.get("timestamp") or row.get("t"))
            value = row.get("yesProbability", row.get("p"))
            if timestamp is None or value is None:
                continue
            try:
                points.append((timestamp, float(value)))
            except (TypeError, ValueError):
                continue
        if not points:
            return None
        points.sort(key=lambda p: p[0])

        before = [p for p in points if p[0] <= published]
        after = [p for p in points if published < p[0] <= window_end]
        if not before or not after:
            return None

        probability_before = before[-1][1]
        probability_after = after[-1][1]
        change = probability_after - probability_before
        direction = "UP" if change > 0 else "DOWN" if change < 0 else "FLAT"
        magnitude = (
            ImpactMagnitude.HIGH if abs(change) >= 10
            else ImpactMagnitude.MEDIUM if abs(change) >= 5
            else ImpactMagnitude.LOW if abs(change) >= 2
            else ImpactMagnitude.NONE
        )

        window_start = published - timedelta(minutes=window_minutes)
        window_series = [
            {"timestamp": ts.isoformat(), "yesProbability": round(value, 4)}
            for ts, value in points
            if window_start <= ts <= window_end
        ]

        return {
            "news_published_at": published,
            "observation_window": observation_window,
            "probability_before": round(probability_before, 4),
            "probability_after": round(probability_after, 4),
            "probability_change": round(change, 4),
            "movement_direction": direction,
            "impact_magnitude": magnitude.value,
            "before_at": before[-1][0],
            "after_at": after[-1][0],
            "series": window_series,
            "points_before": len(before),
            "points_after": len(after),
        }

    async def analyze_market(
        self,
        *,
        market: dict,
        published_at: datetime,
        observation_window: str = "1h",
        series: Optional[list[dict]] = None,
        fetch_series: bool = True,
    ) -> Optional[dict]:
        """Full probability-movement record for one matched Phase 14 market."""
        if series is None and fetch_series:
            series = await self._fetch_series(market)
        if not series:
            return None

        analysis = self.analyze_series(
            series, published_at=published_at, observation_window=observation_window
        )
        if analysis is None:
            return None

        sources = market.get("sources") or [{}]
        source = sources[0] if isinstance(sources, list) and sources else {}
        return {
            "market_id": str(market.get("id")),
            "market_name": market.get("title"),
            "market_url": source.get("url"),
            "source_name": source.get("name") or "Forecast market",
            "source_url": source.get("url"),
            **analysis,
            "notes": "Probability movement observed after publication.",
        }

    async def _fetch_series(self, market: dict) -> Optional[list[dict]]:
        """Real traded probability series for a market, or ``None``."""
        from .. import forecast_history

        try:
            payload = await forecast_history.fetch_market_history(market, range_key="1M")
        except Exception as exc:
            logger.debug("probability history unavailable for %s: %s", market.get("id"), exc)
            return None
        if not payload:
            return None
        return payload.get("points") or None

    async def find_and_analyze(
        self,
        *,
        article_text: str,
        published_at: datetime,
        markets: list[dict],
        observation_window: str = "1h",
    ) -> list[dict]:
        """Match an article to markets and measure each match's movement."""
        matched = self.match_markets(article_text, markets)
        if not matched:
            return []

        async def one(market: dict) -> Optional[dict]:
            try:
                return await self.analyze_market(
                    market=market,
                    published_at=published_at,
                    observation_window=observation_window,
                )
            except Exception as exc:
                logger.debug("probability movement failed for %s: %s", market.get("id"), exc)
                return None

        results = await asyncio.gather(*(one(m) for m, _ in matched), return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]


__all__ = [
    "Bar",
    "HistoryBundle",
    "ProviderHistoryFetcher",
    "MarketImpactAnalyzer",
    "ProbabilityMovementAnalyzer",
    "WINDOW_MINUTES",
    "INDEX_SYMBOLS",
    "ASSET_SYMBOLS",
    "DEFAULT_MAGNITUDE_THRESHOLDS",
    "resolve_entity",
]
