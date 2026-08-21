import pytest

from pipeline_py.risk.engine import PASS_GATES, WAIT_GATES, PlanLevels, PortfolioContext, evaluate, position_size


def account(**overrides):
    base = {
        "capital": 5_000_000,
        "risk_per_trade": 0.005,
        "max_positions": 5,
        "max_heat": 0.03,
        "max_notional_pct": 0.30,
        "min_rr": 1.5,
        "max_sector_positions": 2,
    }
    base.update(overrides)
    return base


def levels(**overrides):
    base = {
        "trigger_price": 4250.0,
        "stop_planned": 4080.0,
        "target_planned": 4600.0,  # (4600-4250)/(4250-4080) = 2.06R
        "sector33": "3650",
        "turnover_value": 1_000_000_000,
        "avg_volume_20d": 5_000_000,
    }
    base.update(overrides)
    return PlanLevels(**base)


def ctx(**overrides):
    base = {"open_positions": 0, "current_heat": 0.0, "sector_position_counts": {}}
    base.update(overrides)
    return PortfolioContext(**base)


class TestPositionSize:
    def test_sizes_off_the_stop_distance_and_floors_to_the_lot(self):
        # target risk = 5,000,000 * 0.005 = 25,000; risk/share = 170
        # 25,000 / 170 = 147.05 -> floor to 100 -> 100 shares
        shares, risk = position_size(5_000_000, 0.005, 4250.0, 4080.0)
        assert shares == 100
        assert risk == 100 * 170.0

    def test_actual_risk_never_exceeds_the_target(self):
        shares, risk = position_size(5_000_000, 0.005, 4250.0, 4080.0)
        assert risk <= 5_000_000 * 0.005

    def test_zero_or_negative_risk_per_share_yields_no_position(self):
        assert position_size(5_000_000, 0.005, 100.0, 100.0) == (0, 0.0)
        assert position_size(5_000_000, 0.005, 100.0, 105.0) == (0, 0.0)

    def test_larger_account_produces_proportionally_more_shares(self):
        small, _ = position_size(1_000_000, 0.005, 4250.0, 4080.0)
        large, _ = position_size(10_000_000, 0.005, 4250.0, 4080.0)
        assert large > small


class TestGateDecisions:
    def test_all_gates_passing_returns_buy(self):
        v = evaluate(account(), levels(), ctx())
        assert v.decision == "BUY"
        assert v.reason_code == "all_gates_passed"
        assert all(g["passed"] for g in v.gates.values())

    def test_rr_below_minimum_is_a_pass(self):
        # trigger 4250, stop 4080 (risk 170), target 4350 (reward 100) -> 0.59R
        v = evaluate(account(), levels(target_planned=4350.0), ctx())
        assert v.decision == "PASS"
        assert v.reason_code == "min_rr"
        assert v.gates["min_rr"]["passed"] is False

    def test_shares_below_lot_size_is_a_pass(self):
        # Tiny account can't afford even one lot at this risk distance.
        v = evaluate(account(capital=10_000), levels(), ctx())
        assert v.decision == "PASS"
        assert v.reason_code == "lot_size"

    def test_notional_over_the_cap_is_a_pass(self):
        # A cheap stop distance produces a huge share count that blows past
        # the notional cap even though R:R and lot size are fine. The stop is
        # 1% rather than 0.1%: at 0.1% the round trip alone is ~1R, so the
        # plan would fail on cost before it ever reached the notional gate.
        v = evaluate(
            account(capital=5_000_000, max_notional_pct=0.30),
            levels(trigger_price=1000.0, stop_planned=990.0, target_planned=1020.0),
            ctx(),
        )
        assert v.decision == "PASS"
        assert v.reason_code == "notional"

    def test_illiquid_turnover_is_a_pass(self):
        v = evaluate(account(), levels(turnover_value=100_000_000), ctx())
        assert v.decision == "PASS"
        assert v.reason_code == "turnover"

    def test_missing_turnover_does_not_block(self):
        # Matches score_theme's own _passes_liquidity: unknown isn't guilty.
        v = evaluate(account(), levels(turnover_value=None), ctx())
        assert v.gates["turnover"]["passed"] is True

    def test_shares_over_one_percent_of_adv_is_a_pass(self):
        v = evaluate(account(), levels(avg_volume_20d=1_000), ctx())  # 100/1000 = 10%
        assert v.decision == "PASS"
        assert v.reason_code == "liquidity"

    def test_heat_exceeded_is_a_wait_not_a_pass(self):
        v = evaluate(account(max_heat=0.001), levels(), ctx(current_heat=0.0))
        assert v.decision == "WAIT"
        assert v.reason_code == "heat"

    def test_max_positions_reached_is_a_wait(self):
        v = evaluate(account(max_positions=2), levels(), ctx(open_positions=2))
        assert v.decision == "WAIT"
        assert v.reason_code == "max_positions"

    def test_sector_concentration_is_a_wait(self):
        v = evaluate(
            account(max_sector_positions=2),
            levels(sector33="3650"),
            ctx(sector_position_counts={"3650": 2}),
        )
        assert v.decision == "WAIT"
        assert v.reason_code == "sector_concentration"

    def test_unknown_sector_does_not_inherit_another_sectors_count(self):
        # A plan with no sector33 must not accidentally match existing
        # positions parked under a real sector code — it should count as 0,
        # not as whatever the busiest sector bucket happens to hold.
        v = evaluate(
            account(max_sector_positions=1),
            levels(sector33=None),
            ctx(sector_position_counts={"3700": 5}),
        )
        assert v.gates["sector_concentration"]["passed"] is True
        assert v.gates["sector_concentration"]["value"] == 0


class TestGatePriority:
    def test_instrument_level_pass_beats_a_simultaneous_portfolio_level_wait(self):
        # Both min_rr and max_positions fail at once. The instrument-level
        # PASS reason should surface, not the portfolio-level WAIT — telling
        # the user "this name is bad" is more useful than "no room right now"
        # when both are true.
        v = evaluate(
            account(max_positions=0),
            levels(target_planned=4300.0),  # rr well under 1.5
            ctx(open_positions=1),
        )
        assert v.decision == "PASS"
        assert v.reason_code == "min_rr"

    def test_gate_dicts_are_fully_populated_even_when_an_early_gate_fails(self):
        # The caller persists gate_results for every plan_decision, so every
        # gate must be evaluated regardless of which one determines the verdict.
        v = evaluate(account(), levels(target_planned=4300.0), ctx())
        assert set(v.gates) == set(PASS_GATES) | set(WAIT_GATES)


class TestCostAwareRR:
    """The R:R gate is evaluated net of execution cost. Every figure the app
    reported before this was gross, i.e. a return nobody could have taken."""

    def test_the_reported_rr_is_lower_than_the_chart_says(self):
        v = evaluate(account(), levels(), ctx())
        assert v.rr_net < v.rr_gross
        assert v.gates["min_rr"]["value"] == round(v.rr_net, 3)
        assert v.gates["min_rr"]["gross"] == round(v.rr_gross, 3)

    def test_a_plan_that_only_clears_the_bar_before_cost_is_rejected(self):
        """The gate this whole change exists for: gross 1.5R against a
        min_rr of 1.5 is not a 1.5R trade once the round trip is paid."""
        # risk 170/share; a target of exactly 1.5R gross is 4250 + 255.
        v = evaluate(account(min_rr=1.5), levels(target_planned=4505.0), ctx())
        assert v.gates["min_rr"]["gross"] >= 1.5
        assert v.decision == "PASS"
        assert v.reason_code == "min_rr_after_cost"

    def test_a_genuinely_bad_rr_still_reads_as_an_ordinary_rejection(self):
        # Not a cost problem — the plan was never close. The distinct reason
        # code must not swallow the plain case.
        v = evaluate(account(), levels(target_planned=4350.0), ctx())
        assert v.reason_code == "min_rr"

    def test_a_tighter_stop_costs_more_in_r_for_identical_execution(self):
        """The counter-intuitive result worth surfacing: 'risking less per
        share' makes the trade more expensive in its own risk unit, because
        the unit shrank faster than the cost did."""
        atr = 100.0
        tight = evaluate(
            account(min_rr=0.0),
            levels(trigger_price=4250.0, stop_planned=4250.0 - 1.0 * atr,
                   target_planned=4250.0 + 3.0 * atr, atr=atr),
            ctx(),
        )
        wide = evaluate(
            account(min_rr=0.0),
            levels(trigger_price=4250.0, stop_planned=4250.0 - 2.0 * atr,
                   target_planned=4250.0 + 6.0 * atr, atr=atr),
            ctx(),
        )
        # Same 3:1 gross on both.
        assert tight.rr_gross == pytest.approx(wide.rr_gross)
        assert tight.economics.cost_loss_r > wide.economics.cost_loss_r
        assert tight.rr_net < wide.rr_net

    def test_the_break_even_win_rate_rises_once_cost_is_charged(self):
        v = evaluate(account(), levels(atr=100.0), ctx())
        econ = v.economics
        assert econ.required_win_rate_net > econ.required_win_rate_gross

    def test_a_plan_whose_target_cannot_cover_its_own_cost_has_no_win_rate(self):
        # Best case is a net loss, so no hit rate makes it profitable. The
        # honest answer is "none", not a plausible-looking fraction.
        v = evaluate(
            account(min_rr=0.0),
            levels(trigger_price=1000.0, stop_planned=999.0, target_planned=1000.5),
            ctx(),
        )
        assert v.rr_net < 0
        assert v.economics.required_win_rate_net is None
        assert v.decision == "PASS"

    def test_missing_atr_falls_back_to_the_floor_rather_than_to_zero_cost(self):
        v = evaluate(account(), levels(atr=None), ctx())
        assert v.economics.cost_win_r > 0

    def test_an_inverted_stop_reports_no_economics_and_still_passes_out(self):
        v = evaluate(account(), levels(stop_planned=4300.0), ctx())
        assert v.economics is None
        assert v.rr_net == 0.0
        assert v.decision == "PASS"
