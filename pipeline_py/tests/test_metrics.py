import math

from pipeline_py.backtest.metrics import (
    TRADING_DAYS,
    Trade,
    calmar_ratio,
    compute_metrics,
    equity_curve,
    kurtosis,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    skewness,
    sortino_ratio,
)


class TestSharpe:
    def test_matches_hand_computed_value(self):
        # mean 0.01, sample sd 0.01 -> daily SR 1.0 -> annualized sqrt(252)
        returns = [0.0, 0.01, 0.02]
        assert abs(sharpe_ratio(returns, annualize=False) - 1.0) < 1e-12
        assert abs(sharpe_ratio(returns) - math.sqrt(TRADING_DAYS)) < 1e-9

    def test_zero_variance_returns_zero_not_infinity(self):
        assert sharpe_ratio([0.01] * 10) == 0.0

    def test_annualization_is_exactly_sqrt_252(self):
        returns = [0.001, -0.002, 0.003, 0.0005, -0.001]
        daily = sharpe_ratio(returns, annualize=False)
        assert abs(sharpe_ratio(returns) - daily * math.sqrt(252)) < 1e-12


class TestSortino:
    def test_no_losing_days_gives_zero_downside_hence_zero(self):
        assert sortino_ratio([0.01, 0.02, 0.03]) == 0.0

    def test_downside_deviation_uses_full_sample_length(self):
        # returns: +0.02, -0.01, +0.02, -0.01 -> mean 0.005
        # downside sq = (0 + 0.0001 + 0 + 0.0001)/4 = 0.00005 -> dd = 0.0070710678
        returns = [0.02, -0.01, 0.02, -0.01]
        expected_daily = 0.005 / math.sqrt(0.00005)
        assert abs(sortino_ratio(returns, annualize=False) - expected_daily) < 1e-9


class TestEquityAndDrawdown:
    def test_equity_curve_compounds(self):
        eq = equity_curve([0.1, -0.1])
        assert abs(eq[1] - 1.1) < 1e-12
        assert abs(eq[2] - 0.99) < 1e-12

    def test_max_drawdown_is_peak_to_trough_fraction(self):
        # peak 1.5 -> trough 0.75 == 50% drawdown
        assert abs(max_drawdown([1.0, 1.5, 0.75, 1.2]) - 0.5) < 1e-12

    def test_monotonic_rise_has_no_drawdown(self):
        assert max_drawdown([1.0, 1.1, 1.2]) == 0.0

    def test_calmar_is_zero_when_there_is_no_drawdown(self):
        assert calmar_ratio([1.0, 1.1, 1.2], 3) == 0.0


class TestProfitFactor:
    def test_gross_gains_over_gross_losses(self):
        assert abs(profit_factor([2.0, -1.0, 3.0, -1.0]) - 2.5) < 1e-12

    def test_all_wins_is_infinite(self):
        assert profit_factor([1.0, 2.0]) == float("inf")

    def test_no_trades_is_zero_not_a_crash(self):
        assert profit_factor([]) == 0.0


class TestMoments:
    def test_symmetric_sample_has_zero_skew(self):
        assert abs(skewness([-2, -1, 0, 1, 2])) < 1e-12

    def test_right_tail_produces_positive_skew(self):
        assert skewness([0, 0, 0, 0, 10]) > 0

    def test_kurtosis_is_non_excess_so_normal_is_about_three(self):
        # A large symmetric sample should sit near 3, not near 0. The DSR
        # formula subtracts 1 from this term and only lines up with the
        # published derivation for the raw fourth moment.
        xs = [-3, -2, -2, -1, -1, -1, 0, 0, 0, 0, 1, 1, 1, 2, 2, 3]
        assert 2.0 < kurtosis(xs) < 4.0


class TestComputeMetrics:
    def test_aggregates_trade_and_return_statistics(self):
        trades = [
            Trade("7203", "2026-01-05", "2026-01-09", 100, 110, 0.2, "long", pnl=0.02, holding_days=4),
            Trade("6758", "2026-01-05", "2026-01-09", 100, 95, 0.2, "long", pnl=-0.01, holding_days=4),
        ]
        m = compute_metrics([0.01, -0.005, 0.002], trades, turnover=1.5)
        assert m.n_trades == 2
        assert abs(m.win_rate - 0.5) < 1e-12
        assert abs(m.expectancy - 0.005) < 1e-12
        assert abs(m.avg_holding_days - 4) < 1e-12
        assert m.turnover == 1.5
        assert m.n_periods == 3
        # The daily figure is what DSR/PBO must consume; both are reported.
        assert abs(m.sharpe - m.sharpe_daily * math.sqrt(252)) < 1e-9

    def test_empty_backtest_does_not_crash(self):
        m = compute_metrics([], [], 0.0)
        assert m.n_trades == 0
        assert m.sharpe == 0.0
        assert m.max_drawdown == 0.0
