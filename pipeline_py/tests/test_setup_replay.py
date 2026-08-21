from datetime import date, timedelta

from pipeline_py.screening.evaluate import Bar
from pipeline_py.setups.replay import baseline, replay, walk_plan

BREAKOUT = {
    "key": "breakout_20d",
    "candidate_rule": {"close_above_ma25": True, "min_turnover": 300_000_000},
    "trigger_rule": {"type": "close_above", "ref": "high_20", "buffer_pct": 0.0},
    "invalidation_rule": {"type": "close_below", "ref": "low_10"},
    "stop_rule": {"type": "atr_mult", "mult": 1.8},
    "target_rule": {"type": "atr_mult", "mult": 3.0},
    "time_stop_bars": 10,
    "expiry_bars": 5,
    "min_rr": 1.0,
}


def weekday_dates(n, start="2026-01-05"):
    d = date.fromisoformat(start)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def bars_from(closes, opens=None, highs=None, lows=None):
    dates = weekday_dates(len(closes))
    return [
        Bar(
            dt,
            opens[i] if opens else closes[i],
            highs[i] if highs else closes[i] + 1,
            lows[i] if lows else closes[i] - 1,
            closes[i],
        )
        for i, dt in enumerate(dates)
    ]


class TestWalkPlanWaitsForTheTrigger:
    """The bug this replaces bought unconditionally on as_of+1 while still
    measuring risk from trigger_price — a price that was never paid. These
    pin the corrected behaviour against that regression."""

    def test_no_fill_while_price_stays_below_the_trigger(self):
        # Drifts up but never reaches 120 within the 5-session window.
        bars = bars_from([100, 101, 102, 103, 104, 105])
        out = walk_plan(bars, 0, trigger_price=120, invalidation_level=90,
                        stop=110, target=140, expiry_bars=5, time_stop_bars=10)
        assert out["outcome"] == "expired"
        assert out.get("entry_fill") is None

    def test_the_fill_is_the_session_after_the_trigger_not_the_trigger_itself(self):
        # Trigger fires on index 2 (close 120); the fill must be index 3's open.
        bars = bars_from(
            [100, 105, 120, 125, 130, 135],
            opens=[100, 104, 118, 123, 128, 133],
        )
        out = walk_plan(bars, 0, trigger_price=120, invalidation_level=90,
                        stop=110, target=140, expiry_bars=5, time_stop_bars=10)
        assert out["triggered_on"] == bars[2].date
        assert out["entry_fill"] == 123  # bars[3].open

    def test_a_trigger_on_the_last_watched_session_still_needs_a_fill_session(self):
        # Triggers exactly at the expiry boundary but no bar remains to buy on.
        bars = bars_from([100, 101, 102, 103, 104, 120])
        out = walk_plan(bars, 0, trigger_price=120, invalidation_level=90,
                        stop=110, target=140, expiry_bars=5, time_stop_bars=10)
        assert out is None  # unjudgeable, not a timeout

    def test_invalidation_before_the_trigger_ends_the_plan_unfilled(self):
        bars = bars_from([100, 85, 130, 140, 150, 160])
        out = walk_plan(bars, 0, trigger_price=120, invalidation_level=90,
                        stop=110, target=140, expiry_bars=5, time_stop_bars=10)
        assert out["outcome"] == "invalidated"
        assert out.get("entry_fill") is None

    def test_a_window_running_past_the_data_is_unjudgeable(self):
        bars = bars_from([100, 101, 102])  # only 2 sessions of a 5-session window
        out = walk_plan(bars, 0, trigger_price=120, invalidation_level=90,
                        stop=110, target=140, expiry_bars=5, time_stop_bars=10)
        assert out is None

    def test_r_is_measured_from_the_actual_fill(self):
        # Fill at 123, stop 110 -> risk 13. Target 140 reached on a later bar.
        bars = bars_from(
            [100, 105, 120, 125, 145, 150],
            opens=[100, 104, 118, 123, 141, 148],
            highs=[101, 106, 121, 126, 146, 151],
        )
        out = walk_plan(bars, 0, trigger_price=120, invalidation_level=90,
                        stop=110, target=140, expiry_bars=5, time_stop_bars=10)
        assert out["outcome"] == "target"
        assert out["entry_fill"] == 123
        # exit 141 (gapped past the 140 target, so filled at the open)
        assert abs(out["r_multiple"] - (141 - 123) / (123 - 110)) < 1e-9


def feat_row(**kw):
    base = {"ma_25": 990.0, "ma_75": 950.0, "atr_14": 20.0, "adx_14": 25.0, "ret_20d": 0.1}
    base.update(kw)
    return base


class TestReplay:
    def test_a_qualifying_session_produces_one_row(self):
        code = "72030"
        closes = [1000 + i * 5 for i in range(40)]
        bars = {code: bars_from(closes)}
        as_of = bars[code][24].date
        rows = replay(
            {as_of: {code: feat_row(ma_25=closes[23] - 5)}},
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert len(rows) == 1
        assert rows[0]["setup_key"] == "breakout_20d"

    def test_a_code_missing_from_securities_is_excluded(self):
        code = "72030"
        closes = [1000 + i * 5 for i in range(40)]
        bars = {code: bars_from(closes)}
        as_of = bars[code][24].date
        rows = replay(
            {as_of: {code: feat_row()}}, bars, {}, [BREAKOUT], [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert rows == []

    def test_a_code_failing_the_candidate_rule_is_excluded(self):
        code = "72030"
        closes = [1000.0] * 40
        bars = {code: bars_from(closes)}
        as_of = bars[code][24].date
        rows = replay(
            {as_of: {code: feat_row(ma_25=2000.0)}},  # close never above ma_25
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert rows == []

    def test_unfilled_plans_are_recorded_rather_than_dropped(self):
        # How often a Setup fails to trigger is part of its cost; dropping
        # those rows would make the survivors look better than the Setup is.
        code = "72030"
        closes = [1000 + i * 5 for i in range(24)] + [900.0] * 16  # collapses after as_of
        bars = {code: bars_from(closes)}
        as_of = bars[code][23].date
        rows = replay(
            {as_of: {code: feat_row(ma_25=closes[22] - 5)}},
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert len(rows) == 1
        assert rows[0]["outcome"] in {"invalidated", "expired"}
        assert rows[0]["r_multiple"] is None


class TestBaselineIsAControl:
    def test_it_ignores_signal_conditions_and_buys_everything_tradable(self):
        # This name fails BREAKOUT's candidate_rule outright, yet must still
        # appear in the control — "buy everything" has to mean everything.
        code = "72030"
        bars = {code: bars_from([1000.0] * 40)}
        as_of = bars[code][24].date
        rows = baseline(
            {as_of: {code: feat_row(ma_25=2000.0)}},
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert len(rows) == 1
        assert rows[0]["n_trades"] == 1

    def test_it_still_applies_the_liquidity_floor(self):
        # A name too thin to fill isn't a fair member of "buy everything".
        code = "72030"
        bars = {code: bars_from([1000.0] * 40)}
        as_of = bars[code][24].date
        rows = baseline(
            {as_of: {code: feat_row()}},
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 1_000_000},  # below min_turnover
        )
        assert rows == []

    def test_it_does_not_wait_for_a_trigger(self):
        # The control buys on as_of+1 regardless of price action. Waiting is
        # part of what the Setup does, so it has to beat not-waiting.
        code = "72030"
        # Flat forever: a trigger-waiting walk would expire, the control fills.
        bars = {code: bars_from([1000.0] * 40)}
        as_of = bars[code][24].date
        rows = baseline(
            {as_of: {code: feat_row()}},
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert rows[0]["n_trades"] == 1

    def test_a_name_without_atr_is_skipped(self):
        code = "72030"
        bars = {code: bars_from([1000.0] * 40)}
        as_of = bars[code][24].date
        rows = baseline(
            {as_of: {code: feat_row(atr_14=None)}},
            bars,
            {code: {"code": code}},
            [BREAKOUT],
            [as_of],
            {(code, as_of): 5_000_000_000},
        )
        assert rows == []

    def test_sum_r_is_kept_so_sessions_weight_by_trade_count(self):
        # Averaging per-session averages would weight a 2-name session the
        # same as a 200-name one.
        codes = ["A", "B"]
        bars = {c: bars_from([1000.0] * 40) for c in codes}
        as_of = bars["A"][24].date
        rows = baseline(
            {as_of: {c: feat_row() for c in codes}},
            bars,
            {c: {"code": c} for c in codes},
            [BREAKOUT],
            [as_of],
            {(c, as_of): 5_000_000_000 for c in codes},
        )
        assert rows[0]["n_trades"] == 2
        assert "sum_r" in rows[0]
