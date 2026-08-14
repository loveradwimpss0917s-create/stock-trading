"""Probabilistic and Deflated Sharpe Ratio (Bailey & López de Prado).

The point of DSR: if you try N strategies against the same data, the best
one's Sharpe is inflated by selection alone. Bailey & López de Prado show
that with 1,000 independent backtests, an expected maximum Sharpe around
3.26 arises even when every true Sharpe is zero. DSR asks whether the
observed Sharpe beats that selection benchmark, not whether it beats zero.

Two things must hold or the number is meaningless:

1. Every Sharpe here is a DAILY ratio. Feeding an annualized SR into these
   formulas while the benchmark is built from daily variance overstates the
   result badly. metrics.Metrics carries sharpe_daily for exactly this.
2. `kurtosis` is the raw fourth moment (normal == 3), not excess kurtosis.
   The (γ4 - 1)/4 term in the PSR denominator only matches the published
   derivation on that convention.

normal CDF/quantile come from statistics.NormalDist rather than a
hand-rolled rational approximation — it is stdlib and already correct.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Sequence

EULER_MASCHERONI = 0.5772156649015329
_NORM = NormalDist()


def norm_cdf(x: float) -> float:
    return _NORM.cdf(x)


def norm_ppf(p: float) -> float:
    # Guard the open interval: N=1 would otherwise ask for Z(0).
    eps = 1e-15
    return _NORM.inv_cdf(min(max(p, eps), 1 - eps))


def expected_max_sharpe(var_sr: float, n_trials: int) -> float:
    """E[max SR] under the False Strategy Theorem, for n_trials independent
    strategies whose SRs have variance var_sr and true mean zero."""
    n = max(int(n_trials), 2)
    if var_sr <= 0:
        return 0.0
    a = norm_ppf(1 - 1 / n)
    b = norm_ppf(1 - 1 / (n * math.e))
    return math.sqrt(var_sr) * ((1 - EULER_MASCHERONI) * a + EULER_MASCHERONI * b)


def probabilistic_sharpe(
    sr_observed: float,
    sr_benchmark: float,
    n_periods: int,
    skew: float,
    kurtosis: float,
) -> float:
    """PSR: probability the true SR exceeds sr_benchmark.

    All SRs at the same (daily) frequency. Returns 0.5 when the sample is too
    short to say anything, rather than a spuriously confident number.
    """
    if n_periods < 2:
        return 0.5

    denom_sq = 1 - skew * sr_observed + ((kurtosis - 1) / 4) * sr_observed**2
    if denom_sq <= 0:
        # Extreme skew/kurtosis can drive the variance estimate non-positive;
        # the statistic is undefined there, so decline to claim significance.
        return 0.5

    z = (sr_observed - sr_benchmark) * math.sqrt(n_periods - 1) / math.sqrt(denom_sq)
    return norm_cdf(z)


def deflated_sharpe(
    sr_observed: float,
    sr_variance_across_trials: float,
    n_trials: int,
    n_periods: int,
    skew: float,
    kurtosis: float,
) -> tuple[float, float]:
    """Returns (dsr, expected_max_sr).

    dsr is the probability the strategy's true SR exceeds what selection
    across n_trials would have produced by chance alone.
    """
    sr0 = expected_max_sharpe(sr_variance_across_trials, n_trials)
    dsr = probabilistic_sharpe(sr_observed, sr0, n_periods, skew, kurtosis)
    return dsr, sr0


def sharpe_variance_across_trials(daily_sharpes: Sequence[float]) -> float:
    """Sample variance of the trial SRs — the V[SR] the theorem needs.

    Using a single strategy's SR here yields 0 and collapses the benchmark to
    0, which would quietly turn DSR back into "is it better than zero".
    """
    n = len(daily_sharpes)
    if n < 2:
        return 0.0
    mean = math.fsum(daily_sharpes) / n
    return math.fsum((s - mean) ** 2 for s in daily_sharpes) / (n - 1)
