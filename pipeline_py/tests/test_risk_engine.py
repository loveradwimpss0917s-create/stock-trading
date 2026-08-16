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
        # the notional cap even though R:R and lot size are fine.
        v = evaluate(
            account(capital=5_000_000, max_notional_pct=0.30),
            levels(trigger_price=1000.0, stop_planned=999.0, target_planned=1002.0),
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
