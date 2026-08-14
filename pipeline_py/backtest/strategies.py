"""Cross-sectional strategies.

Restricted to the Edges the design blueprint marks as servable by J-Quants
Free alone (daily bars + earnings summaries): short-term reversal, 52-week
high proximity, and a low-volatility composite. Margin/short-interest and
investor-flow Edges need Standard/Premium data and are absent rather than
approximated.

Each strategy is dollar-neutral by construction (equal gross long and short)
so results reflect cross-sectional selection rather than market beta.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .engine import FeatureRow


def _ranked(values: dict[str, float], reverse: bool) -> list[str]:
    return [code for code, _ in sorted(values.items(), key=lambda kv: kv[1], reverse=reverse)]


def _long_short_weights(
    scores: dict[str, float], n_side: int, higher_is_long: bool
) -> dict[str, float]:
    """Top/bottom n_side by score, equal weight, gross exposure 1.0 per side."""
    if len(scores) < 2 * n_side:
        n_side = len(scores) // 2
    if n_side == 0:
        return {}

    ordered = _ranked(scores, reverse=higher_is_long)
    longs, shorts = ordered[:n_side], ordered[-n_side:]
    w = 1.0 / n_side
    weights = {c: w for c in longs}
    weights.update({c: -w for c in shorts})
    return weights


def _collect(features: dict[str, FeatureRow], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for code, row in features.items():
        v = row.values.get(key)
        if v is not None:
            out[code] = float(v)
    return out


@dataclass
class ShortTermReversal:
    """Buy recent losers, sell recent winners — the classic 1-week reversal.
    Feasible on daily bars alone."""

    n_side: int = 5
    lookback_key: str = "ret_5d"
    name: str = "short_term_reversal"

    def target_weights(self, asof: str, features: dict[str, FeatureRow]) -> dict[str, float]:
        scores = _collect(features, self.lookback_key)
        # higher_is_long=False: the biggest 5-day losers become the longs.
        return _long_short_weights(scores, self.n_side, higher_is_long=False)


@dataclass
class FiftyTwoWeekHigh:
    """Long names trading nearest their trailing high, short the most beaten
    down — the George & Hwang proximity effect."""

    n_side: int = 5
    name: str = "fifty_two_week_high"

    def target_weights(self, asof: str, features: dict[str, FeatureRow]) -> dict[str, float]:
        scores = _collect(features, "dist_52w_high")
        return _long_short_weights(scores, self.n_side, higher_is_long=True)


@dataclass
class LowVolatility:
    """Long low realized vol, short high — the low-beta anomaly."""

    n_side: int = 5
    name: str = "low_volatility"

    def target_weights(self, asof: str, features: dict[str, FeatureRow]) -> dict[str, float]:
        scores = _collect(features, "vol_20d")
        # higher_is_long=False so the *lowest* vol names are the longs.
        return _long_short_weights(scores, self.n_side, higher_is_long=False)


@dataclass
class RsiMeanReversion:
    """Long oversold (low RSI), short overbought."""

    n_side: int = 5
    name: str = "rsi_mean_reversion"

    def target_weights(self, asof: str, features: dict[str, FeatureRow]) -> dict[str, float]:
        scores = _collect(features, "rsi_14")
        return _long_short_weights(scores, self.n_side, higher_is_long=False)


def default_strategies(n_side: int = 5) -> list:
    return [
        ShortTermReversal(n_side=n_side),
        FiftyTwoWeekHigh(n_side=n_side),
        LowVolatility(n_side=n_side),
        RsiMeanReversion(n_side=n_side),
    ]
