import math
from datetime import date, timedelta

from pipeline_py.features.build_features import MIN_BARS, build_rows, market_close_utc

START = date(2026, 1, 5)


def make_bars(n: int, start_close: float = 100.0) -> list[dict]:
    """Consecutive calendar days — the builder only cares about ordering, not
    about which days are actually sessions."""
    bars = []
    for i in range(n):
        close = start_close + i
        bars.append(
            {
                "date": (START + timedelta(days=i)).isoformat(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
            }
        )
    return bars


def test_market_close_utc_converts_1500_jst_to_0600_utc():
    # JST is UTC+9, so a 15:00 close is 06:00 the same UTC day.
    assert market_close_utc("2026-05-20").startswith("2026-05-20T06:00:00")


def test_known_from_is_the_bar_date_close_not_ingestion_time():
    rows = build_rows("72030", make_bars(40))
    for row in rows:
        # The stamp must fall on the row's own trading day — stamping "now"
        # would make every historical feature look knowable today.
        assert row["known_from"].startswith(row["date"])


def test_returns_nothing_when_history_is_shorter_than_warmup():
    assert build_rows("72030", make_bars(MIN_BARS - 1)) == []


def test_emits_one_row_per_bar_with_the_expected_shape():
    bars = make_bars(40)
    rows = build_rows("72030", bars)
    assert len(rows) == len(bars)
    assert rows[0]["code"] == "72030"
    assert rows[0]["feature_set"] == "v1"
    assert rows[0]["date"] == bars[0]["date"]


def test_nan_warmup_values_become_none_not_nan():
    # NaN isn't valid JSON — it would be rejected by PostgREST, or worse,
    # serialized as something the numeric columns silently accept.
    rows = build_rows("72030", make_bars(40))
    for row in rows:
        for key, value in row.items():
            assert not (isinstance(value, float) and math.isnan(value)), f"{key} is NaN"
    # The first row is inside every indicator's warm-up, so it should be null.
    assert rows[0]["rsi_14"] is None
    assert rows[0]["ma_25"] is None


def test_late_rows_have_indicators_populated():
    rows = build_rows("72030", make_bars(60))
    last = rows[-1]
    for key in ("ret_1d", "ret_5d", "ret_20d", "ma_25", "ema_12", "ema_26", "rsi_14", "macd"):
        assert last[key] is not None, f"{key} unexpectedly null on a warmed-up row"


def test_features_are_causal_extending_history_does_not_change_earlier_rows():
    """The core look-ahead guarantee: a row dated D must be identical whether
    or not the series continues past D."""
    short = build_rows("72030", make_bars(45))
    long = build_rows("72030", make_bars(80))
    by_date = {r["date"]: r for r in long}
    for row in short:
        assert by_date[row["date"]] == row
