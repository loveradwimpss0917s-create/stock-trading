/**
 * Risk of ruin and drawdown distribution — TypeScript port of
 * pipeline_py/risk/ruin.py.
 *
 * Runs in the browser rather than behind an endpoint because it needs no
 * data at all: given a win rate, payoff and position size, the answer is
 * pure arithmetic. Keeping it local makes the slider interactive, which
 * matters — the point is to let someone feel how fast ruin arrives as the
 * bet grows, and a network round trip per keystroke destroys that.
 *
 * The knowledge encoded: a positive expectancy does not make a size
 * survivable. Ruin depends on the path, and paths are far worse than
 * intuition suggests when trades are this noisy.
 *
 * Keep in lockstep with ruin.py — the Python side carries the reference
 * test suite.
 */

export interface RuinResult {
  pRuin: number;
  medianFinalEquity: number;
  pProfit: number;
  medianMaxDrawdown: number;
  p95MaxDrawdown: number;
  expectancyR: number;
  nSimulations: number;
  nTrades: number;
}

/** Expected R per trade. avgLossR is a positive magnitude.
 * The reason win rate alone is meaningless: 70% at 0.3R loses to 30% at 3R. */
export function expectancyR(winRate: number, avgWinR: number, avgLossR: number): number {
  return winRate * avgWinR - (1 - winRate) * Math.abs(avgLossR);
}

/** The win rate at which expectancy is exactly zero. */
export function requiredWinRate(avgWinR: number, avgLossR: number): number | null {
  const loss = Math.abs(avgLossR);
  const denom = avgWinR + loss;
  if (denom <= 0) return null;
  return loss / denom;
}

/** Kelly as a fraction of capital. Reported for reference, never as a
 * recommendation — full Kelly assumes the inputs are exact, and estimated
 * from a few hundred noisy trades it routinely overbets. */
export function kellyFraction(winRate: number, avgWinR: number, avgLossR: number): number {
  const loss = Math.abs(avgLossR);
  if (loss <= 0 || avgWinR <= 0) return 0;
  const b = avgWinR / loss;
  return Math.max(0, (winRate * (b + 1) - 1) / b);
}

/** Deterministic PRNG (mulberry32) so the same inputs always give the same
 * answer. A risk figure that flickers between renders reads as noise and
 * invites rerolling until a comfortable number appears. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function simulate(opts: {
  winRate: number;
  avgWinR: number;
  avgLossR: number;
  riskPerTrade: number;
  nTrades?: number;
  nSimulations?: number;
  ruinThreshold?: number;
  seed?: number;
}): RuinResult {
  const {
    winRate,
    avgWinR,
    avgLossR,
    riskPerTrade,
    nTrades = 200,
    nSimulations = 5000,
    ruinThreshold = 0.5,
    seed = 42,
  } = opts;

  const rng = mulberry32(seed);
  const loss = Math.abs(avgLossR);

  let ruined = 0;
  let profitable = 0;
  const finals: number[] = [];
  const drawdowns: number[] = [];

  for (let s = 0; s < nSimulations; s++) {
    let equity = 1;
    let peak = 1;
    let worstDd = 0;
    let hitRuin = false;

    for (let t = 0; t < nTrades; t++) {
      const r = rng() < winRate ? avgWinR : -loss;
      equity *= 1 + riskPerTrade * r;
      if (equity <= 0) {
        equity = 0;
        hitRuin = true;
        break;
      }
      peak = Math.max(peak, equity);
      worstDd = Math.max(worstDd, (peak - equity) / peak);
      // Checked every trade, not at the end: an account that dipped through
      // the threshold and recovered was still closed.
      if (equity <= ruinThreshold) {
        hitRuin = true;
        break;
      }
    }

    if (hitRuin) ruined++;
    if (equity > 1) profitable++;
    finals.push(equity);
    drawdowns.push(worstDd);
  }

  finals.sort((a, b) => a - b);
  drawdowns.sort((a, b) => a - b);

  return {
    pRuin: ruined / nSimulations,
    medianFinalEquity: percentile(finals, 0.5),
    pProfit: profitable / nSimulations,
    medianMaxDrawdown: percentile(drawdowns, 0.5),
    p95MaxDrawdown: percentile(drawdowns, 0.95),
    expectancyR: expectancyR(winRate, avgWinR, avgLossR),
    nSimulations,
    nTrades,
  };
}

function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const idx = q * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo]!;
  return sorted[lo]! + (sorted[hi]! - sorted[lo]!) * (idx - lo);
}
