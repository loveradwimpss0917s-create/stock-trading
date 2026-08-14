"""Probability of Backtest Overfitting via CSCV
(Bailey, Borwein, López de Prado, Zhu 2017).

The question PBO answers: when you pick the best strategy on one half of
the data, how often does it land in the *bottom* half on the other? If that
happens about half the time, your selection procedure carries no
information — you were fitting noise, however good the winner's backtest
looked.

Procedure:
  1. Split the T x N return matrix into S equal blocks (S even).
  2. For every way of choosing S/2 blocks as in-sample:
     - pick the strategy with the best IS Sharpe
     - find that strategy's relative rank among all N on the OOS blocks
     - λ = ln(ω / (1 - ω)) where ω is that relative rank in (0, 1)
  3. PBO = the fraction of combinations with λ < 0, i.e. the IS winner
     underperformed the median out of sample.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Sequence

from ..backtest.metrics import sharpe_ratio


def split_blocks(n_rows: int, n_blocks: int) -> list[list[int]]:
    """Contiguous, near-equal blocks. Contiguity matters: shuffling rows would
    destroy the serial correlation that makes overfitting detectable."""
    if n_blocks <= 0 or n_rows < n_blocks:
        return []
    size = n_rows // n_blocks
    blocks = [list(range(i * size, (i + 1) * size)) for i in range(n_blocks)]
    # Any remainder goes onto the final block rather than forming a stub.
    leftover = n_rows - n_blocks * size
    if leftover:
        blocks[-1].extend(range(n_blocks * size, n_rows))
    return blocks


def _column(returns: Sequence[Sequence[float]], rows: Sequence[int], col: int) -> list[float]:
    return [returns[r][col] for r in rows]


def pbo_cscv(
    returns: Sequence[Sequence[float]],
    n_blocks: int = 16,
    max_combinations: int | None = None,
) -> dict:
    """returns: T x N matrix (rows are periods, columns are strategies).

    Returns a dict with pbo, the lambda distribution, and the counts behind
    it, so a caller can show the histogram the design blueprint asks for.
    """
    if not returns or not returns[0]:
        return {"pbo": None, "lambdas": [], "n_combinations": 0, "reason": "empty matrix"}

    n_rows = len(returns)
    n_strategies = len(returns[0])
    if n_strategies < 2:
        return {
            "pbo": None,
            "lambdas": [],
            "n_combinations": 0,
            "reason": "PBO compares strategies against each other; need at least 2",
        }
    if n_blocks % 2 != 0:
        raise ValueError("n_blocks must be even so it can be split in half")

    blocks = split_blocks(n_rows, n_blocks)
    if not blocks:
        return {
            "pbo": None,
            "lambdas": [],
            "n_combinations": 0,
            "reason": f"{n_rows} rows cannot be split into {n_blocks} blocks",
        }

    all_idx = list(range(n_blocks))
    combos = list(combinations(all_idx, n_blocks // 2))
    if max_combinations and len(combos) > max_combinations:
        step = len(combos) / max_combinations
        combos = [combos[int(i * step)] for i in range(max_combinations)]

    lambdas: list[float] = []
    for is_blocks in combos:
        is_set = set(is_blocks)
        is_rows = [r for b in is_blocks for r in blocks[b]]
        oos_rows = [r for b in all_idx if b not in is_set for r in blocks[b]]
        if not is_rows or not oos_rows:
            continue

        is_sharpes = [sharpe_ratio(_column(returns, is_rows, c), annualize=False) for c in range(n_strategies)]
        best = max(range(n_strategies), key=lambda c: is_sharpes[c])

        oos_sharpes = [sharpe_ratio(_column(returns, oos_rows, c), annualize=False) for c in range(n_strategies)]
        # Rank of the IS winner among OOS results, 1 = worst, N = best.
        rank = 1 + sum(1 for c in range(n_strategies) if oos_sharpes[c] < oos_sharpes[best])
        omega = rank / (n_strategies + 1)
        lambdas.append(math.log(omega / (1 - omega)))

    if not lambdas:
        return {"pbo": None, "lambdas": [], "n_combinations": 0, "reason": "no usable splits"}

    pbo = sum(1 for lam in lambdas if lam < 0) / len(lambdas)
    return {
        "pbo": pbo,
        "lambdas": lambdas,
        "n_combinations": len(lambdas),
        "median_lambda": sorted(lambdas)[len(lambdas) // 2],
    }
