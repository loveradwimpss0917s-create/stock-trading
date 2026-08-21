import pytest

from pipeline_py.risk.cost_in_r import (
    CostAssumption,
    breakeven_slippage_rate,
    cost_in_r,
    plan_economics,
)


class TestSlippageRate:
    def test_scales_with_atr_above_the_floor(self):
        c = CostAssumption(min_slippage_rate=0.0005, atr_slippage_fraction=0.10)
        # ATR 2% of price -> 0.10 * 0.02 = 20bp, well above the 5bp floor
        assert c.slippage_rate(1000.0, 20.0) == pytest.approx(0.002)

    def test_falls_back_to_the_floor_for_a_quiet_name(self):
        c = CostAssumption(min_slippage_rate=0.0005, atr_slippage_fraction=0.10)
        # ATR 0.1% of price -> 1bp, below the floor
        assert c.slippage_rate(1000.0, 1.0) == 0.0005

    def test_missing_or_invalid_atr_uses_the_floor_rather_than_zero(self):
        c = CostAssumption()
        assert c.slippage_rate(1000.0, None) == c.min_slippage_rate
        assert c.slippage_rate(1000.0, 0.0) == c.min_slippage_rate
        assert c.slippage_rate(0.0, 20.0) == c.min_slippage_rate


class TestCostInR:
    def test_a_tighter_stop_costs_more_in_r_for_identical_execution(self):
        """The central point of the module: cost in R is driven by the size
        of the risk unit, so a tight stop makes the same spread expensive."""
        wide = cost_in_r(entry_fill=1000.0, exit_price=1000.0, stop_planned=964.0, atr=20.0)
        tight = cost_in_r(entry_fill=1000.0, exit_price=1000.0, stop_planned=980.0, atr=20.0)
        assert tight > wide
        # risk 36 vs 20 -> cost ratio should be 36/20 = 1.8x
        assert tight / wide == pytest.approx(36.0 / 20.0)

    def test_cost_is_charged_on_both_sides(self):
        one_side = 1000.0 * 0.002
        out = cost_in_r(entry_fill=1000.0, exit_price=1000.0, stop_planned=980.0, atr=20.0)
        assert out == pytest.approx(2 * one_side / 20.0)

    def test_risk_is_measured_from_the_actual_fill_not_the_planned_entry(self):
        # Gapped in at 1010 against a 980 stop -> risk 30, not the 20 a
        # 1000 reference would have implied. Using the plan would understate.
        gapped = cost_in_r(entry_fill=1010.0, exit_price=1010.0, stop_planned=980.0, atr=20.0)
        clean = cost_in_r(entry_fill=1000.0, exit_price=1000.0, stop_planned=980.0, atr=20.0)
        # Same execution, wider realised risk -> cheaper in R, by exactly the
        # ratio of the two risk distances.
        assert gapped == pytest.approx(clean * 20.0 / 30.0)

    def test_above_the_floor_cost_per_share_is_atr_driven_not_price_driven(self):
        """price * (fraction * atr / price) collapses to fraction * atr, so
        round-trip cost in R reduces to 2 * fraction / stop_multiple. That is
        why a 1.0x ATR stop costs ~0.20R and a 1.8x one ~0.11R, and why the
        two numbers measured on live data (0.178R / 0.098R) sit where they
        do — the difference is structural, not a data artifact."""
        atr, frac = 20.0, 0.10
        c = CostAssumption(atr_slippage_fraction=frac, min_slippage_rate=0.0)
        for mult in (1.0, 1.8, 3.0):
            entry = 1000.0
            stop = entry - mult * atr
            out = cost_in_r(entry, entry, stop, atr, c)
            assert out == pytest.approx(2 * frac / mult)

    def test_commission_adds_on_top_of_slippage(self):
        free = cost_in_r(1000.0, 1000.0, 980.0, 20.0, CostAssumption(commission_rate=0.0))
        paid = cost_in_r(1000.0, 1000.0, 980.0, 20.0, CostAssumption(commission_rate=0.001))
        assert paid > free

    def test_non_positive_risk_returns_none_rather_than_dividing(self):
        assert cost_in_r(980.0, 1000.0, 980.0, 20.0) is None
        assert cost_in_r(970.0, 1000.0, 980.0, 20.0) is None

    def test_a_zero_cost_assumption_yields_zero(self):
        free = CostAssumption(min_slippage_rate=0.0, atr_slippage_fraction=0.0, commission_rate=0.0)
        assert cost_in_r(1000.0, 1000.0, 980.0, 20.0, free) == 0.0


class TestBreakevenSlippage:
    def test_the_breakeven_rate_exactly_cancels_the_gross_r(self):
        entry, exit_, stop, gross = 1000.0, 1050.0, 980.0, 0.5
        rate = breakeven_slippage_rate(gross, entry, exit_, stop)
        c = CostAssumption(min_slippage_rate=rate, atr_slippage_fraction=0.0)
        assert cost_in_r(entry, exit_, stop, None, c) == pytest.approx(gross)

    def test_a_larger_gross_r_tolerates_more_slippage(self):
        small = breakeven_slippage_rate(0.1, 1000.0, 1050.0, 980.0)
        large = breakeven_slippage_rate(1.0, 1000.0, 1050.0, 980.0)
        assert large > small

    def test_non_positive_risk_returns_none(self):
        assert breakeven_slippage_rate(0.5, 980.0, 1000.0, 980.0) is None


class TestPlanEconomics:
    def test_cost_in_r_depends_only_on_the_stop_multiple(self):
        """The identity worth trusting over any single measurement: slippage
        per share is fraction x ATR and risk per share is mult x ATR, so ATR
        cancels and price never enters. A cheap stock and an expensive one
        with the same stop multiple pay the same cost in R."""
        seen = set()
        for price, atr in [(3000, 30), (3000, 60), (1500, 45), (800, 24)]:
            e = plan_economics(price, price - 1.8 * atr, price + 3.5 * atr, atr)
            seen.add(round(e.cost_win_r + e.cost_loss_r, 6))
        assert len(seen) == 1

    def test_halving_the_stop_multiple_roughly_doubles_the_cost_in_r(self):
        price, atr = 3000.0, 60.0
        wide = plan_economics(price, price - 2.0 * atr, price + 4.0 * atr, atr)
        tight = plan_economics(price, price - 1.0 * atr, price + 2.0 * atr, atr)
        assert tight.cost_loss_r == pytest.approx(2 * wide.cost_loss_r, rel=0.05)

    def test_a_loss_costs_more_than_one_r(self):
        """The half people skip: cost deepens the loser as well as shaving
        the winner, so the ratio falls faster than a single subtraction."""
        price, atr = 3000.0, 60.0
        e = plan_economics(price, price - 1.8 * atr, price + 3.5 * atr, atr)
        naive = e.rr_gross - (e.cost_win_r + e.cost_loss_r)
        assert e.rr_net < naive

    def test_the_seeded_setups_clear_their_own_min_rr_after_cost(self):
        # Migration 0030 widened the targets for exactly this reason; a
        # regression here means the live setups draft nothing.
        price, atr = 3000.0, 60.0
        for stop_mult, target_mult in [(1.8, 3.5), (1.0, 2.2)]:
            e = plan_economics(
                price, price - stop_mult * atr, price + target_mult * atr, atr
            )
            assert e.rr_net >= 1.5, (stop_mult, target_mult, e.rr_net)

    def test_the_previous_definitions_did_not(self):
        # Pins the finding rather than just the fix: 1.8x/3.0x and 1.0x/1.5x
        # were both under 1.5 net, so neither could ever have drafted a plan.
        price, atr = 3000.0, 60.0
        for stop_mult, target_mult in [(1.8, 3.0), (1.0, 1.5)]:
            e = plan_economics(
                price, price - stop_mult * atr, price + target_mult * atr, atr
            )
            assert e.rr_gross >= 1.5 > e.rr_net

    def test_an_inverted_stop_has_no_economics(self):
        assert plan_economics(1000.0, 1000.0, 1100.0, 20.0) is None
        assert plan_economics(1000.0, 1010.0, 1100.0, 20.0) is None
