import { describe, expect, it } from 'vitest';
import { ichimoku } from '../indicators/ichimoku';

describe('ichimoku', () => {
  it('matches a hand-computed Ichimoku for a known series with small periods', () => {
    const highs = [10, 12, 11, 13, 14, 12];
    const lows = [8, 9, 8, 10, 11, 9];
    const closes = [9, 11, 9, 12, 13, 10];
    // tenkan=2, kijun=3, senkouB=4, displacement=2
    const { tenkanSen, kijunSen, senkouSpanA, senkouSpanB, chikouSpan } = ichimoku(
      highs,
      lows,
      closes,
      2,
      3,
      4,
      2
    );

    expect(tenkanSen).toEqual([NaN, 10, 10, 10.5, 12, 11.5]);
    expect(kijunSen[2]).toBeCloseTo(10, 10);
    expect(kijunSen[3]).toBeCloseTo(10.5, 10);
    expect(kijunSen[4]).toBeCloseTo(11, 10);
    expect(kijunSen[5]).toBeCloseTo(11.5, 10);

    expect(senkouSpanA[4]).toBeCloseTo(10, 10);
    expect(senkouSpanA[5]).toBeCloseTo(10.5, 10);
    expect(senkouSpanA[6]).toBeCloseTo(11.5, 10);
    expect(senkouSpanA[7]).toBeCloseTo(11.5, 10);

    expect(senkouSpanB[5]).toBeCloseTo(10.5, 10);
    expect(senkouSpanB[6]).toBeCloseTo(11, 10);
    expect(senkouSpanB[7]).toBeCloseTo(11, 10);

    expect(chikouSpan).toEqual([9, 12, 13, 10, NaN, NaN]);
  });
});
