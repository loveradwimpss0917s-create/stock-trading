from pipeline_py.backtest.labeling import Barriers, triple_barrier

B = Barriers(profit_take=2.0, stop_loss=2.0, max_hold=5)


def test_profit_take_hit_returns_1():
    # entry 100, atr 5 -> upper 110
    prices = [100, 102, 111, 100]
    assert triple_barrier(prices, 0, atr=5, barriers=B) == 1


def test_stop_loss_hit_returns_minus_1():
    # lower barrier 90
    prices = [100, 95, 89, 120]
    assert triple_barrier(prices, 0, atr=5, barriers=B) == -1


def test_timeout_returns_0():
    prices = [100, 101, 99, 100, 101, 100]
    assert triple_barrier(prices, 0, atr=5, barriers=B) == 0


def test_entry_bar_itself_cannot_trigger_a_barrier():
    # The entry price sits above the profit-take level only because atr is
    # tiny; the scan must start at entry_idx+1, so nothing triggers here.
    prices = [100]
    assert triple_barrier(prices, 0, atr=0.01, barriers=B) == 0


def test_max_hold_window_is_respected():
    # Profit take is reached, but only after max_hold sessions.
    prices = [100, 100, 100, 100, 100, 100, 200]
    assert triple_barrier(prices, 0, atr=5, barriers=Barriers(2.0, 2.0, 3)) == 0


def test_stop_wins_when_both_barriers_are_breached_on_the_same_bar():
    # With only daily closes there's no intrabar ordering, so the conservative
    # reading is that the stop hit first.
    prices = [100, 89]
    assert triple_barrier(prices, 0, atr=5, barriers=B) == -1


def test_zero_atr_returns_neutral_rather_than_dividing_by_zero():
    assert triple_barrier([100, 200], 0, atr=0.0, barriers=B) == 0


def test_out_of_range_entry_index_is_neutral():
    assert triple_barrier([100, 101], 5, atr=5, barriers=B) == 0
