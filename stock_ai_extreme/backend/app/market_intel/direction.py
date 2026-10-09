"""Phase 23B — Market Direction Engine (spec §2, §3, §4, §6).

Pure and offline-testable: this module receives already-fetched rows and
computes returns, direction, historical statistics and rolling analytics. It
never touches the network or the database, so every rule below is locked down
deterministically in the tests.

Core rule (spec §3): the previous *valid trading-session* close is used, never
the previous calendar date. The provider only returns actual sessions (weekends
and holidays are absent), so the previous row *is* the previous trading session;
this module still de-duplicates corrections and drops unusable rows so a
revision cannot silently turn into a fabricated 0% return.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Instruments (spec §2)
#
# SPX is the index and SPY is the ETF. They are separate instruments with
# separate symbols — an ETF price is NEVER used as an index level, and every
# observation carries which one it is.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Instrument:
    key: str          # "spx" | "spy"
    symbol: str       # provider symbol: "^GSPC" | "SPY"
    name: str
    kind: str         # "INDEX" | "ETF"
    currency: str
    #: decimals the source publishes at; used for the FLAT test (spec §3).
    price_precision: int = 2

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "symbol": self.symbol,
            "name": self.name,
            "kind": self.kind,
            "currency": self.currency,
            "price_precision": self.price_precision,
            "is_index": self.kind == "INDEX",
        }


INSTRUMENTS: dict[str, Instrument] = {
    "spx": Instrument("spx", "^GSPC", "S&P 500 Index", "INDEX", "USD", 2),
    "spy": Instrument("spy", "SPY", "SPDR S&P 500 ETF Trust", "ETF", "USD", 2),
}

#: Yahoo/FRED-style math error sentinel for "not computable from real data".
_ABS_TOL = 1e-9

#: Annualisation factor for daily returns (252 trading sessions).
TRADING_DAYS_PER_YEAR = 252


def resolve_instrument(key: str) -> Optional[Instrument]:
    """Look up an instrument by its API key, symbol or alias (case-insensitive)."""
    if not key:
        return None
    lowered = key.strip().lower()
    if lowered in INSTRUMENTS:
        return INSTRUMENTS[lowered]
    aliases = {
        "^gspc": "spx", "gspc": "spx", "spx": "spx", "s&p500": "spx",
        "sp500": "spx", ".inx": "spx",
        "spy": "spy", "spy.us": "spy", "spdr": "spy",
    }
    resolved = aliases.get(lowered)
    return INSTRUMENTS.get(resolved) if resolved else None


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


@dataclass
class DailyObservation:
    """One real trading session for one instrument (spec §2, §3)."""

    instrument: str                 # "spx" | "spy"
    symbol: str                     # provider symbol
    instrument_kind: str            # INDEX | ETF
    trading_date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    adjusted_close: Optional[float] = None
    previous_close: Optional[float] = None
    absolute_change: Optional[float] = None
    return_pct: Optional[float] = None
    direction: Optional[str] = None  # UP | DOWN | FLAT (None = no prior session)
    source: str = ""
    source_timestamp: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "instrument": self.instrument,
            "symbol": self.symbol,
            "instrument_kind": self.instrument_kind,
            "trading_date": self.trading_date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "adjusted_close": self.adjusted_close,
            "previous_close": self.previous_close,
            "absolute_change": self.absolute_change,
            "return_pct": self.return_pct,
            "direction": self.direction,
            "source": self.source,
            "source_timestamp": (
                self.source_timestamp.isoformat() if self.source_timestamp else None
            ),
        }


def _as_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def classify_direction(change: float, precision: int = 2) -> str:
    """UP / DOWN / FLAT for a price change, at the source's own precision.

    FLAT means the source's published values are equal — not "a very small
    move rounded to zero". The comparison is made after rounding both sides to
    the instrument's published precision, so a 0.004 index move on a
    2-decimal index is genuinely flat while a 0.01 move is not.
    """
    rounded = round(change, precision)
    if rounded > _ABS_TOL:
        return "UP"
    if rounded < -_ABS_TOL:
        return "DOWN"
    return "FLAT"


def build_daily_observations(
    rows: Iterable[dict],
    instrument: Instrument,
    source: str = "",
    source_timestamp: Optional[datetime] = None,
) -> list[DailyObservation]:
    """Normalise raw OHLCV rows into direction observations (spec §3).

    ``rows`` are dicts with ``date``/``open``/``high``/``low``/``close``/
    ``volume``/``adjusted_close``. Rows are sorted by date and de-duplicated
    keeping the LAST occurrence (spec §3 corrections). A session needs a real
    close and a real previous close to carry a return; the first usable session
    therefore keeps ``direction=None`` rather than inventing a move.
    """
    parsed: dict[date, dict] = {}
    for row in rows:
        day = _to_date(row.get("date") or row.get("trading_date") or row.get("Date"))
        close = _as_float(row.get("close", row.get("Close")))
        if day is None or close is None:
            continue
        # A correction arrives as a later row for the same date: last one wins.
        parsed[day] = {
            "open": _as_float(row.get("open", row.get("Open"))),
            "high": _as_float(row.get("high", row.get("High"))),
            "low": _as_float(row.get("low", row.get("Low"))),
            "close": close,
            "volume": _as_float(row.get("volume", row.get("Volume"))),
            "adjusted_close": _as_float(
                row.get("adjusted_close", row.get("Adj Close", row.get("AdjClose")))
            ),
        }

    observations: list[DailyObservation] = []
    previous_close: Optional[float] = None
    for day in sorted(parsed):
        values = parsed[day]
        close = values["close"]
        absolute_change = None
        return_pct = None
        direction = None
        if previous_close is not None and previous_close != 0:
            absolute_change = round(close - previous_close, 6)
            return_pct = (close / previous_close) - 1.0
            direction = classify_direction(close - previous_close, instrument.price_precision)
        observations.append(
            DailyObservation(
                instrument=instrument.key,
                symbol=instrument.symbol,
                instrument_kind=instrument.kind,
                trading_date=day,
                open=values["open"],
                high=values["high"],
                low=values["low"],
                close=close,
                volume=values["volume"],
                adjusted_close=values["adjusted_close"],
                previous_close=previous_close,
                absolute_change=absolute_change,
                return_pct=return_pct,
                direction=direction,
                source=source,
                source_timestamp=source_timestamp,
            )
        )
        previous_close = close
    return observations


# ---------------------------------------------------------------------------
# Historical direction analytics (spec §4)
# ---------------------------------------------------------------------------


@dataclass
class DirectionStatistics:
    instrument: str
    symbol: str
    instrument_kind: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    sample_size: int = 0            # sessions with a computable return
    up_days: int = 0
    down_days: int = 0
    flat_days: int = 0
    up_frequency: Optional[float] = None
    down_frequency: Optional[float] = None
    flat_frequency: Optional[float] = None
    avg_up_return_pct: Optional[float] = None
    avg_down_return_pct: Optional[float] = None
    max_gain_pct: Optional[float] = None
    max_decline_pct: Optional[float] = None
    total_return_pct: Optional[float] = None


def compute_direction_statistics(
    observations: list[DailyObservation],
) -> DirectionStatistics:
    """Descriptive statistics over the observed sessions (spec §4).

    Every percentage is computed from the observations passed in — nothing is
    hardcoded. ``period_start``/``period_end``/``sample_size`` are always
    present so a consumer can state the observation period and its size.
    """
    instrument = observations[0].instrument if observations else ""
    symbol = observations[0].symbol if observations else ""
    kind = observations[0].instrument_kind if observations else ""
    stats = DirectionStatistics(instrument=instrument, symbol=symbol, instrument_kind=kind)
    if not observations:
        return stats

    stats.period_start = observations[0].trading_date.isoformat()
    stats.period_end = observations[-1].trading_date.isoformat()

    up_returns: list[float] = []
    down_returns: list[float] = []
    for obs in observations:
        if obs.return_pct is None:
            continue
        stats.sample_size += 1
        if obs.direction == "UP":
            stats.up_days += 1
            up_returns.append(obs.return_pct)
        elif obs.direction == "DOWN":
            stats.down_days += 1
            down_returns.append(obs.return_pct)
        else:
            stats.flat_days += 1

    if stats.sample_size:
        stats.up_frequency = round(stats.up_days / stats.sample_size, 6)
        stats.down_frequency = round(stats.down_days / stats.sample_size, 6)
        stats.flat_frequency = round(stats.flat_days / stats.sample_size, 6)
    if up_returns:
        stats.avg_up_return_pct = round(sum(up_returns) / len(up_returns) * 100, 6)
        stats.max_gain_pct = round(max(up_returns) * 100, 6)
    if down_returns:
        stats.avg_down_return_pct = round(sum(down_returns) / len(down_returns) * 100, 6)
        stats.max_decline_pct = round(min(down_returns) * 100, 6)

    first_close = observations[0].close
    last_close = observations[-1].close
    if first_close and first_close != 0 and last_close is not None:
        # Period return uses the close of the session BEFORE the window where
        # one exists, so the first in-window session's move is not dropped.
        base = observations[0].previous_close or first_close
        if base:
            stats.total_return_pct = round((last_close / base - 1.0) * 100, 6)
    return stats


# ---------------------------------------------------------------------------
# Rolling analytics (spec §4, §6)
# ---------------------------------------------------------------------------


@dataclass
class RollingPoint:
    trading_date: str
    rolling_return_pct: Optional[float] = None
    rolling_volatility_pct: Optional[float] = None
    window: int = 0


def compute_rolling(
    observations: list[DailyObservation], window: int = 20
) -> list[RollingPoint]:
    """Rolling compounded return and annualised volatility (spec §4).

    Only real sessions participate; a missing session is a missing row, never a
    zero return (spec §6). A windows' rolling return uses the close that
    precedes the window, so it is a genuine ``window``-session return.
    """
    if window < 2:
        window = 2
    points: list[RollingPoint] = []
    usable = [obs for obs in observations if obs.close is not None]
    if not usable:
        return points

    for index, obs in enumerate(usable):
        # A genuine ``window``-session return is close[t]/close[t-window] - 1, so
        # it needs ``window`` prior sessions to exist. Until then the value is
        # None (a shorter return would be mislabelled as the requested window).
        base_index = index - window
        rolling_return = None
        if base_index >= 0:
            base_row = usable[base_index]
            base = base_row.previous_close
            if base is None:
                base = base_row.close
            if base:
                rolling_return = round((obs.close / base - 1.0) * 100, 6)

        window_returns = [
            row.return_pct
            for row in usable[index - window + 1 : index + 1]
            if row.return_pct is not None
        ]
        volatility = None
        if len(window_returns) >= 2:
            mean = sum(window_returns) / len(window_returns)
            variance = sum((r - mean) ** 2 for r in window_returns) / (len(window_returns) - 1)
            volatility = round(
                math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 6
            )
        points.append(
            RollingPoint(
                trading_date=obs.trading_date.isoformat(),
                rolling_return_pct=rolling_return,
                rolling_volatility_pct=volatility,
                window=window,
            )
        )
    return points


# ---------------------------------------------------------------------------
# Latest-session dashboard payload (spec §5)
# ---------------------------------------------------------------------------


def latest_session(observations: list[DailyObservation]) -> Optional[dict]:
    """The most recent available session, explicitly labelled as a close.

    The market may be closed; the caller must present this as the latest
    available session (a close), never as a live intraday quote (spec §5).
    """
    if not observations:
        return None
    latest = observations[-1]
    payload = latest.as_dict()
    payload["is_latest_available_session"] = True
    payload["quote_basis"] = "LAST_SESSION_CLOSE"
    payload["note"] = (
        "Latest available trading session close — not a live intraday quote."
    )
    return payload


def align_instruments(
    left: list[DailyObservation],
    right: list[DailyObservation],
    left_key: Optional[str] = None,
    right_key: Optional[str] = None,
) -> list[dict]:
    """Session-aligned comparison of two instruments (spec §6).

    The join is on the exact trading date and the column names use each
    instrument's stable key (spx/spy), so a date present in only one series is
    emitted with the other side ``None`` — never a 0% return. The comparison
    therefore cannot manufacture agreement between the two instruments.
    """
    left_key = left_key or (left[0].instrument if left else "left")
    right_key = right_key or (right[0].instrument if right else "right")
    left_by_date = {obs.trading_date: obs for obs in left}
    right_by_date = {obs.trading_date: obs for obs in right}
    aligned = []
    for day in sorted(set(left_by_date) | set(right_by_date)):
        left_obs = left_by_date.get(day)
        right_obs = right_by_date.get(day)
        aligned.append(
            {
                "trading_date": day.isoformat(),
                f"{left_key}_close": left_obs.close if left_obs else None,
                f"{right_key}_close": right_obs.close if right_obs else None,
                f"{left_key}_return_pct": left_obs.return_pct if left_obs else None,
                f"{right_key}_return_pct": right_obs.return_pct if right_obs else None,
                "both_available": left_obs is not None and right_obs is not None,
            }
        )
    return aligned


def dataframe_rows(observations: list[DailyObservation]) -> list[dict]:
    """Flatten observations for the charts (date + return + rolling fields)."""
    return [
        {
            "date": obs.trading_date.isoformat(),
            "close": obs.close,
            "return_pct": obs.return_pct,
            "direction": obs.direction,
        }
        for obs in observations
    ]


# ---------------------------------------------------------------------------
# The named engine (spec §3)
#
# The functions above are the pure implementation; this class is the named
# ``MarketDirectionEngine`` the spec asks for. It is a thin, stateless facade
# over exactly those functions so there is ONE implementation of the return
# rule — the class does not re-derive anything, it simply gives callers an
# object with the spec's method names and keeps a bound instrument.
# ---------------------------------------------------------------------------


class MarketDirectionEngine:
    """Daily direction engine for one instrument (spec §3).

    ``return = (currentClose / previousTradingClose) - 1`` with direction UP
    when the return is positive, DOWN when negative, and FLAT when the source's
    published values are equal at its precision. The previous value is always
    the previous *valid trading-session* close, never the previous calendar
    date: the provider only returns real sessions, so weekends, holidays and
    market closures are simply absent rather than zero-filled.

    The engine is stateless beyond the instrument it is bound to, so the same
    instance can process as many observation batches as needed.
    """

    def __init__(self, instrument: Instrument | str = "spx", source: str = "") -> None:
        resolved = instrument if isinstance(instrument, Instrument) else resolve_instrument(instrument)
        if resolved is None:
            raise ValueError(
                f"Unknown instrument '{instrument}'. Supported: {', '.join(INSTRUMENTS)}."
            )
        self.instrument = resolved
        self.source = source

    # -- core rule (spec §3) -------------------------------------------------
    def build(
        self,
        rows: Iterable[dict],
        source_timestamp: Optional[datetime] = None,
    ) -> list[DailyObservation]:
        """Normalise real provider rows into direction observations."""
        return build_daily_observations(
            rows, self.instrument, source=self.source, source_timestamp=source_timestamp
        )

    def classify(self, change: float) -> str:
        """UP / DOWN / FLAT for a raw price change at the source precision."""
        return classify_direction(change, self.instrument.price_precision)

    def daily_return(self, current_close: float, previous_close: float) -> dict:
        """The spec's single-session return for one pair of real closes.

        Returns the same shape the observation rows carry, so a caller can use
        it for a hand-checked trace without duplicating the formula.
        """
        if previous_close is None or previous_close == 0:
            return {
                "absolute_change": None,
                "return_pct": None,
                "direction": None,
                "reason": "No previous trading-session close is available.",
            }
        change = current_close - previous_close
        return {
            "absolute_change": round(change, 6),
            "return_pct": (current_close / previous_close) - 1.0,
            "direction": self.classify(change),
            "previous_close": previous_close,
        }

    # -- analytics (spec §4, §6) --------------------------------------------
    def statistics(self, observations: list[DailyObservation]) -> DirectionStatistics:
        return compute_direction_statistics(observations)

    def rolling(self, observations: list[DailyObservation], window: int = 20) -> list[RollingPoint]:
        return compute_rolling(observations, window=window)

    def latest(self, observations: list[DailyObservation]) -> Optional[dict]:
        return latest_session(observations)

    def align(
        self,
        own: list[DailyObservation],
        other: list[DailyObservation],
        other_key: Optional[str] = None,
    ) -> list[dict]:
        """Session-align this instrument's series with another instrument.

        Both series are passed explicitly (the bound instrument is the left
        side) so a missing date on either side stays ``None`` — the alignment
        never treats a missing observation as a 0% return.
        """
        return align_instruments(own, other, self.instrument.key, other_key or "other")

    def as_dict(self) -> dict:
        return {
            "engine": "MarketDirectionEngine",
            "instrument": self.instrument.as_dict(),
            "return_formula": "(currentClose / previousTradingClose) - 1",
            "flat_rule": "closes equal at the source's published precision",
            "source": self.source or None,
        }
