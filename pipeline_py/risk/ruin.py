"""Risk of ruin and drawdown distribution.

The piece of professional knowledge this encodes: a positive expectancy
does not make a position size survivable. Bet enough per trade and a
winning system still bankrupts you, because ruin depends on the *path*,
not the average — and paths are far worse than intuition suggests when
trades are this noisy.

Nothing here predicts anything. Given a win rate, an average win and loss
in R, and a fraction of capital risked per trade, the answers are pure
arithmetic and Monte Carlo over the resulting distribution. That makes
this the one part of the app whose output is trustworthy today, with no
edge established and none assumed.

Two figures matter more than the average outcome:

* P(ruin) — reaching the ruin threshold at any point, not at the end.
  A path that dips below and recovers has still ended the account.
* The drawdown distribution — most traders quit at a drawdown well
  before ruin, so the 95th percentile drawdown is the number that
  decides whether a plan is actually followable.

Compounding is on by default: each trade risks a fraction of CURRENT
equity, which is what a percentage risk rule actually does. Fixed-fraction
betting cannot mathematically reach zero, so ruin is defined as falling
to a threshold (default 50% of starting capital) rather than to nothing.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RuinResult:
    p_ruin: float
    median_final_equity: float
    p_profit: float
    median_max_drawdown: float
    p95_max_drawdown: float
    expectancy_r: float
    n_simulations: int
    n_trades: int


def expectancy_r(win_rate: float, avg_win_r: float, avg_loss_r: float) -> float:
    """Expected R per trade. avg_loss_r is given as a positive magnitude.

    The number that matters, and the reason win rate alone is meaningless:
    70% at 0.3R loses to 30% at 3R.
    """
    return win_rate * avg_win_r - (1.0 - win_rate) * abs(avg_loss_r)


def required_win_rate(avg_win_r: float, avg_loss_r: float) -> Optional[float]:
    """The win rate at which expectancy is exactly zero.

    Turns "is this any good" into a question with a checkable answer:
    you either clear this number over enough trades or you don't.
    """
    loss = abs(avg_loss_r)
    denom = avg_win_r + loss
    if denom <= 0:
        return None
    return loss / denom


def kelly_fraction(win_rate: float, avg_win_r: float, avg_loss_r: float) -> float:
    """Kelly as a fraction of capital, in R-units of payoff.

    Reported for reference, never as a recommendation. Full Kelly assumes
    the inputs are known exactly; estimated from a few hundred noisy
    trades it routinely overbets by a wide margin, and its drawdowns are
    brutal even when it is right. Practitioners use a fraction of it —
    which is why half- and quarter-Kelly are surfaced alongside.
    """
    loss = abs(avg_loss_r)
    if loss <= 0 or avg_win_r <= 0:
        return 0.0
    b = avg_win_r / loss  # payoff odds
    f = (win_rate * (b + 1) - 1) / b
    return max(0.0, f)


def simulate(
    win_rate: float,
    avg_win_r: float,
    avg_loss_r: float,
    risk_per_trade: float,
    n_trades: int = 200,
    n_simulations: int = 10_000,
    ruin_threshold: float = 0.5,
    seed: Optional[int] = 42,
) -> RuinResult:
    """Monte Carlo over `n_trades` bets of `risk_per_trade` of current equity.

    seed is fixed by default so the same inputs give the same answer —
    a risk figure that flickers between page loads reads as noise and
    invites the user to reroll until they see one they like.
    """
    rng = random.Random(seed)
    loss = abs(avg_loss_r)

    ruined = 0
    profitable = 0
    finals: list[float] = []
    max_drawdowns: list[float] = []

    for _ in range(n_simulations):
        equity = 1.0
        peak = 1.0
        worst_dd = 0.0
        hit_ruin = False

        for _ in range(n_trades):
            r = avg_win_r if rng.random() < win_rate else -loss
            equity *= 1.0 + risk_per_trade * r
            if equity <= 0:
                equity = 0.0
                hit_ruin = True
                break
            peak = max(peak, equity)
            worst_dd = max(worst_dd, (peak - equity) / peak)
            # Ruin is checked every trade, not at the end: an account that
            # dipped through the threshold and recovered was still closed.
            if equity <= ruin_threshold:
                hit_ruin = True
                break

        if hit_ruin:
            ruined += 1
        if equity > 1.0:
            profitable += 1
        finals.append(equity)
        max_drawdowns.append(worst_dd)

    finals.sort()
    max_drawdowns.sort()

    return RuinResult(
        p_ruin=ruined / n_simulations,
        median_final_equity=_percentile(finals, 0.50),
        p_profit=profitable / n_simulations,
        median_max_drawdown=_percentile(max_drawdowns, 0.50),
        p95_max_drawdown=_percentile(max_drawdowns, 0.95),
        expectancy_r=expectancy_r(win_rate, avg_win_r, avg_loss_r),
        n_simulations=n_simulations,
        n_trades=n_trades,
    )


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = q * (len(sorted_values) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_values[int(idx)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)
