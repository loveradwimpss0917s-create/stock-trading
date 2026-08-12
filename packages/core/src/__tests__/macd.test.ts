import { describe, expect, it } from 'vitest';
import { macd } from '../indicators/macd';

describe('macd', () => {
  it('matches a hand-computed MACD for a known linear series', () => {
    // values: 1..6, fast=2 (k=2/3), slow=3 (k=0.5), signal=2 (k=2/3)
    // emaFast = [NaN,1.5,2.5,3.5,4.5,5.5]
    // emaSlow = [NaN,NaN,2,3,4,5]
    // macdLine = [NaN,NaN,0.5,0.5,0.5,0.5]  (constant once both EMAs are warm, since the series is linear)
    // signal (EMA of [0.5,0.5,0.5,0.5], period 2) = [NaN,0.5,0.5,0.5] -> aligned back to [NaN,NaN,NaN,0.5,0.5,0.5]
    // histogram = macd - signal = [NaN,NaN,NaN,0,0,0]
    const { macdLine, signalLine, histogram } = macd([1, 2, 3, 4, 5, 6], 2, 3, 2);

    expect(macdLine.slice(2)).toEqual([0.5, 0.5, 0.5, 0.5]);
    expect(macdLine[0]).toBeNaN();
    expect(macdLine[1]).toBeNaN();

    expect(signalLine[2]).toBeNaN();
    expect(signalLine.slice(3)).toEqual([0.5, 0.5, 0.5]);

    expect(histogram[2]).toBeNaN();
    histogram.slice(3).forEach((v) => expect(v).toBeCloseTo(0, 10));
  });
});
