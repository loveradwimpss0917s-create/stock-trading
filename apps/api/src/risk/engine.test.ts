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
      // 1% stop rather than 0.1%: at 0.1% the round trip alone is ~1R, so
      // the plan would fail on cost before ever reaching the notional gate.
      levels({ triggerPrice: 1000, stopPlanned: 990, targetPlanned: 1020 }),
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

describe('cost-aware R:R', () => {
  // The gate is evaluated net of execution cost. Every figure the app
  // reported before this was gross, i.e. a return nobody could have taken.

  it('reports a lower R:R than the chart says', () => {
    const v = evaluateRisk(account(), levels(), ctx());
    expect(v.rrNet).toBeLessThan(v.rrGross);
    expect(v.gates.min_rr.gross).toBeGreaterThan(v.gates.min_rr.value!);
  });

  it('rejects a plan that only clears the bar before cost', () => {
    // risk 170/share; a target of exactly 1.5R gross is 4250 + 255.
    const v = evaluateRisk(account({ min_rr: 1.5 }), levels({ targetPlanned: 4505.0 }), ctx());
    expect(v.gates.min_rr.gross).toBeGreaterThanOrEqual(1.5);
    expect(v.decision).toBe('PASS');
    expect(v.reasonCode).toBe('min_rr_after_cost');
  });

  it('still reads a genuinely bad R:R as an ordinary rejection', () => {
    const v = evaluateRisk(account(), levels({ targetPlanned: 4350.0 }), ctx());
    expect(v.reasonCode).toBe('min_rr');
  });

  it('charges more in R for a tighter stop at identical execution', () => {
    // 'Risking less per share' makes the trade more expensive in its own
    // risk unit, because the unit shrank faster than the cost did.
    const atr = 100;
    const tight = evaluateRisk(
      account({ min_rr: 0 }),
      levels({ triggerPrice: 4250, stopPlanned: 4150, targetPlanned: 4550, atr }),
      ctx()
    );
    const wide = evaluateRisk(
      account({ min_rr: 0 }),
      levels({ triggerPrice: 4250, stopPlanned: 4050, targetPlanned: 4850, atr }),
      ctx()
    );
    expect(tight.rrGross).toBeCloseTo(wide.rrGross, 10);
    expect(tight.economics!.costLossR).toBeGreaterThan(wide.economics!.costLossR);
    expect(tight.rrNet).toBeLessThan(wide.rrNet);
  });

  it('raises the break-even win rate once cost is charged', () => {
    const e = evaluateRisk(account(), levels({ atr: 100 }), ctx()).economics!;
    expect(e.requiredWinRateNet!).toBeGreaterThan(e.requiredWinRateGross!);
  });

  it('reports no win rate for a plan that cannot cover its own cost', () => {
    const v = evaluateRisk(
      account({ min_rr: 0 }),
      levels({ triggerPrice: 1000, stopPlanned: 999, targetPlanned: 1000.5 }),
      ctx()
    );
    expect(v.rrNet).toBeLessThan(0);
    expect(v.economics!.requiredWinRateNet).toBeNull();
    expect(v.decision).toBe('PASS');
  });

  it('falls back to the slippage floor rather than to zero cost without ATR', () => {
    const v = evaluateRisk(account(), levels({ atr: null }), ctx());
    expect(v.economics!.costWinR).toBeGreaterThan(0);
  });

  it('reports no economics for an inverted stop', () => {
    const v = evaluateRisk(account(), levels({ stopPlanned: 4300 }), ctx());
    expect(v.economics).toBeNull();
    expect(v.rrNet).toBe(0);
    expect(v.decision).toBe('PASS');
  });
});
