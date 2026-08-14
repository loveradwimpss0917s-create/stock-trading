"""The tests that matter most here are the execution-timing ones.

A backtester that books signal[D] against return[D] produces beautiful,
completely fake equity curves, and nothing downstream (DSR, PBO) can detect
it — the statistics are fine, the data generating process is a lie. So the
next-open rule is asserted directly rather than assumed.
"""
from dataclasses import dataclass

from pipeline_py.backtest.costs import CostModel
from pipeline_py.backtest.engine import Bar, FeatureRow, run_backtest

CAL = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]

NO_COSTS = CostModel(commission_rate=0.0, min_slippage_rate=0.0, atr_slippage_fraction=0.0)


def bars_from_closes(code: str, closes: list[float], opens: list[float] | None = None):
    opens = opens or closes
    return {
        code: {
            d: Bar(date=d, open=opens[i], high=max(opens[i], closes[i]), low=min(opens[i], closes[i]), close=closes[i])
            for i, d in enumerate(CAL)
        }
    }


def features_all(code: str, value: float, key: str = "ret_5d"):
    return {code: {d: FeatureRow(code=code, date=d, values={key: value}) for d in CAL}}


@dataclass
class AlwaysLong:
    code: str
    name: str = "always_long"

    def target_weights(self, asof, features):
        return {self.code: 1.0}


@dataclass
class RecordingStrategy:
    """Captures the dates it was asked about, to prove what it could see."""

    name: str = "recording"

    def __post_init__(self):
        self.seen: list[str] = []

    def target_weights(self, asof, features):
        self.seen.append(asof)
        return {}


class TestExecutionTiming:
    def test_position_is_filled_at_the_next_sessions_open_not_todays_close(self):
        # Decide on day 0; the fill must be day 1's open (110), so the day-1
        # jump from 100 to 110 must NOT be earned.
        bars = bars_from_closes("A", [100, 110, 121, 121, 121], opens=[100, 110, 121, 121, 121])
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        # Day 1 return must be 0 (not yet holding), day 2 earns 110 -> 121.
        assert abs(result.returns[1] - 0.0) < 1e-12
        assert abs(result.returns[2] - 0.1) < 1e-12

    def test_a_signal_cannot_capture_the_move_that_produced_it(self):
        # Price spikes on day 1. A strategy deciding on day 1 fills on day 2,
        # so it cannot book day 1's spike.
        bars = bars_from_closes("A", [100, 200, 200, 200, 200])
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert sum(result.returns) < 0.5  # nowhere near the 100% day-1 move

    def test_strategy_is_only_asked_about_dates_in_the_calendar(self):
        strat = RecordingStrategy()
        bars = bars_from_closes("A", [100] * 5)
        run_backtest(strat, bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=1)
        assert all(d in CAL for d in strat.seen)
        # The last date can't produce a fill (no next session), so no decision
        # is wasted there.
        assert strat.seen[-1] != CAL[-1]

    def test_strategy_never_sees_a_feature_row_dated_after_asof(self):
        seen_dates: list[tuple[str, str]] = []

        @dataclass
        class Inspector:
            name: str = "inspector"

            def target_weights(self, asof, features):
                for row in features.values():
                    seen_dates.append((asof, row.date))
                return {}

        bars = bars_from_closes("A", [100] * 5)
        run_backtest(
            Inspector(), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=1
        )
        assert seen_dates
        for asof, row_date in seen_dates:
            assert row_date <= asof


class TestReturnsAndCosts:
    def test_flat_prices_produce_flat_equity(self):
        bars = bars_from_closes("A", [100] * 5)
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert all(abs(r) < 1e-12 for r in result.returns)
        assert abs(result.equity[-1] - 1.0) < 1e-12

    def test_slippage_makes_a_round_trip_lose_money_on_flat_prices(self):
        bars = bars_from_closes("A", [100] * 5)
        costly = CostModel(commission_rate=0.0, min_slippage_rate=0.01, atr_slippage_fraction=0.0)
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=costly, rebalance_every=99
        )
        # Entry fills above and the final exit fills below, so a flat market
        # still costs the spread.
        assert result.trades
        assert result.trades[0].pnl < 0

    def test_short_position_profits_when_price_falls(self):
        @dataclass
        class AlwaysShort:
            name: str = "always_short"

            def target_weights(self, asof, features):
                return {"A": -1.0}

        bars = bars_from_closes("A", [100, 100, 90, 90, 90])
        result = run_backtest(
            AlwaysShort(), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert sum(result.returns) > 0

    def test_trades_are_closed_out_at_the_end_so_pnl_is_realized(self):
        bars = bars_from_closes("A", [100, 100, 100, 100, 120])
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert len(result.trades) == 1
        assert result.trades[0].exit_date == CAL[-1]
        assert result.trades[0].pnl is not None


def compounded(returns):
    total = 1.0
    for r in returns:
        total *= 1 + r
    return total - 1


def compounded_trades(trades):
    """Sequential single-name trades compound, they don't sum — each trade's
    pnl is a simple return over its own holding period."""
    total = 1.0
    for t in trades:
        total *= 1 + (t.pnl or 0.0)
    return total - 1


class TestAccountingConsistency:
    """The daily return series and the trade list must describe the same book.

    They diverged in the first version: fills were executed *after* the mark
    step, so an entry day's open->close move was missing from the returns but
    present in trade PnL. Live, that showed up as annualized Sharpe 1.07
    alongside a profit factor of 0.82 — a combination that cannot happen if
    both are measuring the same positions.

    Compared by compounding, not summing: the equity curve multiplies daily
    returns while a trade's pnl is a simple return over its holding period.
    """

    def test_single_trade_pnl_matches_the_compounded_daily_returns(self):
        bars = bars_from_closes("A", [100, 105, 110, 115, 120], opens=[100, 102, 108, 112, 118])
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert abs(compounded(result.returns) - compounded_trades(result.trades)) < 1e-9

    def test_holds_with_a_gap_between_close_and_next_open_still_reconcile(self):
        # Overnight gaps are where an off-by-one in the marking base shows up.
        bars = bars_from_closes("A", [100, 90, 130, 95, 140], opens=[100, 120, 80, 125, 85])
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert abs(compounded(result.returns) - compounded_trades(result.trades)) < 1e-9

    def test_reconciles_when_positions_are_rolled_every_session(self):
        bars = bars_from_closes("A", [100, 103, 99, 107, 111], opens=[100, 101, 104, 98, 109])
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=1
        )
        assert abs(compounded(result.returns) - compounded_trades(result.trades)) < 1e-9

    def test_short_daily_series_and_trade_pnl_agree_in_sign_but_not_magnitude(self):
        """Shorts genuinely cannot reconcile exactly, and that is not a bug.

        The daily series is a constant-weight short (rebalanced each session);
        trade pnl is the simple return on the initial notional. Take 100 ->
        200 -> 100: the simple short return is 0%, while the daily-compounded
        one is -100% — the position is wiped out on the way up and never gets
        it back. The daily series is the honest equity path, so it stays the
        basis for Sharpe/DSR; trade pnl remains a per-position figure.
        """

        @dataclass
        class AlwaysShort:
            name: str = "always_short"

            def target_weights(self, asof, features):
                return {"A": -1.0}

        bars = bars_from_closes("A", [100, 95, 105, 90, 85], opens=[100, 97, 102, 92, 88])
        result = run_backtest(
            AlwaysShort(), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        # A falling price must profit the short on both measures.
        assert compounded(result.returns) > 0
        assert compounded_trades(result.trades) > 0

    def test_short_compounding_penalises_a_round_trip_that_looks_flat(self):
        # The case that proves the two bases differ on purpose.
        bars = bars_from_closes("A", [100, 200, 100, 100, 100], opens=[100, 100, 200, 100, 100])

        @dataclass
        class AlwaysShort:
            name: str = "always_short"

            def target_weights(self, asof, features):
                return {"A": -1.0}

        result = run_backtest(
            AlwaysShort(), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        # Price ends where the short was opened, yet the equity path is down.
        assert compounded(result.returns) < -0.4

    def test_slippage_cost_appears_in_both_the_returns_and_the_trade(self):
        bars = bars_from_closes("A", [100] * 5)
        costly = CostModel(commission_rate=0.0, min_slippage_rate=0.01, atr_slippage_fraction=0.0)
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=costly, rebalance_every=99
        )
        assert compounded(result.returns) < 0
        assert abs(compounded(result.returns) - compounded_trades(result.trades)) < 1e-9


class TestMissingData:
    def test_a_code_with_no_bar_on_the_fill_date_is_skipped_not_crashed(self):
        bars = bars_from_closes("A", [100] * 5)
        del bars["A"][CAL[1]]  # no bar on the fill date
        result = run_backtest(
            AlwaysLong("A"), bars, features_all("A", 0.0), CAL, cost_model=NO_COSTS, rebalance_every=99
        )
        assert isinstance(result.returns, list)

    def test_empty_universe_produces_an_empty_but_valid_result(self):
        @dataclass
        class NoOp:
            name: str = "noop"

            def target_weights(self, asof, features):
                return {}

        result = run_backtest(NoOp(), {}, {}, CAL, cost_model=NO_COSTS)
        assert result.metrics.n_trades == 0
        assert all(r == 0.0 for r in result.returns)
