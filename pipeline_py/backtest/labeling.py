"""Triple Barrier labeling (López de Prado).

Port of packages/backtest/src/labeling.ts's intent, with the barriers scaled
by ATR so a 2% move means something different for a volatile name than a
quiet one.

Used for the Phase-2 ML layer rather than by the backtester itself; kept
here so the label definition lives next to the execution assumptions it has
to agree with.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Barriers:
    profit_take: float  # in ATR multiples
    stop_loss: float  # in ATR multiples, positive
    max_hold: int  # sessions


def triple_barrier(
    prices: list[float], entry_idx: int, atr: float, barriers: Barriers
) -> int:
    """Returns 1 (profit take hit first), -1 (stop first), 0 (timed out).

    Scans forward from entry_idx+1, so the entry bar itself cannot trigger a
    barrier — the position isn't on until after the fill.
    """
    if entry_idx < 0 or entry_idx >= len(prices) or atr <= 0:
        return 0

    entry = prices[entry_idx]
    upper = entry + barriers.profit_take * atr
    lower = entry - barriers.stop_loss * atr
    last = min(entry_idx + barriers.max_hold, len(prices) - 1)

    for i in range(entry_idx + 1, last + 1):
        # Checked in this order because with only daily closes there is no way
        # to know which barrier a bar touched first; taking the stop first is
        # the conservative reading.
        if prices[i] <= lower:
            return -1
        if prices[i] >= upper:
            return 1
    return 0
