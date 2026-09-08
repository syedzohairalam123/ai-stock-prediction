"""
Analytical ranking screener — the honest version of "which coin/stock should
I invest in". Produces a RANKED TABLE of real, computed factors (momentum,
trend strength, volatility, risk) for a list of tickers, explicitly labeled
"analytical ranking, not investment advice".

Everything is computed from the same indicator-enriched history the
prediction engine already uses, through the existing provider manager —
one bad ticker degrades to an error row instead of failing the scan.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from .indicators import add_indicators


def _safe_pct(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(value, 4)


def score_frame(df: pd.DataFrame) -> dict:
    """Factor scores for ONE ticker's enriched history. All real math on the
    actual rows — momentum from closes, trend from SMA/ADX, vol from returns."""
    closes = df["Close"]
    last = float(closes.iloc[-1])
    returns = closes.pct_change()

    def ret_over(n: int) -> float | None:
        if len(closes) <= n:
            return None
        base = float(closes.iloc[-1 - n])
        return (last - base) / base * 100 if base else None

    momentum_1m = ret_over(21)
    momentum_3m = ret_over(63)
    sma_30 = float(df["sma_30"].iloc[-1]) if "sma_30" in df.columns and pd.notna(df["sma_30"].iloc[-1]) else None
    adx = float(df["adx_14"].iloc[-1]) if "adx_14" in df.columns and pd.notna(df["adx_14"].iloc[-1]) else None
    rsi = float(df["rsi_14"].iloc[-1]) if "rsi_14" in df.columns and pd.notna(df["rsi_14"].iloc[-1]) else None
    vol_30d = _safe_pct(float(returns.tail(30).std() * (252 ** 0.5) * 100)) if len(returns.dropna()) >= 10 else None

    trend = 0.0
    if sma_30 is not None and last:
        trend += (last / sma_30 - 1) * 100  # % above/below its own 30d mean
    if adx is not None:
        trend += max(0.0, adx - 20) * (1 if (sma_30 is not None and last > sma_30) else -1)

    return {
        "last_close": round(last, 4),
        "momentum_1m_pct": _safe_pct(momentum_1m),
        "momentum_3m_pct": _safe_pct(momentum_3m),
        "trend_score": _safe_pct(trend),
        "rsi_14": _safe_pct(rsi),
        "annualized_volatility_pct": vol_30d,
    }


def _composite_rank(rows: list[dict]) -> list[dict]:
    """Deterministic composite: momentum (40%) + trend (30%) + inverse-vol
    (30%), each normalized 0-100 across the scanned set. Ties break by
    momentum. Missing factors contribute their set-average (never 0, which
    would unfairly punish a ticker for one missing field)."""
    if not rows:
        return rows

    def norm(key: str, invert: bool = False) -> dict[str, float]:
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            return {}
        lo, hi = min(vals), max(vals)
        span = hi - lo
        out = {}
        for r in rows:
            v = r[key]
            if v is None:
                continue
            score = (v - lo) / span * 100 if span else 50.0
            out[r["ticker"]] = 100 - score if invert else score
        return out

    m1, m3 = norm("momentum_1m_pct"), norm("momentum_3m_pct")
    tr, vol = norm("trend_score"), norm("annualized_volatility_pct", invert=True)

    def mean(d: dict) -> float:
        return sum(d.values()) / len(d) if d else 0.0

    m1_f, m3_f, tr_f, vol_f = mean(m1), mean(m3), mean(tr), mean(vol)
    for r in rows:
        t = r["ticker"]
        composite = (
            0.25 * (m1.get(t, m1_f)) + 0.15 * (m3.get(t, m3_f))
            + 0.30 * (tr.get(t, tr_f)) + 0.30 * (vol.get(t, vol_f))
        )
        r["composite_score"] = round(composite, 2)
    rows.sort(key=lambda r: (-r["composite_score"], -(r["momentum_1m_pct"] or 0)))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


async def scan(manager, tickers: list[str], lookback_days: int = 365) -> dict:
    """Scan a list of tickers and return a ranked analytical table. Failing
    tickers appear in `unavailable` with the real reason — never silently
    dropped, never given a fake score."""
    if not tickers:
        raise ValueError("Provide at least one ticker to scan.")
    end = date.today()
    start = end - timedelta(days=lookback_days)
    rows: list[dict] = []
    unavailable: dict[str, str] = {}
    for ticker in dict.fromkeys(t.upper() for t in tickers):
        try:
            frame, source, status = await manager.history(ticker, start, end)
            enriched = add_indicators(frame)
            if len(enriched) < 40:
                raise ValueError(f"only {len(enriched)} usable rows after indicator warmup")
            factors = score_frame(enriched)
            # status may be a DataStatus enum (real manager) or a plain string (stubs)
            status_txt = status.value if hasattr(status, "value") else str(status)
            rows.append({"ticker": ticker, **factors, "data_source": source, "data_status": status_txt})
        except Exception as exc:
            unavailable[ticker] = str(exc)
    ranked = _composite_rank(rows)
    return {
        "scanned": len(tickers),
        "ranked": ranked,
        "unavailable": unavailable,
        "methodology": {
            "composite": "momentum 1m (25%) + momentum 3m (15%) + trend (30%) + inverse volatility (30%), min-max normalized across the scanned set",
            "note": "Analytical ranking of real computed factors — NOT investment advice, not a buy/sell recommendation.",
        },
    }
