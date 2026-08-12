export interface AdxResult {
  plusDI: number[];
  minusDI: number[];
  dx: number[];
  adx: number[];
}

export function adx(highs: number[], lows: number[], closes: number[], period = 14): AdxResult {
  const n = closes.length;
  const plusDM = new Array(n).fill(NaN);
  const minusDM = new Array(n).fill(NaN);
  const tr = new Array(n).fill(NaN);

  for (let i = 1; i < n; i++) {
    const upMove = highs[i] - highs[i - 1];
    const downMove = lows[i - 1] - lows[i];
    plusDM[i] = upMove > downMove && upMove > 0 ? upMove : 0;
    minusDM[i] = downMove > upMove && downMove > 0 ? downMove : 0;

    const hl = highs[i] - lows[i];
    const hc = Math.abs(highs[i] - closes[i - 1]);
    const lc = Math.abs(lows[i] - closes[i - 1]);
    tr[i] = Math.max(hl, hc, lc);
  }

  // Wilder's running-sum smoothing (distinct from EMA smoothing).
  const smooth = (values: number[]): number[] => {
    const out = new Array(n).fill(NaN);
    if (n <= period) return out;
    let sum = 0;
    for (let i = 1; i <= period; i++) sum += values[i];
    let prev = sum;
    out[period] = prev;
    for (let i = period + 1; i < n; i++) {
      prev = prev - prev / period + values[i];
      out[i] = prev;
    }
    return out;
  };

  const smoothedTR = smooth(tr);
  const smoothedPlusDM = smooth(plusDM);
  const smoothedMinusDM = smooth(minusDM);

  const plusDI = new Array(n).fill(NaN);
  const minusDI = new Array(n).fill(NaN);
  const dx = new Array(n).fill(NaN);

  for (let i = period; i < n; i++) {
    plusDI[i] = 100 * (smoothedPlusDM[i] / smoothedTR[i]);
    minusDI[i] = 100 * (smoothedMinusDM[i] / smoothedTR[i]);
    const sum = plusDI[i] + minusDI[i];
    dx[i] = sum === 0 ? 0 : (100 * Math.abs(plusDI[i] - minusDI[i])) / sum;
  }

  const adxOut = new Array(n).fill(NaN);
  const firstDxIdx = dx.findIndex((v) => !Number.isNaN(v));
  if (firstDxIdx >= 0 && firstDxIdx + period <= n) {
    let sum = 0;
    for (let i = firstDxIdx; i < firstDxIdx + period; i++) sum += dx[i];
    let prev = sum / period;
    const adxStart = firstDxIdx + period - 1;
    adxOut[adxStart] = prev;
    for (let i = adxStart + 1; i < n; i++) {
      prev = (prev * (period - 1) + dx[i]) / period;
      adxOut[i] = prev;
    }
  }

  return { plusDI, minusDI, dx, adx: adxOut };
}
