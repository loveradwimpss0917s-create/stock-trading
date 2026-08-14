"""Turns the feature store into ranked trade candidates per theme.

Scope and honesty, up front: none of these themes has cleared the
DSR/PBO gate. They are screens — a defensible, repeatable way to narrow
a universe — not validated edges. The screening output and the validation
verdict are deliberately separate surfaces so one is never mistaken for the
other.

`as_of` is the last session in the feature store, not today's date. On the
Free plan that is ~12 weeks behind; on a paid plan the same code produces
current signals with no change. Callers must display as_of.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

# Entry is assumed at the next session's open, matching the backtester. Stop
# and target are ATR multiples so a volatile name gets proportionally wider
# levels rather than a fixed percentage that would be noise on one stock and
# a straitjacket on another.
STOP_ATR_MULT = {"day": 1.0, "swing": 1.8}
TARGET_ATR_MULT = {"day": 1.5, "swing": 3.0}

# A name that barely moves cannot pay for its own spread on a day trade.
MIN_ATR_PCT_DAY = 0.012  # 1.2% of price
MIN_TURNOVER = 300_000_000  # ~3億円/日. Below this, slippage dominates.


@dataclass
class Candidate:
    code: str
    score: float
    side: str
    entry_ref: float
    stop_price: float
    target_price: float
    atr_14: float
    rr_ratio: float
    rationale: dict[str, Any]


def _z(values: dict[str, float]) -> dict[str, float]:
    """Cross-sectional z-score. Ranking within the day's universe is what
    makes scores comparable across names with different price levels."""
    if len(values) < 2:
        return {k: 0.0 for k in values}
    xs = list(values.values())
    mean = math.fsum(xs) / len(xs)
    var = math.fsum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: (v - mean) / sd for k, v in values.items()}


def _collect(rows: dict[str, dict], key: str) -> dict[str, float]:
    out = {}
    for code, r in rows.items():
        v = r.get(key)
        if v is not None:
            out[code] = float(v)
    return out


def _component_scores(rows: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Builds every named component the theme weights can reference.

    Each is z-scored so weights are on a comparable scale; a raw ATR in yen
    and a raw RSI in points cannot be added together meaningfully.
    """
    comp: dict[str, dict[str, float]] = {}

    comp["ret_1d"] = _z(_collect(rows, "ret_1d"))
    comp["ret_5d"] = _z(_collect(rows, "ret_5d"))
    comp["ret_20d"] = _z(_collect(rows, "ret_20d"))
    comp["dist_52w_high"] = _z(_collect(rows, "dist_52w_high"))
    comp["adx_14"] = _z(_collect(rows, "adx_14"))
    comp["vol_20d"] = _z(_collect(rows, "vol_20d"))

    # Inverted views, so a weight is always "more of this is better".
    comp["ret_1d_neg"] = {k: -v for k, v in comp["ret_1d"].items()}
    comp["ret_5d_neg"] = {k: -v for k, v in comp["ret_5d"].items()}

    # RSI below 50 scores positively and scales with how oversold it is.
    rsi = _collect(rows, "rsi_14")
    comp["rsi_oversold"] = _z({k: (50.0 - v) for k, v in rsi.items()})

    # ATR as a fraction of price — the tradable range, comparable across
    # names in a way that yen-denominated ATR is not.
    atr_pct = {}
    abs_ret = {}
    above_ma25 = {}
    above_ma75 = {}
    for code, r in rows.items():
        close = r.get("close")
        atr = r.get("atr_14")
        if close and atr:
            atr_pct[code] = float(atr) / float(close)
        if r.get("ret_1d") is not None:
            abs_ret[code] = abs(float(r["ret_1d"]))
        if close and r.get("ma_25"):
            above_ma25[code] = 1.0 if float(close) > float(r["ma_25"]) else 0.0
        if close and r.get("ma_75"):
            above_ma75[code] = 1.0 if float(close) > float(r["ma_75"]) else 0.0

    comp["atr_pct"] = _z(atr_pct)
    comp["abs_ret_1d"] = _z(abs_ret)
    # Binary gates left un-z-scored: they are on/off conditions, and
    # z-scoring them would let a universe where everyone is above the MA
    # still penalise most of it.
    comp["above_ma25"] = above_ma25
    comp["above_ma75"] = above_ma75
    return comp


def _passes_liquidity(row: dict, horizon: str) -> tuple[bool, Optional[str]]:
    turnover = row.get("turnover_value")
    if turnover is not None and float(turnover) < MIN_TURNOVER:
        return False, "低流動性"
    if horizon == "day":
        close, atr = row.get("close"), row.get("atr_14")
        if close and atr and float(atr) / float(close) < MIN_ATR_PCT_DAY:
            return False, "値幅不足"
    return True, None


def score_theme(
    rows: dict[str, dict],
    theme: dict,
    horizon: str,
    top_n: int = 10,
) -> list[Candidate]:
    """rows: code -> {feature columns + close/turnover_value}."""
    definition = theme.get("definition") or {}

    if theme["kind"] == "sector":
        wanted = set(definition.get("sector33") or [])
        pool = {c: r for c, r in rows.items() if r.get("sector33") in wanted}
        # A sector theme has no factor weights of its own; rank its members by
        # a trend-following default so the list is ordered by something
        # defensible rather than by code.
        weights = {"ret_20d": 1.0, "dist_52w_high": 0.6, "adx_14": 0.4}
    else:
        pool = dict(rows)
        weights = definition.get("weights") or {}

    if not pool or not weights:
        return []

    comp = _component_scores(pool)

    scored: list[Candidate] = []
    for code, row in pool.items():
        ok, _reason = _passes_liquidity(row, horizon)
        if not ok:
            continue

        close = row.get("close")
        atr = row.get("atr_14")
        if not close or not atr or float(atr) <= 0:
            continue
        close = float(close)
        atr = float(atr)

        breakdown = {}
        total = 0.0
        for key, w in weights.items():
            v = comp.get(key, {}).get(code)
            if v is None:
                continue
            contribution = float(w) * v
            breakdown[key] = round(contribution, 4)
            total += contribution
        if not breakdown:
            continue

        stop = close - STOP_ATR_MULT[horizon] * atr
        target = close + TARGET_ATR_MULT[horizon] * atr
        risk = close - stop
        reward = target - close
        scored.append(
            Candidate(
                code=code,
                score=total,
                side="long",  # long-only screens; shorts need borrow data we lack
                entry_ref=close,
                stop_price=round(stop, 2),
                target_price=round(target, 2),
                atr_14=atr,
                rr_ratio=round(reward / risk, 2) if risk > 0 else 0.0,
                rationale={
                    "components": breakdown,
                    "atr_pct": round(atr / close, 4),
                    "stop_atr_mult": STOP_ATR_MULT[horizon],
                    "target_atr_mult": TARGET_ATR_MULT[horizon],
                },
            )
        )

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:top_n]
