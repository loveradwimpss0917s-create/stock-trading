/**
 * Round-trip execution cost expressed in R — TypeScript port of
 * pipeline_py/risk/cost_in_r.py. Keep the two in lockstep; the Python side
 * carries the reference test suite.
 *
 * Yen costs mean nothing on their own: the same 30-yen spread is trivial on
 * a trade risking 500 yen a share and fatal on one risking 40. Measured in
 * the trade's own risk unit it carries a consequence most retail screens
 * never surface — a tighter stop MULTIPLIES cost in R terms. Slippage per
 * share scales with ATR, so the price cancels and the round trip reduces to
 * roughly 2 * fraction / stop_multiple: a 1.0x ATR stop pays about 0.20R
 * and a 1.8x one about 0.11R for identical execution.
 *
 * On this repo's own data the round trip runs 0.10-0.18R while the largest
 * selection effect measured anywhere is about 0.05R. Cost is an order of
 * magnitude bigger than the thing the app was trying to measure, which is
 * why it gates rather than merely annotates.
 */

export const MIN_SLIPPAGE_RATE = 0.0005; // 5bp
export const ATR_SLIPPAGE_FRACTION = 0.1;
export const COMMISSION_RATE = 0; // SBI/楽天 ゼロ手数料コース

export interface PlanEconomics {
  rrGross: number;
  rrNet: number;
  costWinR: number;
  costLossR: number;
  requiredWinRateGross: number | null;
  requiredWinRateNet: number | null;
}

function slippageRate(price: number, atr: number | null | undefined): number {
  if (!price || price <= 0 || atr == null || atr <= 0) return MIN_SLIPPAGE_RATE;
  return Math.max(MIN_SLIPPAGE_RATE, (ATR_SLIPPAGE_FRACTION * atr) / price);
}

/** Round-trip cost as a multiple of the trade's own risk. Null when risk is
 * non-positive — there is no R to divide by. */
export function costInR(
  entryFill: number,
  exitPrice: number,
  stopPlanned: number,
  atr: number | null | undefined
): number | null {
  const riskPerShare = entryFill - stopPlanned;
  if (riskPerShare <= 0) return null;
  const perShare =
    entryFill * (slippageRate(entryFill, atr) + COMMISSION_RATE) +
    exitPrice * (slippageRate(exitPrice, atr) + COMMISSION_RATE);
  return perShare / riskPerShare;
}

/** Break-even hit rate for a payoff of winR against a loss of lossR.
 * Null when winR is non-positive: no hit rate rescues a trade whose best
 * case is a loss, and the ratio would otherwise return a plausible-looking
 * fraction. */
function requiredWinRate(winR: number, lossR: number): number | null {
  if (winR <= 0 || lossR <= 0) return null;
  return lossR / (winR + lossR);
}

/**
 * What this plan actually pays, once getting in and out is paid for.
 *
 * Cost does not merely shave the winner — it also deepens the loser, which
 * is the part people skip. A stopped-out trade loses its 1R *plus* the
 * round trip, so the denominator grows while the numerator shrinks and the
 * ratio falls faster than a single subtraction suggests.
 *
 * The two exits are priced separately because they happen at different
 * prices; charging the target's cost to a stop-out would overstate what a
 * loss costs on a plan with a wide target.
 */
export function planEconomics(
  triggerPrice: number,
  stopPlanned: number,
  targetPlanned: number,
  atr: number | null | undefined
): PlanEconomics | null {
  const riskPerShare = triggerPrice - stopPlanned;
  if (riskPerShare <= 0) return null;

  const rrGross = (targetPlanned - triggerPrice) / riskPerShare;
  const costWinR = costInR(triggerPrice, targetPlanned, stopPlanned, atr);
  const costLossR = costInR(triggerPrice, stopPlanned, stopPlanned, atr);
  if (costWinR === null || costLossR === null) return null;

  const netWinR = rrGross - costWinR;
  const netLossR = 1 + costLossR; // a loser pays the stop AND the round trip

  return {
    rrGross,
    rrNet: netWinR / netLossR,
    costWinR,
    costLossR,
    requiredWinRateGross: requiredWinRate(rrGross, 1),
    requiredWinRateNet: requiredWinRate(netWinR, netLossR),
  };
}
