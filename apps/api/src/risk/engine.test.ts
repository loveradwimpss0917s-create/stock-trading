import { describe, expect, it } from 'vitest';
import {
  PASS_GATES,
  WAIT_GATES,
  evaluateRisk,
  positionSize,
  type Account,
  type PlanLevels,
  type PortfolioContext,
} from './engine';

// Mirrors pipeline_py/tests/test_risk_engine.py scenario-for-scenario so the
// two implementations can be diffed by eye when one changes.

function account(overrides: Partial<Account> = {}): Account {
  return {
    capital: 5_000_000,
    risk_per_trade: 0.005,
    max_positions: 5,
    max_heat: 0.03,
    max_notional_pct: 0.3,
    min_rr: 1.5,
    max_sector_positions: 2,
    ...overrides,
  };
}

function levels(overrides: Partial<PlanLevels> = {}): PlanLevels {
  return {
    triggerPrice: 4250.0,
    stopPlanned: 4080.0,
    targetPlanned: 4600.0,
    sector33: '3650',
    turnoverValue: 1_000_000_000,
    avgVolume20d: 5_000_000,
    ...overrides,
  };
}

function ctx(overrides: Partial<PortfolioContext> = {}): PortfolioContext {
  return { openPositions: 0, currentHeat: 0, sectorPositionCounts: {}, ...overrides };
}

describe('positionSize', () => {
  it('sizes off the stop distance and floors to the lot', () => {
    const { shares, riskAmount } = positionSize(5_000_000, 0.005, 4250.0, 4080.0);
    expect(shares).toBe(100);
    expect(riskAmount).toBe(100 * 170.0);
  });

  it('never exceeds the target risk', () => {
    const { riskAmount } = positionSize(5_000_000, 0.005, 4250.0, 4080.0);
    expect(riskAmount).toBeLessThanOrEqual(5_000_000 * 0.005);
  });

  it('yields no position for zero or negative risk per share', () => {
    expect(positionSize(5_000_000, 0.005, 100, 100)).toEqual({ shares: 0, riskAmount: 0 });
    expect(positionSize(5_000_000, 0.005, 100, 105)).toEqual({ shares: 0, riskAmount: 0 });
  });
});

describe('evaluateRisk gate decisions', () => {
  it('returns BUY when every gate passes', () => {
    const v = evaluateRisk(account(), levels(), ctx());
    expect(v.decision).toBe('BUY');
    expect(v.reasonCode).toBe('all_gates_passed');
    expect(Object.values(v.gates).every((g) => g.passed)).toBe(true);
  });

  it('PASSes on R:R below the minimum', () => {
    const v = evaluateRisk(account(), levels({ targetPlanned: 4350.0 }), ctx());
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('min_rr');
  });

  it('PASSes when shares fall below the lot size', () => {
    const v = evaluateRisk(account({ capital: 10_000 }), levels(), ctx());
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('lot_size');
  });

  it('PASSes when notional exceeds the cap', () => {
    const v = evaluateRisk(
      account({ capital: 5_000_000, max_notional_pct: 0.3 }),
      levels({ triggerPrice: 1000, stopPlanned: 999, targetPlanned: 1002 }),
      ctx()
    );
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('notional');
  });

  it('PASSes on illiquid turnover', () => {
    const v = evaluateRisk(account(), levels({ turnoverValue: 100_000_000 }), ctx());
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('turnover');
  });

  it('does not block on missing turnover', () => {
    const v = evaluateRisk(account(), levels({ turnoverValue: null }), ctx());
    expect(v.gates.turnover.passed).toBe(true);
  });

  it('PASSes when shares exceed 1% of ADV', () => {
    const v = evaluateRisk(account(), levels({ avgVolume20d: 1000 }), ctx());
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('liquidity');
  });

  it('WAITs, not PASSes, when heat is exceeded', () => {
    const v = evaluateRisk(account({ max_heat: 0.001 }), levels(), ctx({ currentHeat: 0 }));
    expect(v.decision).toBe('WAIT');
    expect(v.reasonCode).toBe('heat');
  });

  it('WAITs when max positions are reached', () => {
    const v = evaluateRisk(account({ max_positions: 2 }), levels(), ctx({ openPositions: 2 }));
    expect(v.decision).toBe('WAIT');
    expect(v.reasonCode).toBe('max_positions');
  });

  it('WAITs on sector concentration', () => {
    const v = evaluateRisk(
      account({ max_sector_positions: 2 }),
      levels({ sector33: '3650' }),
      ctx({ sectorPositionCounts: { '3650': 2 } })
    );
    expect(v.decision).toBe('WAIT');
    expect(v.reasonCode).toBe('sector_concentration');
  });

  it('does not let a missing sector inherit another sectors count', () => {
    const v = evaluateRisk(
      account({ max_sector_positions: 1 }),
      levels({ sector33: null }),
      ctx({ sectorPositionCounts: { '3700': 5 } })
    );
    expect(v.gates.sector_concentration.passed).toBe(true);
    expect(v.gates.sector_concentration.value).toBe(0);
  });
});

describe('gate priority', () => {
  it('an instrument-level PASS beats a simultaneous portfolio-level WAIT', () => {
    const v = evaluateRisk(
      account({ max_positions: 0 }),
      levels({ targetPlanned: 4300.0 }),
      ctx({ openPositions: 1 })
    );
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('min_rr');
  });

  it('every gate is populated even when an early one fails', () => {
    const v = evaluateRisk(account(), levels({ targetPlanned: 4300.0 }), ctx());
    expect(Object.keys(v.gates).sort()).toEqual([...PASS_GATES, ...WAIT_GATES].sort());
  });
});
