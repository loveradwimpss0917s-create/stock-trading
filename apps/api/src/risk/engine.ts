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
 * Every gate is arithmetic — R:R, lot size, notional, portfolio heat,
 * open-position count, sector concentration, turnover, liquidity. None of
 * it depends on a Setup or Regime being statistically valid; unproven ideas
 * get recorded, not gated on.
 */

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
}

export interface GateResult {
  passed: boolean;
  value: number | null;
  threshold?: number;
}

export type Decision = 'BUY' | 'WAIT' | 'PASS';

export interface RiskVerdict {
  decision: Decision;
  reasonCode: string;
  shares: number;
  riskAmount: number;
  riskPct: number;
  notional: number;
  rr: number;
  gates: Record<string, GateResult>;
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

  const riskPerShare = levels.triggerPrice - levels.stopPlanned;
  const rewardPerShare = levels.targetPlanned - levels.triggerPrice;
  const rr = riskPerShare > 0 ? rewardPerShare / riskPerShare : 0;
  gates.min_rr = { passed: rr >= account.min_rr, value: round(rr, 3), threshold: account.min_rr };

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

  for (const gate of PASS_GATES) {
    if (!gates[gate].passed) {
      return { decision: 'PASS', reasonCode: gate, shares, riskAmount, riskPct, notional, rr, gates };
    }
  }
  for (const gate of WAIT_GATES) {
    if (!gates[gate].passed) {
      return { decision: 'WAIT', reasonCode: gate, shares, riskAmount, riskPct, notional, rr, gates };
    }
  }

  return {
    decision: 'BUY',
    reasonCode: 'all_gates_passed',
    shares,
    riskAmount,
    riskPct,
    notional,
    rr,
    gates,
  };
}

function round(v: number, digits: number): number {
  const m = 10 ** digits;
  return Math.round(v * m) / m;
}
