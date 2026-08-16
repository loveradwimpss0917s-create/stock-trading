"""Turns a Setup's symbolic rules into concrete numbers, once, at draft time.

A trader who decides "buy if it breaks 4,250" does not recompute that level
every day as the rolling 20-day high drifts — the number is fixed the moment
the plan is made. So every rolling reference (high_20, low_10, prior_high,
ma_75, an ATR-multiple drawdown) is resolved into a plain price HERE, at the
session the plan is drafted on, and only the resolved number is stored on
`trade_plans`. This has a real consequence for the runtime side: the daily
batch that advances armed plans (`advance-plans`) never has to re-derive a
rolling window — it only compares a session's close against a frozen number
already sitting in `trigger_price` / `invalidation`. That keeps the one place
where a look-ahead bug could hide (recomputing "the 20-day high" using bars
that didn't exist when the plan was made) out of the runtime path entirely.

All rolling windows and the candidate_rule are evaluated using bars up to and
including `idx` — the session index the scan runs for, i.e. "today" as of
the daily batch's EOD data. This mirrors build_features.py's `known_from`
convention: nothing here reaches past the session it claims to know about.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from datetime import timedelta
from typing import Any, Optional

from ..screening.evaluate import Bar


def rolling_high(bars: list[Bar], idx: int, n: int) -> Optional[float]:
    """Highest close over the n sessions ending at and including idx."""
    if idx - n + 1 < 0:
        return None
    window = bars[idx - n + 1 : idx + 1]
    return max(b.close for b in window)


def rolling_low(bars: list[Bar], idx: int, n: int) -> Optional[float]:
    if idx - n + 1 < 0:
        return None
    window = bars[idx - n + 1 : idx + 1]
    return min(b.close for b in window)


def consecutive_down_days(bars: list[Bar], idx: int) -> int:
    """How many sessions in a row, ending at idx, closed below the prior
    session's close. 0 if idx itself was not a down day."""
    count = 0
    i = idx
    while i > 0 and bars[i].close < bars[i - 1].close:
        count += 1
        i -= 1
    return count


def add_trading_days(start: str, n: int) -> str:
    """start + n weekdays, skipping Sat/Sun only. JPX holidays are not
    modeled — an expiry landing on one just expires a session early, which
    errs toward discarding a stale plan sooner rather than holding it open
    on a phantom session. Precision here is not worth a holiday calendar."""
    d = date_cls.fromisoformat(start)
    remaining = n
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return d.isoformat()


def _resolve_ref(ref: str, bars: list[Bar], idx: int, features_row: dict) -> Optional[float]:
    if ref == "high_20":
        return rolling_high(bars, idx, 20)
    if ref == "low_10":
        return rolling_low(bars, idx, 10)
    if ref == "prior_high":
        # Resolved at draft time as *this* session's high — the level the
        # next session's close must reclaim to confirm the setup.
        return bars[idx].high
    if ref == "ma_75":
        v = features_row.get("ma_75")
        return float(v) if v is not None else None
    raise ValueError(f"unknown ref: {ref!r}")


@dataclass(frozen=True)
class ResolvedLevels:
    trigger_price: float
    trigger_condition: dict[str, Any]
    invalidation: dict[str, Any]
    stop_planned: float
    target_planned: float
    expires_on: str


def resolve_plan_levels(
    setup: dict, bars: list[Bar], idx: int, features_row: dict
) -> Optional[ResolvedLevels]:
    """Concrete trigger/stop/target/invalidation for a plan drafted on
    bars[idx]. Returns None if a required rolling window isn't available yet
    (e.g. fewer than 20 sessions of history) — a plan can't be drafted on an
    unresolved level."""
    reference_close = bars[idx].close
    atr = features_row.get("atr_14")
    if atr is None:
        return None
    atr = float(atr)

    trig = setup["trigger_rule"]
    if trig["type"] != "close_above":
        raise ValueError(f"unsupported trigger type: {trig['type']!r}")
    trigger_level = _resolve_ref(trig["ref"], bars, idx, features_row)
    if trigger_level is None:
        return None
    buffer_pct = trig.get("buffer_pct", 0.0)
    trigger_price = round(trigger_level * (1 + buffer_pct), 2)

    inv = setup["invalidation_rule"]
    if inv["type"] == "close_below":
        inv_level = _resolve_ref(inv["ref"], bars, idx, features_row)
        if inv_level is None:
            return None
        invalidation = {"type": "close_below", "level": round(inv_level, 2), "source_ref": inv["ref"]}
    elif inv["type"] == "additional_atr_drawdown":
        inv_level = reference_close - inv["mult"] * atr
        invalidation = {
            "type": "close_below",
            "level": round(inv_level, 2),
            "source_ref": "additional_atr_drawdown",
        }
    else:
        raise ValueError(f"unsupported invalidation type: {inv['type']!r}")

    stop_rule, target_rule = setup["stop_rule"], setup["target_rule"]
    if stop_rule["type"] != "atr_mult" or target_rule["type"] != "atr_mult":
        raise ValueError("only atr_mult stop/target rules are supported")
    stop_planned = round(trigger_price - stop_rule["mult"] * atr, 2)
    target_planned = round(trigger_price + target_rule["mult"] * atr, 2)

    # Whichever of stop or invalidation is tighter fires first — that's a
    # normal, expected outcome and not a defect (a thesis invalidation is
    # often meant to fire before a wider ATR stop ever would). What IS
    # self-contradictory is invalidation sitting at or above the trigger
    # itself: the thesis would already be dead before the position could
    # even be entered. That case must not resolve.
    if invalidation["level"] >= trigger_price:
        return None

    expires_on = add_trading_days(bars[idx].date, setup["expiry_bars"])

    return ResolvedLevels(
        trigger_price=trigger_price,
        trigger_condition={"type": "close_above", "level": trigger_price, "source_rule": trig},
        invalidation=invalidation,
        stop_planned=stop_planned,
        target_planned=target_planned,
        expires_on=expires_on,
    )


def passes_candidate_rule(rule: dict, row: dict, bars: list[Bar], idx: int) -> bool:
    """row: a features_row merged with close/turnover_value, as build by the
    scan batch. All conditions in `rule` must hold (AND)."""
    close = row.get("close")
    if close is None:
        return False
    close = float(close)

    for key, threshold in rule.items():
        if key == "close_above_ma25":
            ma = row.get("ma_25")
            if ma is None or not ((close > float(ma)) == bool(threshold)):
                return False
        elif key == "close_above_ma75":
            ma = row.get("ma_75")
            if ma is None or not ((close > float(ma)) == bool(threshold)):
                return False
        elif key == "dist_from_high20_pct_max":
            high20 = rolling_high(bars, idx, 20)
            if high20 is None or high20 <= 0:
                return False
            if (high20 - close) / high20 > threshold:
                return False
        elif key == "dist_to_ma25_pct_max":
            ma = row.get("ma_25")
            if ma is None or close <= 0:
                return False
            if abs(close - float(ma)) / close > threshold:
                return False
        elif key == "adx_14_min":
            v = row.get("adx_14")
            if v is None or float(v) < threshold:
                return False
        elif key == "ret_20d_min":
            v = row.get("ret_20d")
            if v is None or float(v) < threshold:
                return False
        elif key == "atr_pct_min":
            atr = row.get("atr_14")
            if atr is None or close <= 0 or float(atr) / close < threshold:
                return False
        elif key == "consecutive_down_days_min":
            if consecutive_down_days(bars, idx) < threshold:
                return False
        elif key == "min_turnover":
            v = row.get("turnover_value")
            if v is None or float(v) < threshold:
                return False
        else:
            raise ValueError(f"unknown candidate_rule key: {key!r}")
    return True
