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
