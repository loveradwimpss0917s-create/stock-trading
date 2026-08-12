import { describe, expect, it } from 'vitest';
import { rsi } from '../indicators/rsi';

describe('rsi', () => {
  it('matches a hand-computed Wilder RSI for a known series', () => {
    // closes: 10 -> 12 -> 11 -> 15, period=2
    // deltas: +2, -1, +4
    // seed (i=1..2): gain=(2+0)/2=1, loss=(0+1)/2=0.5 -> RSI = 100-100/(1+1/0.5) = 100-100/3
    // i=3: gain=(1*1+4)/2=2.5, loss=(0.5*1+0)/2=0.25 -> RSI = 100-100/(1+2.5/0.25) = 100-100/11
    const out = rsi([10, 12, 11, 15], 2);
    expect(out[0]).toBeNaN();
    expect(out[1]).toBeNaN();
    expect(out[2]).toBeCloseTo(100 - 100 / 3, 10);
    expect(out[3]).toBeCloseTo(100 - 100 / 11, 10);
  });

  it('returns 100 for a strictly increasing series (no losses)', () => {
    const out = rsi([1, 2, 3, 4, 5], 2);
    expect(out[2]).toBeCloseTo(100, 6);
    expect(out[3]).toBeCloseTo(100, 6);
    expect(out[4]).toBeCloseTo(100, 6);
  });
});
