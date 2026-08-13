"""Same vectors as packages/core's Vitest suite.

If these two suites ever disagree, the feature store and anything the
frontend recomputes have silently diverged — which is exactly the kind of
bug that shows up as an unreproducible backtest.
"""
import math

from pipeline_py.features import indicators as ind


def is_nan(x):
    return isinstance(x, float) and math.isnan(x)


class TestRsi:
    def test_matches_hand_computed_wilder_rsi(self):
        # closes 10,12,11,15 period=2 -> deltas +2,-1,+4
        # seed: gain=1, loss=0.5 -> 100-100/3
        # i=3:  gain=2.5, loss=0.25 -> 100-100/11
        out = ind.rsi([10, 12, 11, 15], 2)
        assert is_nan(out[0]) and is_nan(out[1])
        assert out[2] == 100 - 100 / 3
        assert out[3] == 100 - 100 / 11

    def test_strictly_increasing_series_pins_to_100(self):
        out = ind.rsi([1, 2, 3, 4, 5], 2)
        for v in out[2:]:
            assert abs(v - 100) < 1e-6


class TestEma:
    def test_matches_hand_computed_ema(self):
        # 1..5, period 3, k=0.5; seed SMA(1,2,3)=2
        out = ind.ema([1, 2, 3, 4, 5], 3)
        assert is_nan(out[0]) and is_nan(out[1])
        assert out[2] == 2
        assert out[3] == 3
        assert out[4] == 4

    def test_all_nan_when_shorter_than_period(self):
        assert all(is_nan(v) for v in ind.ema([1, 2], 5))


class TestMacd:
    def test_matches_hand_computed_macd(self):
        macd_line, signal, hist = ind.macd([1, 2, 3, 4, 5, 6], 2, 3, 2)
        assert is_nan(macd_line[0]) and is_nan(macd_line[1])
        assert macd_line[2:] == [0.5, 0.5, 0.5, 0.5]
        assert is_nan(signal[2])
        assert signal[3:] == [0.5, 0.5, 0.5]
        assert is_nan(hist[2])
        for v in hist[3:]:
            assert abs(v) < 1e-10


class TestAtr:
    def test_matches_hand_computed_atr(self):
        highs = [10, 12, 13, 14, 16]
        lows = [8, 9, 10, 11, 12]
        closes = [9, 11, 12, 13, 15]
        # TR = _,3,3,3,4 ; period 2 -> out[2]=3, out[3]=3, out[4]=3.5
        out = ind.atr(highs, lows, closes, 2)
        assert is_nan(out[0]) and is_nan(out[1])
        assert out[2] == 3
        assert out[3] == 3
        assert out[4] == 3.5


class TestAdx:
    def test_clean_uptrend_pins_dx_to_100(self):
        # Rising highs and lows -> -DM always 0 -> DX == 100 regardless of TR.
        # period=1 makes Wilder smoothing a pass-through, so it's hand-checkable.
        highs = [10, 12, 14, 16, 18, 20]
        lows = [8, 9, 10, 11, 12, 13]
        closes = [8, 9, 10, 11, 12, 13]
        plus_di, minus_di, adx_line = ind.adx(highs, lows, closes, 1)

        assert abs(plus_di[1] - 50) < 1e-6
        assert abs(plus_di[2] - 40) < 1e-6
        assert abs(plus_di[5] - 25) < 1e-6
        for v in minus_di[1:]:
            assert abs(v) < 1e-10
        for v in adx_line[1:]:
            assert abs(v - 100) < 1e-6


class TestBollingerBands:
    def test_matches_textbook_population_stddev_example(self):
        # [2,4,4,4,5,5,7,9]: mean 5, population sd 2
        closes = [2, 4, 4, 4, 5, 5, 7, 9]
        middle, upper, lower = ind.bollinger_bands(closes, 8, 2)
        assert middle[7] == 5
        assert upper[7] == 9
        assert lower[7] == 1
        assert all(is_nan(v) for v in middle[:7])


class TestSma:
    def test_rolling_mean(self):
        out = ind.sma([1, 2, 3, 4, 5], 3)
        assert is_nan(out[0]) and is_nan(out[1])
        assert out[2] == 2
        assert out[3] == 3
        assert out[4] == 4


class TestPctReturn:
    def test_simple_return_over_lag(self):
        out = ind.pct_return([100, 110, 121], 1)
        assert is_nan(out[0])
        assert abs(out[1] - 0.10) < 1e-12
        assert abs(out[2] - 0.10) < 1e-12

    def test_zero_base_leaves_nan_rather_than_dividing(self):
        out = ind.pct_return([0, 5], 1)
        assert is_nan(out[1])


class TestDistanceFromHigh:
    def test_zero_at_a_new_high_and_negative_below(self):
        out = ind.distance_from_high([100, 120, 90], 252)
        assert out[0] == 0
        assert out[1] == 0
        assert abs(out[2] - (90 - 120) / 120) < 1e-12


class TestRealizedVol:
    def test_constant_series_has_zero_volatility(self):
        out = ind.realized_vol([100] * 25, 20)
        assert abs(out[24]) < 1e-12

    def test_warmup_is_nan(self):
        out = ind.realized_vol([100, 101, 102], 20)
        assert all(is_nan(v) for v in out)
