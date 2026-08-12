export interface BollingerBandsResult {
  middle: number[];
  upper: number[];
  lower: number[];
}

export function bollingerBands(closes: number[], period = 20, k = 2): BollingerBandsResult {
  const n = closes.length;
  const middle = new Array(n).fill(NaN);
  const upper = new Array(n).fill(NaN);
  const lower = new Array(n).fill(NaN);

  for (let i = period - 1; i < n; i++) {
    const window = closes.slice(i - period + 1, i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const variance = window.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    middle[i] = mean;
    upper[i] = mean + k * sd;
    lower[i] = mean - k * sd;
  }

  return { middle, upper, lower };
}
