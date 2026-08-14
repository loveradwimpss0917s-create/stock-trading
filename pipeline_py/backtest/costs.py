"""Execution costs.

Defaults follow the design blueprint's assumptions for a Japanese retail
account: SBI/Rakuten zero-commission course, ATR-proportional slippage,
1.10%/yr stock borrow on shorts, 20.315% capital gains tax.

Tax is deliberately NOT applied inside the return series. It is a
portfolio-level, realization-timing-dependent charge; folding it into daily
returns would distort Sharpe and — more importantly — feed a tax-mangled
series into DSR/PBO, which are meant to judge whether the *signal* is real.
after_tax_return() is offered for reporting a net figure separately.
"""
from __future__ import annotations

from dataclasses import dataclass

CAPITAL_GAINS_TAX = 0.20315  # 特定口座 譲渡益課税
DEFAULT_BORROW_RATE_ANNUAL = 0.0110  # 貸株料 1.10%/yr
TRADING_DAYS = 252


@dataclass(frozen=True)
class CostModel:
    """All rates are fractions, not bps."""

    commission_rate: float = 0.0  # zero-commission course
    # Floor for slippage when ATR is unavailable or tiny.
    min_slippage_rate: float = 0.0005  # 5bp
    # Slippage as a fraction of ATR: crossing the spread on a liquid large cap
    # costs a small fraction of a day's typical range.
    atr_slippage_fraction: float = 0.10
    borrow_rate_annual: float = DEFAULT_BORROW_RATE_ANNUAL

    def slippage_rate(self, price: float, atr: float | None) -> float:
        if not price or price <= 0:
            return self.min_slippage_rate
        if atr is None or atr <= 0:
            return self.min_slippage_rate
        return max(self.min_slippage_rate, self.atr_slippage_fraction * atr / price)

    def entry_fill_price(self, price: float, atr: float | None, side: str) -> float:
        """Slippage always works against the trade — paying up to buy, hit down
        to sell — so it can never flatter a backtest."""
        rate = self.slippage_rate(price, atr)
        return price * (1 + rate) if side == "long" else price * (1 - rate)

    def exit_fill_price(self, price: float, atr: float | None, side: str) -> float:
        rate = self.slippage_rate(price, atr)
        return price * (1 - rate) if side == "long" else price * (1 + rate)

    def commission(self, notional: float) -> float:
        return abs(notional) * self.commission_rate

    def borrow_cost(self, notional: float, days: int, side: str) -> float:
        if side != "short" or days <= 0:
            return 0.0
        return abs(notional) * self.borrow_rate_annual * days / TRADING_DAYS


def after_tax_return(gross_return: float, tax_rate: float = CAPITAL_GAINS_TAX) -> float:
    """Only gains are taxed; losses pass through untaxed (loss carry-forward is
    out of scope and would need a multi-year account model)."""
    return gross_return * (1 - tax_rate) if gross_return > 0 else gross_return
