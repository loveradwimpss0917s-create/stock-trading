import { describe, expect, it } from 'vitest';
import { adx } from '../indicators/adx';

describe('adx', () => {
  it('matches a hand-computed ADX for a clean uptrend (period=1 removes smoothing)', () => {
    // Strictly increasing highs and lows -> -DM is always 0, so -DI is
    // always 0 and DX collapses to exactly 100 regardless of TR. With
    // period=1, Wilder's running-sum smoothing is a pass-through, so this
    // is hand-verifiable without tracing multi-step smoothing.
    const highs = [10, 12, 14, 16, 18, 20];
    const lows = [8, 9, 10, 11, 12, 13];
    const closes = [8, 9, 10, 11, 12, 13];
    // +DM[i] = high[i]-high[i-1] = 2 for all i=1..5; -DM[i] = 0
    // TR[1..5] = [4, 5, 6, 7, 8] (computed from highs/lows/closes above)
    // +DI[i] = 100*2/TR[i] -> [50, 40, 33.33.., 28.57.., 25]
    // -DI[i] = 0 for all i
    // DX[i] = 100*|+DI-0|/(+DI+0) = 100 for all i
    // ADX (period=1, pass-through) = 100 for all i once defined
    const { plusDI, minusDI, dx, adx: adxLine } = adx(highs, lows, closes, 1);

    expect(plusDI[1]).toBeCloseTo(50, 6);
    expect(plusDI[2]).toBeCloseTo(40, 6);
    expect(plusDI[3]).toBeCloseTo((100 * 2) / 6, 6);
    expect(plusDI[4]).toBeCloseTo((100 * 2) / 7, 6);
    expect(plusDI[5]).toBeCloseTo(25, 6);

    minusDI.slice(1).forEach((v) => expect(v).toBeCloseTo(0, 10));
    dx.slice(1).forEach((v) => expect(v).toBeCloseTo(100, 6));
    adxLine.slice(1).forEach((v) => expect(v).toBeCloseTo(100, 6));
  });
});
