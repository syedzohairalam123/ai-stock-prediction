"""Phase 23B — offline engine tests for direction + market-cap logic (spec §18).

Everything here is deterministic and offline: no network, no database. Each
rule from spec §3, §4, §6, §10, §11, §12, §13 is asserted directly on the pure
functions so a regression cannot hide behind a live-provider call.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.market_intel.companies import (
    CompanyDefinition,
    CompanyMarketData,
    METHOD_COMPUTED,
    METHOD_PROVIDER,
    QUALITY_ESTIMATED,
    QUALITY_UNAVAILABLE,
    QUALITY_VERIFIED,
    build_company_market_data,
    compute_market_cap,
    get_company,
    market_cap_race,
    rank_companies,
    scenario_market_cap,
    split_adjusted_price,
    split_adjusted_shares,
)
from app.market_intel.direction import (
    INSTRUMENTS,
    align_instruments,
    build_daily_observations,
    classify_direction,
    compute_direction_statistics,
    compute_rolling,
    latest_session,
    resolve_instrument,
)


def _rows(*pairs):
    """(ISO date, close) pairs → provider-style rows."""
    return [{"date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1_000_000} for day, close in pairs]


# ---------------------------------------------------------------------------
# §2 — SPX index vs SPY ETF must stay distinct
# ---------------------------------------------------------------------------


class TestInstruments:
    def test_spx_and_spy_are_separate_instruments(self):
        spx = INSTRUMENTS["spx"]
        spy = INSTRUMENTS["spy"]
        assert spx.symbol == "^GSPC" and spx.kind == "INDEX"
        assert spy.symbol == "SPY" and spy.kind == "ETF"
        assert spx.symbol != spy.symbol
        assert spx.as_dict()["is_index"] is True
        assert spy.as_dict()["is_index"] is False

    def test_resolve_instrument_aliases(self):
        assert resolve_instrument("^GSPC").key == "spx"
        assert resolve_instrument("SPY").key == "spy"
        assert resolve_instrument("spy.us").key == "spy"
        assert resolve_instrument("nonsense") is None


# ---------------------------------------------------------------------------
# §3 — daily return and previous *trading-session* close
# ---------------------------------------------------------------------------


class TestDirectionEngine:
    def test_daily_return_is_close_over_previous_close(self):
        observations = build_daily_observations(
            _rows(("2026-01-02", 100.0), ("2026-01-05", 105.0)), INSTRUMENTS["spx"], source="test"
        )
        assert observations[0].return_pct is None          # no prior session
        assert observations[0].direction is None
        assert observations[1].previous_close == 100.0
        assert round(observations[1].return_pct, 6) == 0.05
        assert observations[1].direction == "UP"

    def test_previous_close_is_previous_trading_session_not_calendar_day(self):
        # Friday → Monday: the gap is 3 calendar days but the previous trading
        # session is Friday's close, so the return is vs Friday, not vs nothing.
        observations = build_daily_observations(
            _rows(("2026-01-02", 100.0), ("2026-01-05", 102.0)), INSTRUMENTS["spy"], source="t"
        )
        assert observations[1].previous_close == 100.0
        assert round(observations[1].return_pct, 6) == 0.02

    def test_holiday_gap_still_uses_last_available_session(self):
        # Monday is a holiday and simply absent; Tuesday measures vs Friday.
        observations = build_daily_observations(
            _rows(("2026-01-02", 100.0), ("2026-01-06", 98.0)), INSTRUMENTS["spx"], source="t"
        )
        assert observations[1].trading_date == date(2026, 1, 6)
        assert observations[1].previous_close == 100.0
        assert round(observations[1].return_pct, 6) == -0.02
        assert observations[1].direction == "DOWN"

    def test_flat_at_source_precision(self):
        assert classify_direction(0.0, 2) == "FLAT"
        assert classify_direction(0.004, 2) == "FLAT"     # rounds to 0.00 at 2dp
        assert classify_direction(0.01, 2) == "UP"
        assert classify_direction(-0.01, 2) == "DOWN"

    def test_missing_session_is_absent_not_zero_return(self):
        rows = _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0), ("2026-01-07", 103.0))
        observations = build_daily_observations(rows, INSTRUMENTS["spx"], source="t")
        # 2026-01-06 was never observed: it must not appear at all (not a 0% day).
        assert [o.trading_date.isoformat() for o in observations] == [
            "2026-01-02",
            "2026-01-05",
            "2026-01-07",
        ]
        # 2026-01-07 is measured against 2026-01-05 (the previous real session).
        assert observations[2].previous_close == 101.0

    def test_correction_keeps_last_row_for_a_date(self):
        rows = _rows(("2026-01-02", 100.0), ("2026-01-05", 999.0), ("2026-01-05", 101.0))
        observations = build_daily_observations(rows, INSTRUMENTS["spx"], source="t")
        assert len(observations) == 2
        assert observations[1].close == 101.0

    def test_rows_missing_a_close_are_dropped_not_zero_filled(self):
        rows = [
            {"date": "2026-01-02", "close": 100.0},
            {"date": "2026-01-05", "close": None},
            {"date": "2026-01-06", "close": 102.0},
        ]
        observations = build_daily_observations(rows, INSTRUMENTS["spx"], source="t")
        assert [o.trading_date.isoformat() for o in observations] == ["2026-01-02", "2026-01-06"]
        assert observations[1].previous_close == 100.0


# ---------------------------------------------------------------------------
# §4 — historical statistics + rolling analytics
# ---------------------------------------------------------------------------


class TestStatistics:
    def test_counts_frequencies_and_period(self):
        observations = build_daily_observations(
            _rows(("2026-01-02", 100.0), ("2026-01-05", 105.0), ("2026-01-06", 102.25)),
            INSTRUMENTS["spx"],
            source="t",
        )
        stats = compute_direction_statistics(observations)
        assert stats.sample_size == 2
        assert stats.up_days == 1 and stats.down_days == 1 and stats.flat_days == 0
        assert stats.up_frequency == 0.5 and stats.down_frequency == 0.5
        assert round(stats.avg_up_return_pct, 6) == 5.0
        assert round(stats.avg_down_return_pct, 6) == -2.619048
        assert round(stats.max_gain_pct, 6) == 5.0
        assert round(stats.max_decline_pct, 6) == -2.619048
        assert stats.period_start == "2026-01-02"
        assert stats.period_end == "2026-01-06"

    def test_statistics_are_empty_not_hardcoded_when_no_data(self):
        stats = compute_direction_statistics([])
        assert stats.sample_size == 0
        assert stats.up_frequency is None and stats.avg_up_return_pct is None

    def test_rolling_return_uses_close_before_the_window(self):
        closes = [100.0, 105.0, 102.25]
        observations = build_daily_observations(
            _rows(*[(f"2026-01-{d:02d}", c) for d, c in zip((2, 5, 6), closes)]),
            INSTRUMENTS["spx"],
            source="t",
        )
        points = compute_rolling(observations, window=2)
        assert len(points) == 3
        assert points[0].rolling_return_pct is None       # not enough history yet
        assert points[1].rolling_return_pct is None       # needs 2 prior sessions
        # close[2]/close[0] - 1 = 102.25/100 - 1 (a genuine 2-session return)
        assert round(points[2].rolling_return_pct, 6) == 2.25
        # Two returns now exist in the window → a real annualised volatility.
        assert points[2].rolling_volatility_pct is not None
        assert points[2].rolling_volatility_pct > 0


# ---------------------------------------------------------------------------
# §5, §6 — latest session labelling and alignment
# ---------------------------------------------------------------------------


class TestLatestAndAlignment:
    def test_latest_session_is_labelled_as_a_close(self):
        observations = build_daily_observations(
            _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0)), INSTRUMENTS["spx"], source="t"
        )
        payload = latest_session(observations)
        assert payload["quote_basis"] == "LAST_SESSION_CLOSE"
        assert payload["is_latest_available_session"] is True
        assert "not a live intraday quote" in payload["note"]

    def test_alignment_never_treats_missing_as_zero(self):
        spx = build_daily_observations(
            _rows(("2026-01-02", 100.0), ("2026-01-05", 101.0)), INSTRUMENTS["spx"], source="t"
        )
        spy = build_daily_observations(
            _rows(("2026-01-02", 500.0), ("2026-01-06", 505.0)), INSTRUMENTS["spy"], source="t"
        )
        aligned = align_instruments(spx, spy, "spx", "spy")
        by_date = {row["trading_date"]: row for row in aligned}
        assert by_date["2026-01-05"]["spy_close"] is None
        assert by_date["2026-01-06"]["spx_close"] is None
        assert by_date["2026-01-02"]["both_available"] is True
        assert by_date["2026-01-05"]["both_available"] is False


# ---------------------------------------------------------------------------
# §9, §10 — company market-cap data + calculation
# ---------------------------------------------------------------------------


class TestMarketCapCalculation:
    def test_market_cap_is_price_times_shares(self):
        assert compute_market_cap(100.0, 1_000.0) == 100_000.0

    def test_missing_or_nonpositive_inputs_return_none(self):
        assert compute_market_cap(None, 100.0) is None
        assert compute_market_cap(100.0, None) is None
        assert compute_market_cap(0.0, 100.0) is None
        assert compute_market_cap(100.0, -5.0) is None

    def test_provider_reported_cap_is_retained_verbatim(self):
        definition = CompanyDefinition("apple", "Apple Inc.", "AAPL", "Information Technology")
        record = build_company_market_data(
            definition,
            {"marketCap": 3_000_000_000_000, "currentPrice": 200.0, "sharesOutstanding": 1.0,
             "regularMarketTime": int(datetime.now(timezone.utc).timestamp()), "source": "yfinance"},
            source="yfinance",
        )
        assert record.market_cap == 3_000_000_000_000
        assert record.market_cap_methodology == METHOD_PROVIDER
        assert record.data_quality == QUALITY_VERIFIED

    def test_computed_cap_is_marked_estimated(self):
        definition = CompanyDefinition("apple", "Apple Inc.", "AAPL", "Information Technology")
        record = build_company_market_data(
            definition,
            {"currentPrice": 200.0, "sharesOutstanding": 15_000_000_000,
             "regularMarketTime": int(datetime.now(timezone.utc).timestamp())},
            source="yfinance",
        )
        assert record.market_cap == 3_000_000_000_000
        assert record.market_cap_methodology == METHOD_COMPUTED
        assert record.data_quality == QUALITY_ESTIMATED
        assert "not an officially reported figure" in (record.note or "")

    def test_multi_class_issuer_flags_the_limitation(self):
        definition = CompanyDefinition(
            "alphabet", "Alphabet Inc.", "GOOGL", "Communication Services", additional_tickers=("GOOG",)
        )
        record = build_company_market_data(
            definition,
            {"currentPrice": 200.0, "sharesOutstanding": 1_000_000_000,
             "regularMarketTime": int(datetime.now(timezone.utc).timestamp())},
            source="yfinance",
        )
        assert "multiple share classes" in (record.note or "")

    def test_missing_inputs_never_become_a_zero_cap(self):
        definition = CompanyDefinition("apple", "Apple Inc.", "AAPL", "Information Technology")
        record = build_company_market_data(definition, {}, source="yfinance")
        assert record.market_cap is None
        assert record.data_quality == QUALITY_UNAVAILABLE

    def test_split_restatement_preserves_market_cap(self):
        # 2:1 split: price halves, shares double → the cap is unchanged, which is
        # the whole point of handling splits (spec §10).
        before = compute_market_cap(200.0, 1_000.0)
        after = compute_market_cap(
            split_adjusted_price(200.0, 2.0), split_adjusted_shares(1_000.0, 2.0)
        )
        assert after == before

    def test_get_company_resolves_id_and_ticker(self):
        assert get_company("nvidia").company_id == "nvidia"
        assert get_company("NVDA").company_id == "nvidia"
        assert get_company("nope") is None


# ---------------------------------------------------------------------------
# §11, §12, §13 — ranking, race, scenario
# ---------------------------------------------------------------------------


def _record(company_id: str, cap: float | None, ticker: str | None = None) -> CompanyMarketData:
    return CompanyMarketData(
        company_id=company_id,
        name=company_id.title(),
        ticker=ticker or company_id[:4].upper(),
        exchange="NASDAQ",
        sector="Information Technology",
        price=1.0,
        currency="USD",
        shares_outstanding=1.0,
        market_cap=cap,
        observation_timestamp=datetime.now(timezone.utc),
        price_source="test",
        shares_source="test",
        data_quality=QUALITY_ESTIMATED if cap is not None else QUALITY_UNAVAILABLE,
    )


class TestRanking:
    def test_ranks_are_computed_from_records_not_hardcoded(self):
        records = rank_companies([_record("a", 100.0), _record("b", 300.0), _record("c", 200.0)])
        ranks = {r.company_id: r.rank for r in records}
        assert ranks == {"b": 1, "c": 2, "a": 3}

    def test_rank_change_positive_means_moved_up(self):
        records = rank_companies(
            [_record("a", 500.0), _record("b", 100.0)],
            previous_ranks={"a": 3, "b": 1},
        )
        changes = {r.company_id: r.rank_change for r in records}
        assert changes["a"] == 2      # moved from 3rd to 1st
        assert changes["b"] == -1     # dropped from 1st to 2nd

    def test_uncapped_company_is_unranked_never_given_a_fake_cap(self):
        records = rank_companies([_record("a", 100.0), _record("b", None)])
        by_id = {r.company_id: r for r in records}
        assert by_id["b"].rank is None
        assert by_id["b"].market_cap is None
        assert by_id["a"].rank == 1

    def test_market_cap_change_tracked_against_previous(self):
        records = rank_companies([_record("a", 150.0)], previous_caps={"a": 100.0})
        assert records[0].market_cap_change == 50.0
        assert records[0].market_cap_change_pct == 50.0


class TestScenario:
    def test_scenario_arithmetic(self):
        result = scenario_market_cap(100.0, 1_000.0, 0.10)
        assert result["scenario_price"] == 110.0
        assert result["scenario_market_cap"] == 110_000.0
        assert result["label"] == "HYPOTHETICAL_SCENARIO"
        assert "not a prediction" in result["note"]

    def test_scenario_negative_return(self):
        result = scenario_market_cap(100.0, 1_000.0, -0.25)
        assert result["scenario_price"] == 75.0
        assert result["scenario_market_cap"] == 75_000.0

    def test_scenario_without_reference_price_returns_none(self):
        result = scenario_market_cap(None, 1_000.0, 0.1)
        assert result["scenario_price"] is None
        assert result["scenario_market_cap"] is None

    def test_race_is_descriptive_and_has_no_probability(self):
        race = market_cap_race([_record("a", 200.0)], {"a": [{"market_cap": 100.0, "rank": 2}]})
        assert race["rows"][0]["market_cap_change"] == 100.0
        assert "probability" in race["note"]
        assert "chance" not in str(race).lower()
