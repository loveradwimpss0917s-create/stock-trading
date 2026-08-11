"""Shared utilities for the J-Quants/EDINET/JPX ingestion adapters."""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

JST = timezone(timedelta(hours=9))

T = TypeVar("T")


class TokenBucketRateLimiter:
    """Limits calls to at most `max_calls` per `period_seconds` sliding window.

    `sleep_fn`/`time_fn` are injectable so tests can exercise the throttling
    logic without waiting on a real clock.
    """

    def __init__(
        self,
        max_calls: int,
        period_seconds: float,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._sleep = sleep_fn
        self._time = time_fn
        self._calls: deque[float] = deque()

    def acquire(self) -> None:
        self._evict_expired()
        if len(self._calls) >= self.max_calls:
            wait = self.period_seconds - (self._time() - self._calls[0])
            if wait > 0:
                self._sleep(wait)
            self._evict_expired()
        self._calls.append(self._time())

    def _evict_expired(self) -> None:
        now = self._time()
        while self._calls and now - self._calls[0] >= self.period_seconds:
            self._calls.popleft()


class RetryExhausted(RuntimeError):
    """Raised when retry_with_backoff exhausts max_attempts."""


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    should_retry: Callable[[Exception], bool],
    max_attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Retries fn() with exponential backoff (2s, 4s, 8s, ... capped at max_delay)."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised as RetryExhausted below
            attempt += 1
            if attempt >= max_attempts or not should_retry(exc):
                raise RetryExhausted(f"failed after {attempt} attempt(s)") from exc
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            sleep_fn(delay)


def pad_security_code(code: str) -> str:
    """J-Quants uses 5-digit codes (7203 -> 72030); passes through if already 5 digits."""
    code = str(code).strip()
    if len(code) == 4 and code.isdigit():
        return code + "0"
    return code


def jst_to_utc(dt: datetime) -> datetime:
    """Attaches JST if naive, then converts to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(timezone.utc)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
