from datetime import date, timedelta
from unittest.mock import MagicMock

from pipeline_py.regime.compute import classify, compute_regime, run
from pipeline_py.screening.evaluate import Bar

AS_OF = "2026-05-22"


def bars_for(code, closes, end=AS_OF):
    """Weekday-spaced bars ending on `end`, most recent close last."""
    d = date.fromisoformat(end)
    dates = []
    while len(dates) < len(closes):
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d -= timedelta(days=1)
    dates.reverse()
    return [Bar(dd, c, c + 1, c - 1, c) for dd, c in zip(dates, closes)]


class TestClassify:
    def test_offense_requires_both_thresholds(self):
        assert classify(0.60, 0.55) == "offense"
        assert classify(0.60, 0.54) == "neutral"  # breadth up, advancers not
        assert classify(0.59, 0.55) == "neutral"

    def test_defense_requires_both_thresholds(self):
        assert classify(0.40, 0.45) == "defense"
        assert classify(0.41, 0.45) == "neutral"

    def test_the_middle_is_neutral(self):
        assert classify(0.50, 0.50) == "neutral"


class TestComputeRegime:
    def test_breadth_counts_only_codes_with_a_bar_on_as_of(self):
        # code B has no session dated as_of (stale) and must not count.
        features = {"A": {"ma_25": 95.0, "ma_75": 90.0}, "B": {"ma_25": 95.0, "ma_75": 90.0}}
        bars = {
            "A": bars_for("A", [90, 92, 96, 98, 100]),
            "B": bars_for("B", [90, 92, 96, 98], end="2026-05-21"),  # one day stale
        }
        snap = compute_regime(features, bars, AS_OF)
        assert snap["computed_from_n"] == 1

    def test_pct_above_ma25_reflects_the_close_vs_the_feature_value(self):
        features = {
            "A": {"ma_25": 90.0, "ma_75": 80.0},   # close 100 > both
            "B": {"ma_25": 110.0, "ma_75": 120.0},  # close 100 < both
        }
        bars = {"A": bars_for("A", [95, 97, 100]), "B": bars_for("B", [105, 102, 100])}
        snap = compute_regime(features, bars, AS_OF)
        assert snap["pct_above_ma25"] == 0.5
        assert snap["pct_above_ma75"] == 0.5

    def test_new_high_minus_low_counts_20_session_extremes(self):
        # A closes at its own rolling high; B closes at its own rolling low.
        features = {"A": {"ma_25": 1, "ma_75": 1}, "B": {"ma_25": 1, "ma_75": 1}}
        bars = {
            "A": bars_for("A", list(range(80, 105))),   # rising -> new high
            "B": bars_for("B", list(range(105, 80, -1))),  # falling -> new low
        }
        snap = compute_regime(features, bars, AS_OF)
        assert snap["new_high_minus_low"] == 0  # one of each cancels out

    def test_dispersion_is_zero_when_every_return_is_identical(self):
        features = {"A": {}, "B": {}}
        bars = {"A": bars_for("A", [100, 101]), "B": bars_for("B", [50, 50.5])}  # both +1%
        snap = compute_regime(features, bars, AS_OF)
        assert abs(snap["dispersion"]) < 1e-9

    def test_dispersion_is_positive_when_returns_diverge(self):
        features = {"A": {}, "B": {}}
        bars = {"A": bars_for("A", [100, 110]), "B": bars_for("B", [100, 90])}
        snap = compute_regime(features, bars, AS_OF)
        assert snap["dispersion"] > 0

    def test_no_matching_codes_returns_none_rather_than_dividing_by_zero(self):
        assert compute_regime({}, {}, AS_OF) is None

    def test_a_single_bar_with_no_prior_session_is_excluded_from_adv_decline(self):
        # Advance/decline needs a prior close; a code with only one bar in
        # the whole store can still count for ma25 but must not corrupt
        # the advancer count or the dispersion series.
        features = {"A": {"ma_25": 90.0, "ma_75": 90.0}}
        bars = {"A": bars_for("A", [100])}
        snap = compute_regime(features, bars, AS_OF)
        assert snap is None  # len(bars) < 2 guard excludes it entirely


class TestRun:
    def test_persists_exactly_one_row_via_upsert(self, monkeypatch):
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.select.side_effect = lambda table, params: [{"date": AS_OF}]

        def select_all(table, params):
            if table == "securities_with_data":
                return [{"code": "A", "sector33": "3650", "scale_category": "TOPIX Core30"}]
            if table == "features":
                return [{"code": "A", "ma_25": 90.0, "ma_75": 80.0}]
            if table == "daily_quotes":
                return [
                    {"code": "A", "date": d, "open": c, "high": c + 1, "low": c - 1, "close": c}
                    for d, c in zip(["2026-05-21", AS_OF], [98, 100])
                ]
            raise AssertionError(table)

        db.select_all.side_effect = select_all
        monkeypatch.setattr("pipeline_py.regime.compute.SupabaseUpsertClient", lambda: db)

        snap = run(persist=True)
        assert snap["date"] == AS_OF
        db.upsert.assert_called_once()
        args, kwargs = db.upsert.call_args
        assert args[0] == "regime_snapshots"
        assert kwargs["on_conflict"] == "date"

    def test_a_fund_in_securities_does_not_pollute_breadth(self, monkeypatch):
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.select.side_effect = lambda table, params: [{"date": AS_OF}]

        def select_all(table, params):
            if table == "securities_with_data":
                return [
                    {"code": "A", "sector33": "3650", "scale_category": "TOPIX Core30"},
                    {"code": "ETF", "sector33": "9999", "scale_category": "-"},
                ]
            if table == "features":
                return [
                    {"code": "A", "ma_25": 90.0, "ma_75": 80.0},
                    {"code": "ETF", "ma_25": 90.0, "ma_75": 80.0},
                ]
            if table == "daily_quotes":
                return [
                    {"code": c, "date": d, "open": v, "high": v + 1, "low": v - 1, "close": v}
                    for c in ("A", "ETF")
                    for d, v in zip(["2026-05-21", AS_OF], [98, 100])
                ]
            raise AssertionError(table)

        db.select_all.side_effect = select_all
        monkeypatch.setattr("pipeline_py.regime.compute.SupabaseUpsertClient", lambda: db)

        snap = run(persist=False)
        assert snap["computed_from_n"] == 1
