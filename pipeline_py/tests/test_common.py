from datetime import datetime

import pytest

from pipeline_py.ingest.common import (
    RetryExhausted,
    TokenBucketRateLimiter,
    jst_to_utc,
    pad_security_code,
    retry_with_backoff,
)


class FakeClock:
    """Deterministic time/sleep pair: sleep() advances the clock instead of blocking."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_pad_security_code_pads_4_digit_codes():
    assert pad_security_code("7203") == "72030"


def test_pad_security_code_passes_through_5_digit_codes():
    assert pad_security_code("72030") == "72030"


def test_rate_limiter_allows_calls_under_the_limit_without_sleeping():
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(5, 60.0, sleep_fn=clock.sleep, time_fn=clock.time)
    for _ in range(5):
        limiter.acquire()
    assert clock.slept == []


def test_rate_limiter_sleeps_when_the_limit_is_exceeded():
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(5, 60.0, sleep_fn=clock.sleep, time_fn=clock.time)
    for _ in range(5):
        limiter.acquire()
    limiter.acquire()  # 6th call within the same 60s window must wait
    assert clock.slept == [60.0]


def test_rate_limiter_does_not_sleep_once_the_window_has_elapsed():
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(5, 60.0, sleep_fn=clock.sleep, time_fn=clock.time)
    for _ in range(5):
        limiter.acquire()
    clock.now += 60.0
    limiter.acquire()
    assert clock.slept == []


def test_retry_with_backoff_retries_then_succeeds():
    clock = FakeClock()
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = retry_with_backoff(
        flaky, should_retry=lambda exc: True, sleep_fn=clock.sleep, max_attempts=5
    )
    assert result == "ok"
    assert attempts["n"] == 3
    assert clock.slept == [2.0, 4.0]  # exponential backoff: 2s, then 4s


def test_retry_with_backoff_raises_after_max_attempts():
    clock = FakeClock()

    def always_fails() -> None:
        raise ValueError("persistent")

    with pytest.raises(RetryExhausted):
        retry_with_backoff(
            always_fails, should_retry=lambda exc: True, sleep_fn=clock.sleep, max_attempts=3
        )
    assert len(clock.slept) == 2  # backs off between attempts 1->2 and 2->3, then gives up


def test_retry_with_backoff_does_not_retry_non_retryable_errors():
    clock = FakeClock()
    attempts = {"n": 0}

    def fails_once() -> None:
        attempts["n"] += 1
        raise ValueError("not retryable")

    with pytest.raises(RetryExhausted):
        retry_with_backoff(
            fails_once, should_retry=lambda exc: False, sleep_fn=clock.sleep, max_attempts=5
        )
    assert attempts["n"] == 1
    assert clock.slept == []


def test_jst_to_utc_converts_naive_datetime_as_jst():
    naive = datetime(2026, 8, 9, 18, 30, 0)  # 18:30 JST
    utc = jst_to_utc(naive)
    assert utc.hour == 9  # JST is UTC+9
    assert utc.utcoffset().total_seconds() == 0
