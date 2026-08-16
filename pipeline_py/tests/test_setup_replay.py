from datetime import date, timedelta

from pipeline_py.screening.evaluate import Bar
from pipeline_py.setups.replay import replay

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


def make_bars(code, closes):
    dates = weekday_dates(len(closes))
    return [Bar(dt, c, c + 1, c - 1, c) for dt, c in zip(dates, closes)]


def feat_row(**kw):
    base = {"ma_25": 990.0, "ma_75": 950.0, "atr_14": 20.0, "adx_14": 25.0, "ret_20d": 0.1}
    base.update(kw)
    return base


class TestReplay:
    def test_a_qualifying_session_produces_one_outcome_row(self):
        code = "72030"
        closes = [1000 + i * 5 for i in range(30)]  # steady rise
        bars = {code: make_bars(code, closes)}
        as_of = bars[code][24].date
        features_by_date = {as_of: {code: feat_row(ma_25=closes[23] - 5)}}
        securities = {code: {"code": code}}
        turnover = {(code, as_of): 5_000_000_000}

        rows = replay(features_by_date, bars, securities, [BREAKOUT], [as_of], turnover)
        assert len(rows) == 1
        r = rows[0]
        assert r["code"] == code
        assert r["setup_key"] == "breakout_20d"
        assert r["as_of"] == as_of
        assert r["outcome"] in {"target", "stop", "timeout", "no_entry"}

    def test_a_code_missing_from_securities_is_excluded(self):
        code = "72030"
        closes = [1000 + i * 5 for i in range(30)]
        bars = {code: make_bars(code, closes)}
        as_of = bars[code][24].date
        features_by_date = {as_of: {code: feat_row()}}
        turnover = {(code, as_of): 5_000_000_000}

        rows = replay(features_by_date, bars, {}, [BREAKOUT], [as_of], turnover)
        assert rows == []

    def test_the_session_immediately_after_as_of_is_the_entry(self):
        # Deterministic target hit: after the draft session, price gaps
        # straight to the target on the very next bar. A slight upward
        # drift keeps low_10 strictly below high_20/trigger — a perfectly
        # flat series makes invalidation == trigger, which resolve_plan_levels
        # correctly refuses to resolve.
        code = "72030"
        closes = [1000.0 + i * 0.5 for i in range(25)]
        bars_list = make_bars(code, closes)
        as_of = bars_list[24].date
        # Append one more session that gaps to a clear target hit.
        next_date = weekday_dates(1, start=(date.fromisoformat(as_of) + timedelta(days=3)).isoformat())[0]
        bars_list.append(Bar(next_date, 1200.0, 1210.0, 1195.0, 1205.0))
        bars = {code: bars_list}
        features_by_date = {as_of: {code: feat_row(ma_25=990.0, atr_14=10.0)}}
        securities = {code: {"code": code}}
        turnover = {(code, as_of): 5_000_000_000}

        rows = replay(features_by_date, bars, securities, [BREAKOUT], [as_of], turnover)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "target"
        assert rows[0]["entry_fill"] == 1200.0  # the next session's open

    def test_no_session_after_as_of_produces_no_row(self):
        code = "72030"
        closes = [1000 + i * 5 for i in range(25)]
        bars = {code: make_bars(code, closes)}
        as_of = bars[code][-1].date  # last available bar — nothing to enter on
        features_by_date = {as_of: {code: feat_row(ma_25=closes[-2] - 5)}}
        securities = {code: {"code": code}}
        turnover = {(code, as_of): 5_000_000_000}

        rows = replay(features_by_date, bars, securities, [BREAKOUT], [as_of], turnover)
        assert rows == []

    def test_a_non_qualifying_code_produces_no_row(self):
        code = "72030"
        closes = [1000.0] * 30  # flat — never above its own ma_25 with the given feature
        bars = {code: make_bars(code, closes)}
        as_of = bars[code][24].date
        features_by_date = {as_of: {code: feat_row(ma_25=2000.0)}}  # close never above ma_25
        securities = {code: {"code": code}}
        turnover = {(code, as_of): 5_000_000_000}

        rows = replay(features_by_date, bars, securities, [BREAKOUT], [as_of], turnover)
        assert rows == []
