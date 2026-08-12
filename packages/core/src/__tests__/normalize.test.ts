import { describe, expect, it } from 'vitest';
import { sectorNeutralize, winsorize, zscore } from '../normalize';

describe('winsorize', () => {
  it('clips the extremes to the p/1-p quantile bounds', () => {
    // n=10, p=0.2 -> lowerIdx=floor(0.2*9)=1 -> sorted[1]=2; upperIdx=ceil(0.8*9)=8 -> sorted[8]=9
    const xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    expect(winsorize(xs, 0.2)).toEqual([2, 2, 3, 4, 5, 6, 7, 8, 9, 9]);
  });
});

describe('zscore', () => {
  it('matches the [2,4,4,4,5,5,7,9] textbook example (mean=5, sd=2)', () => {
    const xs = [2, 4, 4, 4, 5, 5, 7, 9];
    const out = zscore(xs);
    const expected = [-1.5, -0.5, -0.5, -0.5, 0, 0, 1, 2];
    out.forEach((v, i) => expect(v).toBeCloseTo(expected[i], 10));
  });

  it('returns all zeros for a constant series (zero variance)', () => {
    expect(zscore([5, 5, 5])).toEqual([0, 0, 0]);
  });
});

describe('sectorNeutralize', () => {
  it('demeans each score against its own sector group', () => {
    const scores = new Map([
      ['A', 10],
      ['B', 20],
      ['C', 5],
      ['D', 15],
    ]);
    const sector = new Map([
      ['A', 'tech'],
      ['B', 'tech'],
      ['C', 'finance'],
      ['D', 'finance'],
    ]);
    const result = sectorNeutralize(scores, sector);
    expect(result.get('A')).toBeCloseTo(-5, 10);
    expect(result.get('B')).toBeCloseTo(5, 10);
    expect(result.get('C')).toBeCloseTo(-5, 10);
    expect(result.get('D')).toBeCloseTo(5, 10);
  });
});
