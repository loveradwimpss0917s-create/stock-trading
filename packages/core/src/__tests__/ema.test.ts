import { describe, expect, it } from 'vitest';
import { ema } from '../indicators/ema';

describe('ema', () => {
  it('matches a hand-computed EMA for a known linear series', () => {
    // values: 1,2,3,4,5, period=3, k=2/(3+1)=0.5
    // seed = SMA(1,2,3) = 2 at index2
    // i=3: 4*0.5 + 2*0.5 = 3
    // i=4: 5*0.5 + 3*0.5 = 4
    const out = ema([1, 2, 3, 4, 5], 3);
    expect(out[0]).toBeNaN();
    expect(out[1]).toBeNaN();
    expect(out[2]).toBeCloseTo(2, 10);
    expect(out[3]).toBeCloseTo(3, 10);
    expect(out[4]).toBeCloseTo(4, 10);
  });

  it('returns all-NaN when there are fewer values than the period', () => {
    const out = ema([1, 2], 5);
    expect(out.every((v) => Number.isNaN(v))).toBe(true);
  });
});
