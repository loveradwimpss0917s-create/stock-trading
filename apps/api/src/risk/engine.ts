/**
 * Risk Engine — TypeScript port of pipeline_py/risk/engine.py.
 *
 * The Python module is the batch-side reference (its test suite is the
 * source of truth for the math); this port exists because Cloudflare
 * Workers can't run Python and the Worker is where a user's live decision
 * happens — portfolio heat and open-position counts change the moment a
 * position opens or closes, so a once-daily precomputed verdict would be
 * stale within the same session. Keep the two in lockstep: any gate added
 * here needs the matching gate in engine.py, and vice versa.
 *
 * Every gate is arithmetic — R:R (net of execution cost), lot size,
 * notional, portfolio heat, open-position count, sector concentration,
 * turnover, liquidity. None of it depends on a Setup or Regime being
 * statistically valid; unproven ideas get recorded, not gated on.
 */
import { planEconomics, type PlanEconomics } from './cost';

export const LOT_SIZE = 100;
export const MIN_TURNOVER = 300_000_000; // matches pipeline_py/screening/scoring.py

export const PASS_GATES = ['min_rr', 'lot_size', 'notional', 'turnover', 'liquidity'] as const;
export const WAIT_GATES = ['heat', 'max_positions', 'sector_concentration'] as const;

export interface Account {
  capital: number;
  risk_per_trade: number;
  max_positions: number;
  max_heat: number;
  max_notional_pct: number;
  min_rr: number;
  max_sector_positions: number;
}

export interface PortfolioContext {
  openPositions: number;
  currentHeat: number;
  sectorPositionCounts: Record<string, number>;
}

export interface PlanLevels {
  triggerPrice: number;
  stopPlanned: number;
  targetPlanned: number;
  sector33?: string | null;
  turnoverValue?: number | null;
  avgVolume20d?: number | null;
  /** Drives the cost model. Absent, cost falls back to the flat slippage
   * floor, which understates it on volatile names — the resulting R:R is
   * then optimistic. Callers that can supply ATR should. */
  atr?: number | null;
}

export interface GateResult {
  passed: boolean;
  value: number | null;
  threshold?: number;
  /** min_rr only: the pre-cost figure, kept beside the net one so the gap
   * is visible rather than folded away. */
  gross?: number;
}

export type Decision = 'BUY' | 'WAIT' | 'PASS';

export interface RiskVerdict {
  decision: Decision;
  reasonCode: string;
  shares: number;
  riskAmount: number;
  riskPct: number;
  notional: number;
  rrGross: number;
  rrNet: number;
  gates: Record<string, GateResult>;
  economics: PlanEconomics | null;
}

/** Shares sized off the stop distance, floored to the lot size. Flooring
 * only ever reduces the risk below the target — never rounds up past it —
 * so risk_amount is a ceiling, not an approximation. */
export function positionSize(
  capital: number,
  riskPerTrade: number,
  trigger: number,
  stop: number
): { shares: number; riskAmount: number } {
  const riskPerShare = trigger - stop;
  if (riskPerShare <= 0) return { shares: 0, riskAmount: 0 };
  const targetRisk = capital * riskPerTrade;
  const rawShares = targetRisk / riskPerShare;
  const shares = Math.floor(rawShares / LOT_SIZE) * LOT_SIZE;
  return { shares, riskAmount: shares * riskPerShare };
}

export function evaluateRisk(
  account: Account,
  levels: PlanLevels,
  ctx: PortfolioContext
): RiskVerdict {
  const gates: Record<string, GateResult> = {};

  // The R:R gate is evaluated NET of execution cost. Gating on the gross
  // figure approves plans whose advertised edge is entirely consumed by
  // getting in and out — on this repo's own data the round trip runs
  // 0.10-0.18R, larger than any selection effect measured here. Cost is
  // arithmetic, not a hypothesis, so it is allowed to block.
  const econ = planEconomics(
    levels.triggerPrice,
    levels.stopPlanned,
    levels.targetPlanned,
    levels.atr
  );
  const rrGross = econ ? econ.rrGross : 0;
  const rrNet = econ ? econ.rrNet : 0;
  gates.min_rr = {
    passed: rrNet >= account.min_rr,
    value: round(rrNet, 3),
    gross: round(rrGross, 3),
    threshold: account.min_rr,
  };

  const { shares, riskAmount } = positionSize(
    account.capital,
    account.risk_per_trade,
    levels.triggerPrice,
    levels.stopPlanned
  );
  gates.lot_size = { passed: shares >= LOT_SIZE, value: shares };

  const notional = shares * levels.triggerPrice;
  const maxNotional = account.capital * account.max_notional_pct;
  gates.notional = {
    passed: notional <= maxNotional,
    value: round(notional, 2),
    threshold: round(maxNotional, 2),
  };

  const riskPct = account.capital ? riskAmount / account.capital : 0;
  const newHeat = ctx.currentHeat + riskPct;
  gates.heat = { passed: newHeat <= account.max_heat, value: round(newHeat, 4), threshold: account.max_heat };

  gates.max_positions = {
    passed: ctx.openPositions < account.max_positions,
    value: ctx.openPositions,
    threshold: account.max_positions,
  };

  const sectorCount = levels.sector33 ? ctx.sectorPositionCounts[levels.sector33] ?? 0 : 0;
  gates.sector_concentration = {
    passed: sectorCount < account.max_sector_positions,
    value: sectorCount,
    threshold: account.max_sector_positions,
  };

  // Unknown turnover/volume doesn't block — matches score_theme's own
  // _passes_liquidity, which treats missing data as "not disqualifying".
  if (levels.turnoverValue != null) {
    gates.turnover = {
      passed: levels.turnoverValue >= MIN_TURNOVER,
      value: levels.turnoverValue,
      threshold: MIN_TURNOVER,
    };
  } else {
    gates.turnover = { passed: true, value: null };
  }

  if (levels.avgVolume20d && shares) {
    const advPct = shares / levels.avgVolume20d;
    gates.liquidity = { passed: advPct <= 0.01, value: round(advPct, 4) };
  } else {
    gates.liquidity = { passed: true, value: null };
  }

  const verdict = (decision: Decision, reasonCode: string): RiskVerdict => ({
    decision,
    reasonCode,
    shares,
    riskAmount,
    riskPct,
    notional,
    rrGross,
    rrNet,
    gates,
    economics: econ,
  });

  for (const gate of PASS_GATES) {
    if (!gates[gate].passed) {
      // A plan whose gross R:R cleared the bar and whose net one did not
      // failed for a reason the user can act on — widen the stop, or accept
      // that this trade is too tight to be worth taking — so it gets its own
      // reason rather than reading as an ordinary bad-R:R rejection.
      if (gate === 'min_rr' && rrGross >= account.min_rr) {
        return verdict('PASS', 'min_rr_after_cost');
      }
      return verdict('PASS', gate);
    }
  }
  for (const gate of WAIT_GATES) {
    if (!gates[gate].passed) return verdict('WAIT', gate);
  }

  return verdict('BUY', 'all_gates_passed');
}

function round(v: number, digits: number): number {
  const m = 10 ** digits;
  return Math.round(v * m) / m;
}
