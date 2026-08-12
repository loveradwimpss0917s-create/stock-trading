import { ema } from './ema';

export interface MacdResult {
  macdLine: number[];
  signalLine: number[];
  histogram: number[];
}

export function macd(
  values: number[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9
): MacdResult {
  const emaFast = ema(values, fastPeriod);
  const emaSlow = ema(values, slowPeriod);

  const macdLine = values.map((_, i) =>
    Number.isNaN(emaFast[i]) || Number.isNaN(emaSlow[i]) ? NaN : emaFast[i] - emaSlow[i]
  );

  const firstValid = macdLine.findIndex((v) => !Number.isNaN(v));
  const signalLine = new Array(values.length).fill(NaN);
  if (firstValid >= 0) {
    const validTail = macdLine.slice(firstValid);
    const sig = ema(validTail, signalPeriod);
    for (let i = 0; i < sig.length; i++) signalLine[firstValid + i] = sig[i];
  }

  const histogram = macdLine.map((v, i) =>
    Number.isNaN(v) || Number.isNaN(signalLine[i]) ? NaN : v - signalLine[i]
  );

  return { macdLine, signalLine, histogram };
}
