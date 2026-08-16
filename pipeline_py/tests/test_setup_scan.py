from datetime import date, timedelta
from unittest.mock import MagicMock

from pipeline_py.setups.scan import run_scan

AS_OF = "2026-05-22"

BREAKOUT = {
    "key": "breakout_20d",
    "horizon": "swing",
    "candidate_rule": {"close_above_ma25": True, "adx_14_min": 20, "min_turnover": 300_000_000},
    "trigger_rule": {"type": "close_above", "ref": "high_20", "buffer_pct": 0.0},
    "invalidation_rule": {"type": "close_below", "ref": "low_10"},
    "stop_rule": {"type": "atr_mult", "mult": 1.8},
    "target_rule": {"type": "atr_mult", "mult": 3.0},
    "time_stop_bars": 10,
    "expiry_bars": 5,
    "min_rr": 1.5,
}


def _weekday_dates(n, end=AS_OF):
    d = date.fromisoformat(end)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return list(reversed(out))


def _rising_bars_rows(code, n=25, start_close=1000.0, step=5.0):
    dates = _weekday_dates(n)
    rows = []
    for i, d in enumerate(dates):
        c = start_close + i * step
        rows.append(
            {
                "code": code, "date": d,
                "open": c - 1, "high": c + 1, "low": c - 2, "close": c,
                "turnover_value": 5_000_000_000,
            }
        )
    return rows


def _mock_db(setups, sec_rows, feature_rows, quote_rows, active_plans=None, accounts=None):
    db = MagicMock()

    def select(table, params):
        assert table == "features"
        return [{"date": AS_OF}]

    def select_all(table, params):
        if table == "setups":
            return setups
        if table == "securities_with_data":
            return sec_rows
        if table == "features":
            return feature_rows
        if table == "daily_quotes":
            return quote_rows
        if table == "accounts":
            return accounts if accounts is not None else [{"id": 1}]
        if table == "trade_plans":
            return active_plans or []
        raise AssertionError(f"unexpected table: {table}")

    db.select.side_effect = select
    db.select_all.side_effect = select_all
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    return db


def sec_row(code, sector33="3650"):
    return {"code": code, "name_ja": f"銘柄{code}", "sector33": sector33, "scale_category": "TOPIX Core30"}


def feat_row(code, **kw):
    base = {
        "code": code, "ret_1d": 0.01, "ret_5d": 0.02, "ret_20d": 0.15,
        "rsi_14": 60.0, "atr_14": 20.0, "adx_14": 25.0, "vol_20d": 0.2,
        "dist_52w_high": -0.01, "ma_25": 990.0, "ma_75": 950.0,
    }
    base.update(kw)
    return base


class TestRunScan:
    def test_a_qualifying_code_produces_one_draft_with_resolved_levels(self, monkeypatch):
        code = "72030"
        db = _mock_db(
            setups=[BREAKOUT],
            sec_rows=[sec_row(code)],
            feature_rows=[feat_row(code)],
            quote_rows=_rising_bars_rows(code),
        )
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        drafts = run_scan(persist=False)
        assert len(drafts) == 1
        d = drafts[0]
        assert d["code"] == code
        assert d["setup_key"] == "breakout_20d"
        assert d["state"] == "draft"
        assert d["stop_planned"] < d["trigger_price"] < d["target_planned"]
        assert d["expected_rr"] >= BREAKOUT["min_rr"]

    def test_a_code_with_an_active_plan_for_the_same_setup_is_skipped(self, monkeypatch):
        code = "72030"
        db = _mock_db(
            setups=[BREAKOUT],
            sec_rows=[sec_row(code)],
            feature_rows=[feat_row(code)],
            quote_rows=_rising_bars_rows(code),
            active_plans=[{"code": code, "setup_key": "breakout_20d"}],
        )
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        assert run_scan(persist=False) == []

    def test_a_code_failing_the_candidate_rule_produces_nothing(self, monkeypatch):
        code = "72030"
        db = _mock_db(
            setups=[BREAKOUT],
            sec_rows=[sec_row(code)],
            feature_rows=[feat_row(code, adx_14=5.0)],  # below adx_14_min=20
            quote_rows=_rising_bars_rows(code),
        )
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        assert run_scan(persist=False) == []

    def test_zero_qualifying_names_is_a_normal_empty_result_not_an_error(self, monkeypatch):
        # No securities at all — the point being this must not raise.
        db = _mock_db(setups=[BREAKOUT], sec_rows=[], feature_rows=[], quote_rows=[])
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        assert run_scan(persist=False) == []

    def test_a_fund_is_excluded_even_if_its_numbers_would_qualify(self, monkeypatch):
        code = "13060"
        db = _mock_db(
            setups=[BREAKOUT],
            sec_rows=[{"code": code, "name_ja": "ETF", "sector33": "9999", "scale_category": "-"}],
            feature_rows=[feat_row(code)],
            quote_rows=_rising_bars_rows(code),
        )
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        assert run_scan(persist=False) == []

    def test_top_n_per_setup_caps_the_number_of_new_drafts(self, monkeypatch):
        codes = [f"1000{i}" for i in range(5)]
        db = _mock_db(
            setups=[BREAKOUT],
            sec_rows=[sec_row(c) for c in codes],
            feature_rows=[feat_row(c) for c in codes],
            quote_rows=[row for c in codes for row in _rising_bars_rows(c)],
        )
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        drafts = run_scan(top_n_per_setup=2, persist=False)
        assert len(drafts) == 2

    def test_a_code_missing_the_latest_sessions_bar_is_skipped(self, monkeypatch):
        # features exist for as_of, but daily_quotes hasn't caught up yet —
        # must not draft off a stale bar.
        code = "72030"
        rows = _rising_bars_rows(code)[:-1]  # drop the most recent session
        db = _mock_db(
            setups=[BREAKOUT],
            sec_rows=[sec_row(code)],
            feature_rows=[feat_row(code)],
            quote_rows=rows,
        )
        monkeypatch.setattr("pipeline_py.setups.scan.SupabaseUpsertClient", lambda: db)

        assert run_scan(persist=False) == []
