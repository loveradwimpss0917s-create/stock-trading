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


@dataclass(frozen=True)
class PlanEconomics:
    """A plan's payoff before and after execution cost."""

    rr_gross: float
    rr_net: float
    cost_win_r: float
    cost_loss_r: float
    required_win_rate_gross: Optional[float]
    required_win_rate_net: Optional[float]


def _required_win_rate(win_r: float, loss_r: float) -> Optional[float]:
    """Break-even hit rate for a payoff of win_r against a loss of loss_r.

    None when win_r is non-positive: no hit rate rescues a trade whose best
    case is a loss, and the ratio would silently return a plausible-looking
    fraction if computed anyway.
    """
    if win_r <= 0 or loss_r <= 0:
        return None
    return loss_r / (win_r + loss_r)


def plan_economics(
    trigger_price: float,
    stop_planned: float,
    target_planned: float,
    atr: Optional[float],
    cost: CostAssumption = CostAssumption(),
) -> Optional[PlanEconomics]:
    """What this plan actually pays, once getting in and out is paid for.

    The advertised R:R is a claim about two prices on a chart. The tradeable
    R:R is smaller on both sides at once, and that is the part people skip:
    cost does not merely shave the winner, it also *deepens the loser*. A
    stopped-out trade loses its 1R plus the round trip, so the denominator
    grows while the numerator shrinks and the ratio falls faster than a
    single subtraction suggests.

    Cost is computed separately for the two exits because they happen at
    different prices — charging the target's cost to a stop-out would
    overstate what a loss costs on a plan with a wide target.

    The number worth acting on is required_win_rate_net. A 3:1 plan looks
    like it only needs 25%; on a 1.0x ATR stop the honest figure is near
    30%, and that five-point gap is the difference between a system that
    clears its costs and one that funds the broker.
    """
    risk_per_share = trigger_price - stop_planned
    if risk_per_share <= 0:
        return None

    rr_gross = (target_planned - trigger_price) / risk_per_share
    cost_win_r = cost_in_r(trigger_price, target_planned, stop_planned, atr, cost)
    cost_loss_r = cost_in_r(trigger_price, stop_planned, stop_planned, atr, cost)
    if cost_win_r is None or cost_loss_r is None:
        return None

    net_win_r = rr_gross - cost_win_r
    net_loss_r = 1.0 + cost_loss_r  # a loser pays the stop AND the round trip
    rr_net = net_win_r / net_loss_r

    return PlanEconomics(
        rr_gross=rr_gross,
        rr_net=rr_net,
        cost_win_r=cost_win_r,
        cost_loss_r=cost_loss_r,
        required_win_rate_gross=_required_win_rate(rr_gross, 1.0),
        required_win_rate_net=_required_win_rate(net_win_r, net_loss_r),
    )


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
