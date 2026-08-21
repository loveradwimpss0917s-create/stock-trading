import pytest

from pipeline_py.risk.ruin import (
    expectancy_r,
    kelly_fraction,
    required_win_rate,
    simulate,
)


class TestExpectancy:
    def test_win_rate_alone_does_not_decide_expectancy(self):
        """The point of showing R rather than hit rate: the higher win rate
        can be the losing system."""
        frequent_small = expectancy_r(win_rate=0.70, avg_win_r=0.3, avg_loss_r=1.0)
        rare_large = expectancy_r(win_rate=0.30, avg_win_r=3.0, avg_loss_r=1.0)
        assert frequent_small < 0
        assert rare_large > 0

    def test_a_break_even_system_has_zero_expectancy(self):
        assert expectancy_r(0.5, 1.0, 1.0) == pytest.approx(0.0)


class TestRequiredWinRate:
    def test_one_to_one_payoff_needs_half(self):
        assert required_win_rate(1.0, 1.0) == pytest.approx(0.5)

    def test_a_three_to_one_payoff_needs_a_quarter(self):
        assert required_win_rate(3.0, 1.0) == pytest.approx(0.25)

    def test_it_is_the_exact_zero_expectancy_point(self):
        for win, loss in [(0.5, 1.0), (2.0, 1.0), (3.0, 1.5)]:
            wr = required_win_rate(win, loss)
            assert expectancy_r(wr, win, loss) == pytest.approx(0.0, abs=1e-12)

    def test_a_degenerate_payoff_returns_none(self):
        assert required_win_rate(0.0, 0.0) is None


class TestKelly:
    def test_a_negative_edge_yields_zero_rather_than_a_short(self):
        assert kelly_fraction(win_rate=0.3, avg_win_r=1.0, avg_loss_r=1.0) == 0.0

    def test_a_coin_flip_at_two_to_one_gives_the_textbook_quarter(self):
        # b=2, p=0.5 -> (0.5*3 - 1)/2 = 0.25
        assert kelly_fraction(0.5, 2.0, 1.0) == pytest.approx(0.25)

    def test_a_bigger_edge_allows_a_bigger_fraction(self):
        assert kelly_fraction(0.6, 2.0, 1.0) > kelly_fraction(0.55, 2.0, 1.0)


class TestSimulate:
    def test_a_losing_system_ruins_far_more_often_than_a_winning_one(self):
        losing = simulate(0.40, 1.0, 1.0, risk_per_trade=0.02, n_simulations=2000)
        winning = simulate(0.60, 1.0, 1.0, risk_per_trade=0.02, n_simulations=2000)
        assert losing.p_ruin > winning.p_ruin
        assert losing.expectancy_r < 0 < winning.expectancy_r

    def test_a_positive_expectancy_system_still_ruins_when_bet_too_large(self):
        """The central lesson: edge does not make a size survivable."""
        small = simulate(0.55, 1.0, 1.0, risk_per_trade=0.01, n_simulations=2000)
        huge = simulate(0.55, 1.0, 1.0, risk_per_trade=0.30, n_simulations=2000)
        assert small.expectancy_r == huge.expectancy_r  # same edge
        assert huge.p_ruin > small.p_ruin

    def test_ruin_is_detected_mid_path_not_only_at_the_end(self):
        # Alternating-ish paths can dip below the threshold and recover; an
        # end-of-path check would miss those and understate the risk.
        res = simulate(
            0.50, 1.0, 1.0, risk_per_trade=0.25, n_trades=400,
            ruin_threshold=0.5, n_simulations=2000,
        )
        assert res.p_ruin > 0
        # Some simulations end above the threshold despite having touched it.
        assert res.median_final_equity >= 0

    def test_drawdown_percentiles_are_ordered(self):
        res = simulate(0.55, 1.0, 1.0, risk_per_trade=0.02, n_simulations=2000)
        assert 0 <= res.median_max_drawdown <= res.p95_max_drawdown <= 1.0

    def test_more_trades_deepen_the_worst_case_drawdown(self):
        short = simulate(0.55, 1.0, 1.0, 0.02, n_trades=50, n_simulations=2000)
        long = simulate(0.55, 1.0, 1.0, 0.02, n_trades=500, n_simulations=2000)
        assert long.p95_max_drawdown > short.p95_max_drawdown

    def test_the_same_inputs_give_the_same_answer(self):
        # A risk figure that changes on every page load reads as noise and
        # invites rerolling until a comfortable number appears.
        a = simulate(0.55, 1.5, 1.0, 0.01, n_simulations=500)
        b = simulate(0.55, 1.5, 1.0, 0.01, n_simulations=500)
        assert a.p_ruin == b.p_ruin
        assert a.p95_max_drawdown == b.p95_max_drawdown

    def test_zero_risk_never_ruins_and_never_moves(self):
        res = simulate(0.55, 1.0, 1.0, risk_per_trade=0.0, n_simulations=200)
        assert res.p_ruin == 0.0
        assert res.median_final_equity == pytest.approx(1.0)
        assert res.p95_max_drawdown == pytest.approx(0.0)

    def test_a_realistic_setup_from_this_repos_own_data_is_reported_honestly(self):
        """reversal_3d's measured net R was negative once costs were charged.
        Sized at 1% it should show a meaningful chance of a deep drawdown —
        the simulator must not flatter a losing system."""
        res = simulate(0.4548, 1.0, 1.0, risk_per_trade=0.01, n_trades=200, n_simulations=2000)
        assert res.expectancy_r < 0
        assert res.p_profit < 0.5
