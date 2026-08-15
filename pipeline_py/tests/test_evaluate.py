from pipeline_py.screening.evaluate import MAX_HOLD, Bar, evaluate


def bar(date, o, h, l, c):
    return Bar(date, o, h, l, c)


def flat(n, start=1, price=100.0):
    """n identical bars that touch no barrier."""
    return [bar(f"2026-01-{start + i:02d}", price, price, price, price) for i in range(n)]


class TestBarriers:
    def test_target_hit_returns_one_r_scaled_by_the_actual_fill(self):
        bars = [bar("2026-01-02", 100.0, 112.0, 99.0, 110.0)]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "target"
        assert out.entry_fill == 100.0
        assert out.exit_price == 110.0
        # risk = 100 - 95 = 5, reward = 10 -> 2R
        assert out.r_multiple == 2.0

    def test_stop_hit_returns_minus_one_r(self):
        bars = [bar("2026-01-02", 100.0, 101.0, 94.0, 96.0)]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "stop"
        assert out.r_multiple == -1.0

    def test_a_bar_touching_both_counts_as_the_stop(self):
        # Daily bars say nothing about which side was touched first. Assuming
        # the profitable one would inflate every hit rate this produces.
        bars = [bar("2026-01-02", 100.0, 115.0, 90.0, 105.0)]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "stop"

    def test_timeout_marks_to_the_last_close(self):
        bars = flat(3, price=100.0) + [bar("2026-01-09", 100.0, 103.0, 99.0, 102.0)]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=3)
        assert out.outcome == "timeout"
        assert out.bars_held == 3
        # Marked at bar index 2's close, not the unused 4th bar.
        assert out.exit_price == 100.0

    def test_max_hold_does_not_see_past_its_window(self):
        # The target is hit one session after the window closes.
        bars = flat(3) + [bar("2026-01-09", 100.0, 120.0, 100.0, 119.0)]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=3)
        assert out.outcome == "timeout"

    def test_day_horizon_holds_a_single_session(self):
        assert MAX_HOLD["day"] == 1
        bars = [
            bar("2026-01-02", 100.0, 105.0, 98.0, 104.0),
            bar("2026-01-05", 104.0, 120.0, 104.0, 119.0),  # would hit, but too late
        ]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=MAX_HOLD["day"])
        assert out.outcome == "timeout"
        assert out.exit_price == 104.0


class TestGaps:
    def test_a_gap_through_the_stop_is_not_entered(self):
        # The open is already below the stop the screen published, so the
        # trade cannot be taken at its stated risk.
        bars = [bar("2026-01-02", 90.0, 92.0, 88.0, 91.0)]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "no_entry"
        assert out.r_multiple is None

    def test_a_gap_down_after_entry_fills_at_the_open_not_the_stop(self):
        bars = [
            bar("2026-01-02", 100.0, 101.0, 99.0, 100.0),
            bar("2026-01-05", 80.0, 82.0, 79.0, 81.0),  # gaps far below the stop
        ]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "stop"
        # Filled at 80, not at the 95 stop — worse than -1R, which is the point.
        assert out.exit_price == 80.0
        assert out.r_multiple == -4.0

    def test_a_gap_above_the_target_fills_at_the_open(self):
        bars = [
            bar("2026-01-02", 100.0, 101.0, 99.0, 100.0),
            bar("2026-01-05", 130.0, 131.0, 129.0, 130.0),
        ]
        out = evaluate(bars, 0, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "target"
        assert out.exit_price == 130.0
        assert out.r_multiple == 6.0


class TestCausality:
    def test_the_entry_bars_own_open_is_the_fill_not_the_prior_close(self):
        # A candidate is published on the prior close; the fill is the next
        # open. Using the close would quietly remove overnight gap risk.
        bars = [bar("2026-01-05", 103.0, 104.0, 102.0, 103.5)]
        out = evaluate(bars, 0, stop=100.0, target=110.0, max_hold=5)
        assert out.entry_fill == 103.0

    def test_bars_before_the_entry_index_cannot_trigger_a_barrier(self):
        bars = [
            bar("2026-01-02", 100.0, 200.0, 50.0, 100.0),  # before entry; must be ignored
            bar("2026-01-05", 100.0, 101.0, 99.0, 100.0),
        ]
        out = evaluate(bars, 1, stop=95.0, target=110.0, max_hold=1)
        assert out.outcome == "timeout"

    def test_an_entry_index_past_the_data_yields_no_entry(self):
        out = evaluate(flat(2), 5, stop=95.0, target=110.0, max_hold=5)
        assert out.outcome == "no_entry"


class TestAccounting:
    def test_r_multiple_is_measured_from_the_fill_and_the_published_stop(self):
        # Fill 102 (gapped up from a 100 reference), stop 95 -> risk is 7,
        # not the 5 the screen showed against its reference close.
        bars = [bar("2026-01-05", 102.0, 116.0, 101.0, 115.0)]
        out = evaluate(bars, 0, stop=95.0, target=116.0, max_hold=5)
        assert out.entry_fill == 102.0
        assert abs(out.r_multiple - (116.0 - 102.0) / (102.0 - 95.0)) < 1e-9

    def test_every_outcome_is_one_of_the_declared_values(self):
        cases = [
            ([bar("2026-01-05", 100.0, 111.0, 99.0, 110.0)], 95.0, 110.0),
            ([bar("2026-01-05", 100.0, 101.0, 94.0, 95.0)], 95.0, 110.0),
            (flat(2), 95.0, 110.0),
            ([bar("2026-01-05", 90.0, 91.0, 89.0, 90.0)], 95.0, 110.0),
        ]
        seen = {evaluate(b, 0, s, t, 2).outcome for b, s, t in cases}
        assert seen <= {"target", "stop", "timeout", "no_entry"}
        assert len(seen) == 4  # each case exercises a different branch


class TestBaselineIsAControl:
    """The baseline exists to answer "did picking help, or did the market just
    go up". That only works if it measures the same universe under the same
    levels as the themes — so these pin the shared code path rather than the
    numbers."""

    def test_baseline_uses_the_same_levels_helper_as_the_screen(self):
        from pipeline_py.screening import evaluate as ev
        from pipeline_py.screening.scoring import levels_for

        # Both call levels_for; a second copy of the filter/ATR logic would
        # silently stop the control from being a control.
        assert ev.levels_for is levels_for

    def test_levels_match_what_score_theme_publishes(self):
        from pipeline_py.screening.scoring import levels_for, score_theme
        from pipeline_py.tests.test_screening import BREAKOUT, row, universe

        rows = universe(TOP=row(dist_52w_high=-0.01, ret_20d=0.4))
        [top] = [c for c in score_theme(rows, BREAKOUT, "swing", top_n=1)]
        _close, _atr, stop, target = levels_for(rows[top.code], "swing")
        assert (round(stop, 2), round(target, 2)) == (top.stop_price, top.target_price)

    def test_an_illiquid_name_is_excluded_from_the_control_too(self):
        from pipeline_py.screening.scoring import MIN_TURNOVER, levels_for
        from pipeline_py.tests.test_screening import row

        assert levels_for(row(turnover_value=MIN_TURNOVER - 1), "swing") is None
