import { describe, expect, it } from 'vitest';
import { atr } from '../indicators/atr';

describe('atr', () => {
  it('matches a hand-computed ATR for a known series', () => {
    const highs = [10, 12, 13, 14, 16];
    const lows = [8, 9, 10, 11, 12];
    const closes = [9, 11, 12, 13, 15];
    // TR[1] = max(12-9, |12-9|, |9-9|) = 3
    // TR[2] = max(13-10, |13-11|, |10-11|) = 3
    // TR[3] = max(14-11, |14-12|, |11-12|) = 3
    // TR[4] = max(16-12, |16-13|, |12-13|) = 4
    // period=2: out[2] = avg(TR1,TR2) = 3
    // out[3] = (3*1 + 3)/2 = 3
    // out[4] = (3*1 + 4)/2 = 3.5
    const out = atr(highs, lows, closes, 2);
    expect(out[0]).toBeNaN();
    expect(out[1]).toBeNaN();
    expect(out[2]).toBeCloseTo(3, 10);
    expect(out[3]).toBeCloseTo(3, 10);
    expect(out[4]).toBeCloseTo(3.5, 10);
  });
});
