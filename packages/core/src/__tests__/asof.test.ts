import { describe, expect, it } from 'vitest';
import { assertNoLookahead } from '../asof';

describe('assertNoLookahead', () => {
  it('does not throw when known_from is at or before the signal date', () => {
    const signal = new Date('2026-08-07T00:00:00Z');
    expect(() => assertNoLookahead(new Date('2026-08-06T00:00:00Z'), signal)).not.toThrow();
    expect(() => assertNoLookahead(signal, signal)).not.toThrow();
  });

  it('throws when known_from is after the signal date', () => {
    const signal = new Date('2026-08-07T00:00:00Z');
    const knownFrom = new Date('2026-08-08T00:00:00Z');
    expect(() => assertNoLookahead(knownFrom, signal)).toThrow(/Look-ahead/);
  });
});
