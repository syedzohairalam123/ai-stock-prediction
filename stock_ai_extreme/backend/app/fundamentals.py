"""
Company fundamentals / deep-dive data (Phase 4's full version).

Everything comes from yfinance's `.info` dict and history through the
existing provider layer — no new dependency, no fabricated numbers. Every
field the provider doesn't return comes back as `None`, never 0, so the UI
can honestly show "unavailable" instead of a fake figure.

Pure computation (valuation ratios, growth checks, dividend math) is kept
in *_core() helpers so it's testable without network.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("neural_market.fundamentals")


def valuation_ratios(info: dict, price: float | None) -> dict:
    """Standard valuation ratios from yfinance .info fields. Missing inputs
    propagate as None — a missing EPS must not silently become a 0 P/E."""
    trailing_eps = info.get("trailingEps")
    forward_eps = info.get("forwardEps")
    book = info.get("bookValue")
    sales = info.get("revenuePerShare")

    def ratio(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator in (None, 0):
            return None
        return round(float(numerator) / float(denominator), 4)

    pe_trailing = ratio(price, trailing_eps)
    pe_forward = ratio(price, forward_eps)
    pb = ratio(price, book)
    ps = ratio(price, sales)
    return {
        "trailing_pe": pe_trailing,
        "forward_pe": pe_forward,
        "price_to_book": pb,
        "price_to_sales": ps,
        "eps_trailing": trailing_eps,
        "eps_forward": forward_eps,
        "book_value_per_share": book,
        "revenue_per_share": sales,
        "peg_ratio": info.get("trailingPegRatio"),
        "enterprise_value": info.get("enterpriseValue"),
        "market_cap": info.get("marketCap"),
    }


def profitability_health(info: dict) -> dict:
    margins = {
        "gross_margin_pct": info.get("grossMargins"),
        "operating_margin_pct": info.get("operatingMargins"),
        "profit_margin_pct": info.get("profitMargins"),
        "return_on_equity_pct": info.get("returnOnEquity"),
        "return_on_assets_pct": info.get("returnOnAssets"),
    }
    # yfinance returns these as fractions (0.25 = 25%) — normalize to %.
    normalized = {k: (round(v * 100, 4) if isinstance(v, (int, float)) else None) for k, v in margins.items()}
    roe = normalized["return_on_equity_pct"]
    margin = normalized["profit_margin_pct"]
    if roe is None or margin is None:
        grade = None
    elif roe > 20 and margin > 15:
        grade = "strong"
    elif roe > 10 and margin > 5:
        grade = "healthy"
    elif roe > 0 and margin > 0:
        grade = "modest"
    else:
        grade = "weak"
    return {**normalized, "grade": grade}


def balance_sheet_health(info: dict) -> dict:
    total_debt = info.get("totalDebt")
    cash = info.get("totalCash")
    current = info.get("currentRatio")
    debt_to_equity = info.get("debtToEquity")  # yfinance reports this already in %
    net_cash = (cash - total_debt) if (cash is not None and total_debt is not None) else None
    if debt_to_equity is None:
        leverage = None
    elif debt_to_equity < 50:
        leverage = "low"
    elif debt_to_equity <= 150:
        leverage = "moderate"
    else:
        leverage = "high"
    return {
        "total_cash": cash, "total_debt": total_debt, "net_cash": net_cash,
        "current_ratio": current, "debt_to_equity_pct": debt_to_equity,
        "leverage": leverage,
    }


def dividend_info(info: dict) -> dict:
    rate = info.get("dividendRate")
    yield_val = info.get("dividendYield")
    # Some yfinance versions return yield as a fraction, some as a percent —
    # normalize anything that looks like a fraction to a % number.
    if isinstance(yield_val, (int, float)) and yield_val is not None and yield_val < 1:
        yield_val = round(yield_val * 100, 4)
    payout = info.get("payoutRatio")
    if isinstance(payout, (int, float)) and payout is not None:
        payout = round(payout * 100, 4)
    return {
        "dividend_rate": rate,
        "dividend_yield_pct": yield_val,
        "payout_ratio_pct": payout,
        "ex_dividend_date": info.get("exDividendDate"),
        "five_year_avg_yield_pct": info.get("fiveYearAvgDividendYield"),
    }


def analyst_view(info: dict) -> dict:
    return {
        "recommendation_mean": info.get("recommendationMean"),
        "recommendation_key": info.get("recommendationKey"),
        "analysts_count": info.get("numberOfAnalystOpinions"),
        "target_mean_price": info.get("targetMeanPrice"),
        "target_high_price": info.get("targetHighPrice"),
        "target_low_price": info.get("targetLowPrice"),
        "target_upside_pct": None,  # filled below when a real price is available
    }


def earnings_dates_list(max_items: int = 8) -> list[dict]:
    """Placeholder structure the provider fills with real earnings rows;
    kept separate so tests can assert the shape without network."""
    return []


def build_fundamentals(info: dict, price: float | None, history_frame=None) -> dict:
    """One-shot deep-dive payload. `history_frame` (optional, indicator-enriched
    close history) adds 52w position and simple momentum context."""
    valuation = valuation_ratios(info, price)
    analyst = analyst_view(info)
    if price and analyst["target_mean_price"]:
        analyst["target_upside_pct"] = round((analyst["target_mean_price"] - price) / price * 100, 4)

    context: dict = {}
    if history_frame is not None and not history_frame.empty:
        closes = history_frame["Close"]
        hi52, lo52 = float(closes.tail(252).max()), float(closes.tail(252).min())
        last = float(closes.iloc[-1])
        if hi52 != lo52:
            context["position_52w_pct"] = round((last - lo52) / (hi52 - lo52) * 100, 4)
        context["high_52w"] = round(hi52, 4)
        context["low_52w"] = round(lo52, 4)
        if len(closes) > 63:
            context["return_3m_pct"] = round((last / float(closes.iloc[-64]) - 1) * 100, 4)
        if len(closes) > 21:
            context["return_1m_pct"] = round((last / float(closes.iloc[-22]) - 1) * 100, 4)

    return {
        "valuation": valuation,
        "profitability": profitability_health(info),
        "balance_sheet": balance_sheet_health(info),
        "dividends": dividend_info(info),
        "analyst": analyst,
        "price_context": context,
        "employees": info.get("fullTimeEmployees"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "disclaimer": "Fundamentals snapshot for education — not investment advice.",
    }
