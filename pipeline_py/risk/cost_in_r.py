"""Round-trip execution cost expressed in R.

Yen costs mean nothing on their own — the same 30-yen spread is trivial on
a trade risking 500 yen a share and fatal on one risking 40. What matters
is cost measured in the trade's own risk unit, and that number carries a
consequence most retail screens never surface:

    a tighter stop multiplies cost in R terms

Measured on this repo's own Shadow Book: reversal_3d, whose stop is
1.0x ATR, pays 0.178R per round trip. pullback_ma25, at 1.8x ATR, pays
0.098R for the same execution quality. Same broker, same slippage, nearly
double the cost — purely because the risk unit is smaller. A Setup that
looks cheap because it "risks less per trade" can be the most expensive
one to run.

Costs are applied to the Setup verification path (replay/baseline), which
previously ignored them entirely and therefore reported every Setup's
gross R as if it were takeable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The blueprint's model: slippage scales with ATR because crossing the
# spread on a wide-range name costs more, with a floor for quiet names.
DEFAULT_MIN_SLIPPAGE_RATE = 0.0005  # 5bp
DEFAULT_ATR_SLIPPAGE_FRACTION = 0.10
DEFAULT_COMMISSION_RATE = 0.0  # SBI/楽天 ゼロ手数料コース


@dataclass(frozen=True)
class CostAssumption:
    """All rates are fractions of price, not bps."""

    min_slippage_rate: float = DEFAULT_MIN_SLIPPAGE_RATE
    atr_slippage_fraction: float = DEFAULT_ATR_SLIPPAGE_FRACTION
    commission_rate: float = DEFAULT_COMMISSION_RATE

    def slippage_rate(self, price: float, atr: Optional[float]) -> float:
        if not price or price <= 0 or atr is None or atr <= 0:
            return self.min_slippage_rate
        return max(self.min_slippage_rate, self.atr_slippage_fraction * atr / price)


def cost_in_r(
    entry_fill: float,
    exit_price: float,
    stop_planned: float,
    atr: Optional[float],
    cost: CostAssumption = CostAssumption(),
) -> Optional[float]:
    """Round-trip cost as a multiple of the trade's own risk.

    Risk is measured from the ACTUAL fill to the published stop, matching
    how r_multiple is computed — using the planned entry instead would
    understate cost on any trade that gapped in.

    Returns None when risk is non-positive: there is no R to divide by, and
    a trade entered past its own stop is already recorded as no_entry.
    """
    risk_per_share = entry_fill - stop_planned
    if risk_per_share <= 0:
        return None

    entry_slip = cost.slippage_rate(entry_fill, atr)
    exit_slip = cost.slippage_rate(exit_price, atr)
    per_share = (
        entry_fill * (entry_slip + cost.commission_rate)
        + exit_price * (exit_slip + cost.commission_rate)
    )
    return per_share / risk_per_share


def breakeven_slippage_rate(
    gross_r: float, entry_fill: float, exit_price: float, stop_planned: float
) -> Optional[float]:
    """The per-side slippage at which this trade's gross R is exactly eaten.

    More useful than a single cost estimate: it converts "is this Setup
    viable" into "is my execution better than X bp", which is a question
    about the broker and the order type rather than about the model.
    """
    risk_per_share = entry_fill - stop_planned
    if risk_per_share <= 0 or (entry_fill + exit_price) <= 0:
        return None
    return gross_r * risk_per_share / (entry_fill + exit_price)
