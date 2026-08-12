import { describe, expect, it } from 'vitest';
import { bollingerBands } from '../indicators/bollingerBands';

describe('bollingerBands', () => {
  it('matches the textbook [2,4,4,4,5,5,7,9] population-stddev example', () => {
    // mean = 40/8 = 5; deviations [-3,-1,-1,-1,0,0,2,4]; squared sum = 32
    // population variance = 32/8 = 4 -> sd = 2
    const closes = [2, 4, 4, 4, 5, 5, 7, 9];
    const { middle, upper, lower } = bollingerBands(closes, 8, 2);

    expect(middle[7]).toBeCloseTo(5, 10);
    expect(upper[7]).toBeCloseTo(9, 10);
    expect(lower[7]).toBeCloseTo(1, 10);
    expect(middle.slice(0, 7).every((v) => Number.isNaN(v))).toBe(true);
  });
});
