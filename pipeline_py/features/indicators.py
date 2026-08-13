"""Technical indicators, mirroring packages/core/src/indicators/*.ts.

Deliberately a port rather than a reimplementation: the feature store and
anything the frontend recomputes for display must agree exactly, so these
follow the TypeScript versions line for line (same seeding, same Wilder
smoothing, same NaN warm-up positions). The shared test vectors in
tests/test_indicators.py are the same ones the Vitest suite asserts.

Every function is causal — out[i] depends only on values[0..i] — which is
what makes the feature store safe to join on date without look-ahead.
"""
from __future__ import annotations

import math
from typing import Optional

NaN = float("nan")


def _is_nan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


def sma(values: list[float], period: int) -> list[float]:
    out = [NaN] * len(values)
    if period <= 0:
        return out
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: list[float], period: int) -> list[float]:
    out = [NaN] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], period: int = 14) -> list[float]:
    out = [NaN] * len(closes)
    if len(closes) <= period or period <= 0:
        return out
    gain = 0.0
    loss = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gain += d
        else:
            loss -= d
    gain /= period
    loss /= period
    out[period] = 100 - 100 / (1 + gain / (loss or 1e-9))
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = (gain * (period - 1) + max(d, 0)) / period
        loss = (loss * (period - 1) + max(-d, 0)) / period
        out[i] = 100 - 100 / (1 + gain / (loss or 1e-9))
    return out


def macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line = [
        NaN if (_is_nan(ema_fast[i]) or _is_nan(ema_slow[i])) else ema_fast[i] - ema_slow[i]
        for i in range(len(values))
    ]

    first_valid = next((i for i, v in enumerate(macd_line) if not _is_nan(v)), None)
    signal_line = [NaN] * len(values)
    if first_valid is not None:
        sig = ema(macd_line[first_valid:], signal)
        for i, v in enumerate(sig):
            signal_line[first_valid + i] = v

    hist = [
        NaN if (_is_nan(macd_line[i]) or _is_nan(signal_line[i])) else macd_line[i] - signal_line[i]
        for i in range(len(values))
    ]
    return macd_line, signal_line, hist


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    n = len(closes)
    tr = [NaN] * n
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    out = [NaN] * n
    if n <= period:
        return out
    prev = sum(tr[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> tuple[list[float], list[float], list[float]]:
    """Returns (+DI, -DI, ADX), using Wilder's running-sum smoothing."""
    n = len(closes)
    plus_dm = [NaN] * n
    minus_dm = [NaN] * n
    tr = [NaN] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    def smooth(values: list[float]) -> list[float]:
        out = [NaN] * n
        if n <= period:
            return out
        prev = sum(values[1 : period + 1])
        out[period] = prev
        for i in range(period + 1, n):
            prev = prev - prev / period + values[i]
            out[i] = prev
        return out

    s_tr = smooth(tr)
    s_plus = smooth(plus_dm)
    s_minus = smooth(minus_dm)

    plus_di = [NaN] * n
    minus_di = [NaN] * n
    dx = [NaN] * n
    for i in range(period, n):
        if _is_nan(s_tr[i]) or s_tr[i] == 0:
            continue
        plus_di[i] = 100 * (s_plus[i] / s_tr[i])
        minus_di[i] = 100 * (s_minus[i] / s_tr[i])
        total = plus_di[i] + minus_di[i]
        dx[i] = 0.0 if total == 0 else 100 * abs(plus_di[i] - minus_di[i]) / total

    adx_out = [NaN] * n
    first_dx = next((i for i, v in enumerate(dx) if not _is_nan(v)), None)
    if first_dx is not None and first_dx + period <= n:
        prev = sum(dx[first_dx : first_dx + period]) / period
        start = first_dx + period - 1
        adx_out[start] = prev
        for i in range(start + 1, n):
            prev = (prev * (period - 1) + dx[i]) / period
            adx_out[i] = prev
    return plus_di, minus_di, adx_out


def bollinger_bands(
    closes: list[float], period: int = 20, k: float = 2.0
) -> tuple[list[float], list[float], list[float]]:
    n = len(closes)
    middle = [NaN] * n
    upper = [NaN] * n
    lower = [NaN] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((v - mean) ** 2 for v in window) / period  # population, as in the TS version
        sd = math.sqrt(variance)
        middle[i] = mean
        upper[i] = mean + k * sd
        lower[i] = mean - k * sd
    return middle, upper, lower


def pct_return(closes: list[float], lag: int) -> list[float]:
    out = [NaN] * len(closes)
    for i in range(lag, len(closes)):
        base = closes[i - lag]
        if base:
            out[i] = (closes[i] - base) / base
    return out


def realized_vol(closes: list[float], period: int = 20) -> list[float]:
    """Stdev of daily log returns over `period`, annualized by sqrt(252)."""
    n = len(closes)
    out = [NaN] * n
    log_ret = [NaN] * n
    for i in range(1, n):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_ret[i] = math.log(closes[i] / closes[i - 1])
    for i in range(period, n):
        window = [r for r in log_ret[i - period + 1 : i + 1] if not _is_nan(r)]
        if len(window) < 2:
            continue
        mean = sum(window) / len(window)
        var = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
        out[i] = math.sqrt(var) * math.sqrt(252)
    return out


def distance_from_high(closes: list[float], period: int = 252) -> list[float]:
    """(close - rolling max) / rolling max; 0 at a new high, negative below.

    Uses however much history exists when shorter than `period` — the plan's
    window is under 252 sessions, so requiring a full year would emit nothing.
    """
    out: list[float] = [NaN] * len(closes)
    for i in range(len(closes)):
        window = closes[max(0, i - period + 1) : i + 1]
        peak = max(window)
        if peak:
            out[i] = (closes[i] - peak) / peak
    return out


def nan_to_none(x: float) -> Optional[float]:
    """NaN is not valid JSON; the DB columns are nullable for exactly this."""
    return None if _is_nan(x) else x
