from datetime import date, timedelta

import pytest

from pipeline_py.screening.evaluate import Bar
from pipeline_py.setups.rules import (
    add_trading_days,
    consecutive_down_days,
    passes_candidate_rule,
    resolve_plan_levels,
    rolling_high,
    rolling_low,
)

BREAKOUT = {
    "trigger_rule": {"type": "close_above", "ref": "high_20", "buffer_pct": 0.0},
    "invalidation_rule": {"type": "close_below", "ref": "low_10"},
    "stop_rule": {"type": "atr_mult", "mult": 1.8},
    "target_rule": {"type": "atr_mult", "mult": 3.0},
    "expiry_bars": 5,
}
PULLBACK = {
    "trigger_rule": {"type": "close_above", "ref": "prior_high"},
    "invalidation_rule": {"type": "close_below", "ref": "ma_75"},
    "stop_rule": {"type": "atr_mult", "mult": 1.8},
    "target_rule": {"type": "atr_mult", "mult": 3.0},
    "expiry_bars": 5,
}
REVERSAL = {
    "trigger_rule": {"type": "close_above", "ref": "prior_high"},
    "invalidation_rule": {"type": "additional_atr_drawdown", "mult": 1.5},
    "stop_rule": {"type": "atr_mult", "mult": 1.0},
    "target_rule": {"type": "atr_mult", "mult": 1.5},
    "expiry_bars": 2,
}


def make_bars(closes, start="2026-01-05", highs=None, lows=None):
    """Weekday-spaced bars. high defaults to close+1, low to close-1."""
    bars = []
    d = date.fromisoformat(start)
    i = 0
    while len(bars) < len(closes):
        if d.weekday() < 5:
            c = closes[len(bars)]
            h = highs[len(bars)] if highs else c + 1
            lo = lows[len(bars)] if lows else c - 1
            bars.append(Bar(d.isoformat(), c, h, lo, c))
        d += timedelta(days=1)
        i += 1
    return bars


class TestRollingWindows:
    def test_rolling_high_is_the_max_close_over_n_sessions_including_idx(self):
        bars = make_bars([10, 12, 9, 15, 11])
        assert rolling_high(bars, 4, 3) == 15  # window = idx 2,3,4 -> 9,15,11

    def test_rolling_low_is_the_min_close_over_n_sessions_including_idx(self):
        bars = make_bars([10, 12, 9, 15, 11])
        assert rolling_low(bars, 4, 3) == 9

    def test_insufficient_history_returns_none(self):
        bars = make_bars([10, 12, 9])
        assert rolling_high(bars, 2, 20) is None
        assert rolling_low(bars, 2, 20) is None

    def test_window_excludes_sessions_before_it(self):
        # A huge early spike outside the window must not leak in.
        bars = make_bars([1000, 10, 12, 9, 15, 11])
        assert rolling_high(bars, 5, 3) == 15


class TestConsecutiveDownDays:
    def test_counts_a_run_of_strictly_lower_closes(self):
        bars = make_bars([10, 12, 11, 10, 9])  # down at idx2,3,4
        assert consecutive_down_days(bars, 4) == 3

    def test_zero_when_the_session_itself_is_not_a_down_day(self):
        bars = make_bars([10, 9, 11])
        assert consecutive_down_days(bars, 2) == 0

    def test_zero_at_the_first_session(self):
        bars = make_bars([10])
        assert consecutive_down_days(bars, 0) == 0


class TestAddTradingDays:
    def test_skips_weekends(self):
        # 2026-01-05 is a Monday; +5 trading days lands the following Monday.
        assert add_trading_days("2026-01-05", 5) == "2026-01-12"

    def test_from_a_friday_skips_straight_to_monday(self):
        assert add_trading_days("2026-01-09", 1) == "2026-01-12"


def feat_row(**kw):
    base = {"atr_14": 30.0, "ma_25": 990.0, "ma_75": 950.0, "ret_20d": 0.1, "adx_14": 25.0}
    base.update(kw)
    return base


class TestResolvePlanLevels:
    def test_breakout_resolves_a_higher_stop_below_and_target_above_trigger(self):
        bars = make_bars([1000 + i for i in range(25)])  # steadily rising, 25 sessions
        idx = 24
        levels = resolve_plan_levels(BREAKOUT, bars, idx, feat_row())
        assert levels is not None
        assert levels.stop_planned < levels.trigger_price < levels.target_planned
        # trigger = rolling_high(20 sessions incl idx) = bars[idx].close (highest, since rising)
        assert levels.trigger_price == bars[idx].close

    def test_pullback_trigger_is_the_draft_sessions_own_high(self):
        bars = make_bars([100] * 80, highs=[105] * 80)
        levels = resolve_plan_levels(PULLBACK, bars, 79, feat_row(ma_75=90.0))
        assert levels is not None
        assert levels.trigger_price == 105.0

    def test_pullback_invalidation_uses_ma_75_from_features(self):
        bars = make_bars([100] * 80)
        levels = resolve_plan_levels(PULLBACK, bars, 79, feat_row(ma_75=88.0))
        assert levels.invalidation == {"type": "close_below", "level": 88.0, "source_ref": "ma_75"}

    def test_reversal_invalidation_is_atr_multiple_below_reference_close(self):
        bars = make_bars([100, 95, 90])  # idx2 close=90, consecutive down
        levels = resolve_plan_levels(REVERSAL, bars, 2, feat_row(atr_14=10.0))
        # 90 - 1.5*10 = 75
        assert levels.invalidation["level"] == 75.0

    def test_missing_atr_yields_no_levels(self):
        bars = make_bars([100] * 25)
        assert resolve_plan_levels(BREAKOUT, bars, 24, feat_row(atr_14=None)) is None

    def test_insufficient_history_for_the_trigger_window_yields_no_levels(self):
        bars = make_bars([100] * 5)  # breakout needs 20 sessions for high_20
        assert resolve_plan_levels(BREAKOUT, bars, 4, feat_row()) is None

    def test_invalidation_at_or_above_the_trigger_is_rejected(self):
        # ma_75 sitting above the trigger itself would mean the thesis is
        # already invalid before the position could even be entered.
        bars = make_bars([100] * 80)  # default high = close+1 = 101 = trigger
        levels = resolve_plan_levels(PULLBACK, bars, 79, feat_row(ma_75=105.0))
        assert levels is None

    def test_a_tighter_invalidation_than_the_atr_stop_is_not_rejected(self):
        # A wide ATR makes the stop land well below ma_75, so as price falls
        # from the trigger, invalidation (the higher level) fires first.
        # That ordering is expected, not a contradiction.
        bars = make_bars([100] * 80)
        levels = resolve_plan_levels(PULLBACK, bars, 79, feat_row(ma_75=90.0, atr_14=30.0))
        assert levels is not None
        assert levels.invalidation["level"] > levels.stop_planned

    def test_expires_on_is_expiry_bars_trading_days_after_the_draft_session(self):
        bars = make_bars([100 + i for i in range(25)])
        levels = resolve_plan_levels(BREAKOUT, bars, 24, feat_row())
        assert levels.expires_on == add_trading_days(bars[24].date, 5)


def cand_row(**kw):
    base = {
        "close": 1000.0, "ma_25": 990.0, "ma_75": 950.0,
        "adx_14": 25.0, "ret_20d": 0.1, "atr_14": 15.0,
        "turnover_value": 500_000_000,
    }
    base.update(kw)
    return base


class TestPassesCandidateRule:
    def test_all_conditions_must_hold(self):
        bars = make_bars([1000] * 25)
        rule = {"close_above_ma25": True, "adx_14_min": 20}
        assert passes_candidate_rule(rule, cand_row(), bars, 24) is True
        assert passes_candidate_rule(rule, cand_row(adx_14=10), bars, 24) is False

    def test_dist_from_high20_uses_the_same_rolling_window_as_the_trigger(self):
        bars = make_bars([1000 - i for i in range(20)] + [1000])  # idx20 close=1000=high
        rule = {"dist_from_high20_pct_max": 0.0}
        assert passes_candidate_rule(rule, cand_row(close=1000.0), bars, 20) is True

    def test_dist_from_high20_fails_when_far_below(self):
        bars = make_bars([1000] * 20 + [900])
        rule = {"dist_from_high20_pct_max": 0.03}
        assert passes_candidate_rule(rule, cand_row(close=900.0), bars, 20) is False

    def test_min_turnover_missing_data_fails_closed(self):
        # Unlike the risk engine's liquidity gate (which lets missing data
        # through), a *candidate* rule with an explicit turnover floor should
        # not draft a plan for a stock whose liquidity is simply unknown.
        bars = make_bars([1000] * 5)
        rule = {"min_turnover": 300_000_000}
        assert passes_candidate_rule(rule, cand_row(turnover_value=None), bars, 4) is False

    def test_consecutive_down_days_min(self):
        bars = make_bars([100, 95, 90, 85])
        rule = {"consecutive_down_days_min": 3}
        assert passes_candidate_rule(rule, cand_row(), bars, 3) is True
        assert passes_candidate_rule(rule, cand_row(), bars, 1) is False

    def test_unknown_rule_key_raises(self):
        with pytest.raises(ValueError):
            passes_candidate_rule({"not_a_real_key": 1}, cand_row(), make_bars([100]), 0)
