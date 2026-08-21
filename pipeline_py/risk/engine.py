"""Risk Engine: turns a trade plan's price levels into a position size and a
BUY / WAIT / PASS verdict.

Every gate here is arithmetic: R:R (net of execution cost), lot size,
notional, portfolio heat, open-position count, sector concentration,
turnover, liquidity. None of it
requires an unproven Setup or Regime to be right — that is deliberate. The
design's central rule is that unproven ideas get recorded, not gated on;
only calculations that don't need statistical validation are allowed to
block a trade. If a gate here ever depends on "is this Setup any good",
it belongs in analytics, not in this module.

PASS vs WAIT is a real distinction, not two names for "no": PASS is about
the instrument (this name doesn't qualify on its own terms — bad R:R, too
illiquid, too small to fill at the lot size). WAIT is about the portfolio
(the name would be fine on its own, but the book has no room — heat, slot
count, sector concentration). A WAITed plan can still fire later if the
book frees up; a PASSed one should not resurface untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..screening.scoring import MIN_TURNOVER
from .cost_in_r import PlanEconomics, plan_economics

LOT_SIZE = 100

# Ordered so the first failing gate is the one reported: instrument-level
# reasons take priority over portfolio-level ones, since "this name is bad"
# is a more useful thing to tell the user than "no room right now" when both
# happen to be true simultaneously.
PASS_GATES = ("min_rr", "lot_size", "notional", "turnover", "liquidity")
WAIT_GATES = ("heat", "max_positions", "sector_concentration")


@dataclass(frozen=True)
class PortfolioContext:
    """What is already true about the book before this plan is considered.
    Assembled by the caller from `positions` — this module has no DB access,
    so the same verdict logic is exercised the same way in tests and prod."""

    open_positions: int
    current_heat: float  # fraction of capital already at risk
    sector_position_counts: dict[str, int]


@dataclass(frozen=True)
class PlanLevels:
    trigger_price: float
    stop_planned: float
    target_planned: float
    sector33: Optional[str] = None
    turnover_value: Optional[float] = None
    avg_volume_20d: Optional[float] = None
    # Drives the cost model. Absent, cost falls back to the flat slippage
    # floor, which understates it on volatile names — so the resulting R:R
    # is optimistic rather than wrong in the safe direction. Callers that
    # can supply ATR should.
    atr: Optional[float] = None


@dataclass(frozen=True)
class RiskVerdict:
    decision: str  # BUY | WAIT | PASS
    reason_code: str
    shares: int
    risk_amount: float
    risk_pct: float
    notional: float
    rr_gross: float
    rr_net: float
    gates: dict[str, dict]
    economics: Optional[PlanEconomics] = None


def position_size(
    capital: float, risk_per_trade: float, trigger: float, stop: float
) -> tuple[int, float]:
    """Shares sized off the stop distance, floored to the lot size.

    Returns (shares, actual_risk_amount). Flooring to the lot only ever
    reduces the risk below the target — it never rounds up past the cap —
    so the caller can trust risk_amount is a ceiling, not an approximation
    that might run hot.
    """
    risk_per_share = trigger - stop
    if risk_per_share <= 0:
        return 0, 0.0
    target_risk = capital * risk_per_trade
    raw_shares = target_risk / risk_per_share
    shares = int(raw_shares // LOT_SIZE) * LOT_SIZE
    return shares, shares * risk_per_share


def evaluate(account: dict, levels: PlanLevels, ctx: PortfolioContext) -> RiskVerdict:
    """account: a row from `accounts` (capital, risk_per_trade, max_positions,
    max_heat, max_notional_pct, min_rr, max_sector_positions)."""
    gates: dict[str, dict] = {}

    # The R:R gate is evaluated NET of execution cost. Gating on the gross
    # figure would approve plans whose advertised edge is entirely consumed
    # by getting in and out — on this repo's own data the round trip runs
    # 0.10-0.18R, which is larger than any selection effect measured here.
    # Cost is arithmetic, not a hypothesis, so it is allowed to block.
    econ = plan_economics(
        levels.trigger_price, levels.stop_planned, levels.target_planned, levels.atr
    )
    rr_gross = econ.rr_gross if econ else 0.0
    rr_net = econ.rr_net if econ else 0.0
    gates["min_rr"] = {
        "passed": rr_net >= account["min_rr"],
        "value": round(rr_net, 3),
        "gross": round(rr_gross, 3),
        "threshold": account["min_rr"],
    }

    shares, risk_amount = position_size(
        account["capital"], account["risk_per_trade"], levels.trigger_price, levels.stop_planned
    )
    gates["lot_size"] = {"passed": shares >= LOT_SIZE, "value": shares}

    notional = shares * levels.trigger_price
    max_notional = account["capital"] * account["max_notional_pct"]
    gates["notional"] = {
        "passed": notional <= max_notional,
        "value": round(notional, 2),
        "threshold": round(max_notional, 2),
    }

    risk_pct = risk_amount / account["capital"] if account["capital"] else 0.0
    new_heat = ctx.current_heat + risk_pct
    gates["heat"] = {
        "passed": new_heat <= account["max_heat"],
        "value": round(new_heat, 4),
        "threshold": account["max_heat"],
    }

    gates["max_positions"] = {
        "passed": ctx.open_positions < account["max_positions"],
        "value": ctx.open_positions,
        "threshold": account["max_positions"],
    }

    sector_count = (
        ctx.sector_position_counts.get(levels.sector33, 0) if levels.sector33 else 0
    )
    gates["sector_concentration"] = {
        "passed": sector_count < account["max_sector_positions"],
        "value": sector_count,
        "threshold": account["max_sector_positions"],
    }

    # Unknown turnover/volume doesn't block — matches the screen's own
    # _passes_liquidity, which treats missing data as "not disqualifying"
    # rather than as a failure. A stricter reading would double-penalize
    # names the ingest pipeline just hasn't backfilled turnover for yet.
    if levels.turnover_value is not None:
        gates["turnover"] = {
            "passed": levels.turnover_value >= MIN_TURNOVER,
            "value": levels.turnover_value,
            "threshold": MIN_TURNOVER,
        }
    else:
        gates["turnover"] = {"passed": True, "value": None}

    if levels.avg_volume_20d and shares:
        adv_pct = shares / levels.avg_volume_20d
        gates["liquidity"] = {"passed": adv_pct <= 0.01, "value": round(adv_pct, 4)}
    else:
        gates["liquidity"] = {"passed": True, "value": None}

    def verdict(decision: str, reason: str) -> RiskVerdict:
        return RiskVerdict(
            decision, reason, shares, risk_amount, risk_pct, notional, rr_gross, rr_net, gates, econ
        )

    for gate in PASS_GATES:
        if not gates[gate]["passed"]:
            # A plan whose gross R:R cleared the bar and whose net one did not
            # failed for a reason the user can act on — widen the stop, or
            # accept that this particular trade is too tight to be worth
            # taking — so it gets its own reason rather than reading as an
            # ordinary bad-R:R rejection.
            if gate == "min_rr" and rr_gross >= account["min_rr"]:
                return verdict("PASS", "min_rr_after_cost")
            return verdict("PASS", gate)
    for gate in WAIT_GATES:
        if not gates[gate]["passed"]:
            return verdict("WAIT", gate)

    return verdict("BUY", "all_gates_passed")
