"""Performance metrics computed from a daily return series and a trade list.

All Sharpe-family figures are computed at daily frequency and annualized by
sqrt(252) at the point of reporting. The design blueprint is explicit that
the statistical validation layer (DSR/PBO) must be fed *daily* SRs — mixing
annualized and daily values silently inflates the deflated Sharpe — so the
daily figure is kept alongside the annualized one rather than discarded.

Two different bases live here on purpose, and comparing them directly will
mislead:

- Sharpe/Sortino/Calmar/maxDD come from the daily return series, i.e. a
  constant-weight book rebalanced each session. This is the equity path.
- expectancy/profit_factor/win_rate come from trade PnL, a simple return
  per position over its own holding period.

For longs the two reconcile exactly once compounded. For shorts they cannot:
a name going 100 -> 200 -> 100 leaves a simple short return of 0% but a
daily-compounded one of -100%, because the position is wiped out on the way
up. The daily series is the honest path and stays the basis for the
statistics; profit factor below 1 alongside a positive Sharpe is therefore
possible for short-heavy strategies and is not by itself evidence of a bug.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Sequence

TRADING_DAYS = 252


@dataclass
class Trade:
    code: str
    entry_date: str
    exit_date: Optional[str]
    entry_price: float
    exit_price: Optional[float]
    weight: float
    side: str  # 'long' | 'short'
    pnl: Optional[float] = None
    holding_days: Optional[int] = None
    costs: dict[str, float] = field(default_factory=dict)


@dataclass
class Metrics:
    expectancy: float
    profit_factor: float
    sharpe: float  # annualized
    sharpe_daily: float  # what DSR/PBO must consume
    sortino: float
    calmar: float
    max_drawdown: float
    win_rate: float
    n_trades: int
    avg_holding_days: float
    turnover: float
    skew: float
    kurtosis: float
    n_periods: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs) if xs else 0.0


def _stdev(xs: Sequence[float], ddof: int = 1) -> float:
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    m = _mean(xs)
    var = math.fsum((x - m) ** 2 for x in xs) / (n - ddof)
    sd = math.sqrt(max(var, 0.0))

    # A constant series does not produce sd == 0 exactly: 0.01 has no exact
    # binary representation, so the residue lands around 1e-19 and a Sharpe
    # of mean/sd explodes to ~1e16 instead of collapsing to 0. Snap to zero
    # when sd is negligible at the data's own scale — a degenerate series
    # must not hand a spectacular Sharpe to the DSR/PBO layer.
    scale = max(abs(m), max((abs(x) for x in xs), default=0.0))
    if scale > 0 and sd < scale * 1e-12:
        return 0.0
    return sd


def sharpe_ratio(returns: Sequence[float], annualize: bool = True) -> float:
    """Excess-of-zero Sharpe. Risk-free is taken as 0: JGB short rates over the
    sample are near zero, and a non-zero rf would have to be applied
    consistently in the DSR benchmark too."""
    sd = _stdev(returns)
    if sd == 0:
        return 0.0
    sr = _mean(returns) / sd
    return sr * math.sqrt(TRADING_DAYS) if annualize else sr


def sortino_ratio(returns: Sequence[float], annualize: bool = True) -> float:
    """Downside deviation uses the full sample in the denominator, not just the
    losing days — dividing by the count of negatives inflates the ratio for
    strategies that rarely lose."""
    if not returns:
        return 0.0
    downside = [min(r, 0.0) ** 2 for r in returns]
    dd = math.sqrt(sum(downside) / len(returns))
    if dd == 0:
        return 0.0
    sr = _mean(returns) / dd
    return sr * math.sqrt(TRADING_DAYS) if annualize else sr


def equity_curve(returns: Sequence[float], start: float = 1.0) -> list[float]:
    equity = [start]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    return equity


def max_drawdown(equity: Sequence[float]) -> float:
    """Returns a non-negative fraction (0.2 == a 20% peak-to-trough decline)."""
    peak = float("-inf")
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


def cagr(equity: Sequence[float], n_periods: int) -> float:
    if n_periods <= 0 or len(equity) < 2 or equity[0] <= 0 or equity[-1] <= 0:
        return 0.0
    years = n_periods / TRADING_DAYS
    if years <= 0:
        return 0.0
    return (equity[-1] / equity[0]) ** (1 / years) - 1


def calmar_ratio(equity: Sequence[float], n_periods: int) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return cagr(equity, n_periods) / mdd


def skewness(xs: Sequence[float]) -> float:
    n = len(xs)
    sd = _stdev(xs, ddof=0)
    if n < 3 or sd == 0:
        return 0.0
    m = _mean(xs)
    return sum(((x - m) / sd) ** 3 for x in xs) / n


def kurtosis(xs: Sequence[float]) -> float:
    """Non-excess (normal == 3.0). The DSR formula in the design blueprint
    subtracts 1 from this term, which only lines up with the published
    derivation if the input is the raw fourth moment, not excess kurtosis."""
    n = len(xs)
    sd = _stdev(xs, ddof=0)
    if n < 4 or sd == 0:
        return 3.0
    m = _mean(xs)
    return sum(((x - m) / sd) ** 4 for x in xs) / n


def profit_factor(trade_pnls: Sequence[float]) -> float:
    gains = sum(p for p in trade_pnls if p > 0)
    losses = -sum(p for p in trade_pnls if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def compute_metrics(
    returns: Sequence[float],
    trades: Sequence[Trade],
    turnover: float = 0.0,
) -> Metrics:
    pnls = [t.pnl for t in trades if t.pnl is not None]
    holds = [t.holding_days for t in trades if t.holding_days is not None]
    eq = equity_curve(returns)

    return Metrics(
        expectancy=_mean(pnls),
        profit_factor=profit_factor(pnls),
        sharpe=sharpe_ratio(returns),
        sharpe_daily=sharpe_ratio(returns, annualize=False),
        sortino=sortino_ratio(returns),
        calmar=calmar_ratio(eq, len(returns)),
        max_drawdown=max_drawdown(eq),
        win_rate=(sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else 0.0,
        n_trades=len(trades),
        avg_holding_days=_mean(holds),
        turnover=turnover,
        skew=skewness(returns),
        kurtosis=kurtosis(returns),
        n_periods=len(returns),
    )
