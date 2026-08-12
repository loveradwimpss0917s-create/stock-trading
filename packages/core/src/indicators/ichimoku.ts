export interface IchimokuResult {
  tenkanSen: number[];
  kijunSen: number[];
  /** Indexed on the same timeline as inputs, shifted forward by `displacement`. */
  senkouSpanA: number[];
  /** Indexed on the same timeline as inputs, shifted forward by `displacement`. */
  senkouSpanB: number[];
  chikouSpan: number[];
}

export function ichimoku(
  highs: number[],
  lows: number[],
  closes: number[],
  tenkanPeriod = 9,
  kijunPeriod = 26,
  senkouBPeriod = 52,
  displacement = 26
): IchimokuResult {
  const n = closes.length;

  const midpoint = (period: number, i: number): number => {
    if (i < period - 1) return NaN;
    let hi = -Infinity;
    let lo = Infinity;
    for (let j = i - period + 1; j <= i; j++) {
      if (highs[j] > hi) hi = highs[j];
      if (lows[j] < lo) lo = lows[j];
    }
    return (hi + lo) / 2;
  };

  const tenkanSen = new Array(n).fill(NaN);
  const kijunSen = new Array(n).fill(NaN);
  const senkouSpanBBase = new Array(n).fill(NaN);
  for (let i = 0; i < n; i++) {
    tenkanSen[i] = midpoint(tenkanPeriod, i);
    kijunSen[i] = midpoint(kijunPeriod, i);
    senkouSpanBBase[i] = midpoint(senkouBPeriod, i);
  }

  const senkouSpanA = new Array(n + displacement).fill(NaN);
  const senkouSpanB = new Array(n + displacement).fill(NaN);
  const chikouSpan = new Array(n).fill(NaN);

  for (let i = 0; i < n; i++) {
    if (!Number.isNaN(tenkanSen[i]) && !Number.isNaN(kijunSen[i])) {
      senkouSpanA[i + displacement] = (tenkanSen[i] + kijunSen[i]) / 2;
    }
    if (!Number.isNaN(senkouSpanBBase[i])) {
      senkouSpanB[i + displacement] = senkouSpanBBase[i];
    }
    if (i >= displacement) {
      chikouSpan[i - displacement] = closes[i];
    }
  }

  return { tenkanSen, kijunSen, senkouSpanA, senkouSpanB, chikouSpan };
}
