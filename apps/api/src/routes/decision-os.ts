import { Hono } from 'hono';
import { insertInto, selectFrom, updateWhere, type SupabaseEnv } from '../db/supabase';
import { evaluateRisk, type Account, type Decision, type PlanLevels, type PortfolioContext } from '../risk/engine';

const app = new Hono<{ Bindings: SupabaseEnv }>();

interface AccountRow {
  id: number;
  capital: string;
  risk_per_trade: string;
  max_positions: number;
  max_heat: string;
  max_notional_pct: string;
  min_rr: string;
  max_sector_positions: number;
}

interface PlanRow {
  id: number;
  account_id: number;
  code: string;
  setup_key: string;
  state: string;
  reference_close: string;
  trigger_price: string;
  stop_planned: string;
  target_planned: string;
  invalidation: { type: string; level: number; source_ref?: string };
  expires_on: string;
  thesis: string | null;
  anti_thesis: string | null;
  expected_rr: string;
  shares_planned: number | null;
  risk_amount: string | null;
  risk_pct: string | null;
  scenarios: unknown;
  setup_name?: string;
  setup_horizon?: string;
  setup_hypothesis?: string;
  setup_stop_rule?: { type: string; mult: number } | null;
  atr?: string | number | null;
  ticker4?: string;
  security_name?: string;
  sector33?: string | null;
  current_price?: string | null;
  created_on: string;
  triggered_on: string | null;
  triggered_price: string | null;
}

interface PositionRow {
  id: number;
  plan_id: number;
  account_id: number;
  code: string;
  opened_on: string;
  entry_price: string;
  shares: number;
  stop_current: string;
  target_current: string;
  time_stop_on: string;
  status: 'open' | 'closed';
  closed_on: string | null;
  exit_price: string | null;
  exit_reason: string | null;
  pnl_yen: string | null;
  r_multiple: string | null;
  ticker4?: string;
  security_name?: string;
  sector33?: string | null;
  current_price?: string | null;
  current_risk?: string | null;
  current_r?: string | null;
}

async function loadAccount(env: SupabaseEnv, accountId?: number): Promise<AccountRow> {
  const rows = await selectFrom<AccountRow>(env, 'accounts', {
    select: '*',
    ...(accountId ? { id: `eq.${accountId}` } : {}),
    order: 'id.asc',
    limit: '1',
  });
  if (!rows[0]) throw new Error('no account configured');
  return rows[0];
}

function toAccount(row: AccountRow): Account {
  return {
    capital: Number(row.capital),
    risk_per_trade: Number(row.risk_per_trade),
    max_positions: row.max_positions,
    max_heat: Number(row.max_heat),
    max_notional_pct: Number(row.max_notional_pct),
    min_rr: Number(row.min_rr),
    max_sector_positions: row.max_sector_positions,
  };
}

/** Portfolio heat from open positions' CURRENT stop distance, not entry —
 * a position whose stop has been walked to breakeven frees up capacity for
 * a new one, which is the whole point of measuring it this way (design
 * PART 8). Falls back to entry-based risk when current_price hasn't been
 * backfilled for a code yet, rather than silently treating it as zero risk. */
async function loadPortfolioContext(env: SupabaseEnv, accountId: number): Promise<PortfolioContext> {
  const open = await selectFrom<PositionRow>(env, 'positions_view', {
    select: 'shares,entry_price,stop_current,current_risk,sector33',
    account_id: `eq.${accountId}`,
    status: 'eq.open',
  });
  const account = await loadAccount(env, accountId);
  const capital = Number(account.capital);

  let heatSum = 0;
  const sectorCounts: Record<string, number> = {};
  for (const p of open) {
    const fallback = (Number(p.entry_price) - Number(p.stop_current)) * p.shares;
    const risk = p.current_risk != null ? Number(p.current_risk) : fallback;
    heatSum += Math.max(risk, 0);
    if (p.sector33) sectorCounts[p.sector33] = (sectorCounts[p.sector33] ?? 0) + 1;
  }

  return {
    openPositions: open.length,
    currentHeat: capital ? heatSum / capital : 0,
    sectorPositionCounts: sectorCounts,
  };
}

/** ATR isn't a column on trade_plans, but it doesn't need to be: the stop is
 * defined as trigger − mult × ATR, so the multiple recovers it exactly. The
 * cost model needs it because slippage scales with range — without it the
 * flat floor applies and cost comes out optimistically low on exactly the
 * volatile names where it is worst. */
function impliedAtr(plan: PlanRow): number | null {
  if (plan.atr != null) return Number(plan.atr);
  const rule = plan.setup_stop_rule;
  if (rule?.type !== 'atr_mult' || !rule.mult) return null;
  const risk = Number(plan.trigger_price) - Number(plan.stop_planned);
  if (!(risk > 0)) return null;
  return risk / rule.mult;
}

function toPlanLevels(plan: PlanRow): PlanLevels {
  return {
    triggerPrice: Number(plan.trigger_price),
    stopPlanned: Number(plan.stop_planned),
    targetPlanned: Number(plan.target_planned),
    sector33: plan.sector33,
    atr: impliedAtr(plan),
    // Turnover/ADV aren't columns on trade_plans (resolved once at draft
    // time by the Python scan batch, not re-fetched here) — the liquidity
    // gates were already evaluated as part of candidate_rule before the
    // plan was drafted, so re-checking them against possibly-stale figures
    // at decision time would just be noise. R:R, notional, heat, position
    // count, and sector concentration are the gates that meaningfully
    // change between drafting and deciding.
    turnoverValue: null,
    avgVolume20d: null,
  };
}

// ---------------------------------------------------------------------
app.get('/setups', async (c) => {
  const setups = await selectFrom<Record<string, unknown>>(c.env, 'setups', {
    select: 'key,name_ja,horizon,hypothesis,time_stop_bars,expiry_bars,min_rr',
    enabled: 'eq.true',
    order: 'sort_order.asc',
  });
  return c.json({ setups });
});

/** Setup performance against the control — never the raw avg_r alone.
 *
 * The theme system taught this the expensive way: every theme showed a
 * positive average R until screen_baseline was subtracted, at which point
 * the whole effect turned out to be the rising market. edge_r (Setup minus
 * "buy everything tradable, same sessions, same ATR multiples") is the
 * only number here that says whether choosing helped, so the raw figures
 * are returned alongside it rather than on their own. */
app.get('/setup-performance', async (c) => {
  const rows = await selectFrom<Record<string, unknown>>(c.env, 'setup_edge', {
    select: '*',
    order: 'setup_key.asc',
  });
  return c.json({ performance: rows });
});

/**
 * The discipline audit. Nothing here depends on a Setup or Regime being
 * valid — it only reports what the user did relative to their own plan,
 * which is arithmetic about the past rather than a claim about the future.
 * That makes it the half of the app that is trustworthy today.
 *
 * Both shapes are returned together because the summary is the number that
 * matters and the per-position rows are what make it arguable: a rate with
 * no way to see which trades produced it invites dismissal.
 */
app.get('/discipline', async (c) => {
  const accountId = c.req.query('account_id') ?? '1';
  const [summary, positions] = await Promise.all([
    selectFrom<Record<string, unknown>>(c.env, 'discipline_summary', {
      select: '*',
      account_id: `eq.${accountId}`,
    }),
    selectFrom<Record<string, unknown>>(c.env, 'position_behaviour', {
      select: '*',
      account_id: `eq.${accountId}`,
      order: 'opened_on.desc',
    }),
  ]);
  return c.json({ summary: summary[0] ?? null, positions });
});

app.get('/regime', async (c) => {
  const date = c.req.query('date');
  const rows = await selectFrom<Record<string, unknown>>(c.env, 'regime_snapshots', {
    select: '*',
    order: 'date.desc',
    limit: '1',
    ...(date ? { date: `eq.${date}` } : {}),
  });
  return c.json(rows[0] ?? null);
});

app.get('/plans', async (c) => {
  const state = c.req.query('state');
  const query: Record<string, string> = { select: '*', order: 'created_on.desc,id.desc' };
  if (state) query.state = `in.(${state})`;
  const plans = await selectFrom<PlanRow>(c.env, 'trade_plans_view', query);
  return c.json({ plans });
});

/**
 * Create a plan by hand.
 *
 * Until this existed, kabu could only hold trades its own batch drafted
 * from 84-day-old data — which is to say, no trade the user actually took.
 * The Risk Engine never sized a real position and the discipline record
 * had nothing to record. For an app whose remaining value is risk and
 * discipline rather than stock selection, that was not a missing feature
 * but a missing premise.
 *
 * Levels are required and rejected if inconsistent. That is not
 * bureaucracy: a trade without a stop written down before entry has no R,
 * and without an R nothing else in this app can say anything about it.
 * The thesis is required for the same reason a reason_code is — a trade
 * whose rationale was never written cannot be reviewed afterwards, only
 * rationalised.
 */
app.post('/plans', async (c) => {
  const body = await c.req.json<{
    code: string;
    trigger_price: number;
    stop_planned: number;
    target_planned: number;
    thesis: string;
    anti_thesis?: string;
    atr?: number | null;
    reference_close?: number | null;
    time_stop_bars?: number;
    expires_on?: string;
    invalidation_note?: string;
    account_id?: number;
  }>();

  const code = String(body.code ?? '').trim();
  const trigger = Number(body.trigger_price);
  const stop = Number(body.stop_planned);
  const target = Number(body.target_planned);

  if (!code) return c.json({ error: 'code is required' }, 400);
  if (!Number.isFinite(trigger) || !Number.isFinite(stop) || !Number.isFinite(target)) {
    return c.json({ error: 'trigger_price, stop_planned and target_planned are required' }, 400);
  }
  if (stop >= trigger) {
    return c.json({ error: 'ストップはエントリーより下でなければ、リスクが定義できません。' }, 400);
  }
  if (target <= trigger) {
    return c.json({ error: '目標はエントリーより上でなければ、リワードが定義できません。' }, 400);
  }
  if (!body.thesis?.trim()) {
    return c.json({ error: '根拠の記入は必須です。後から検証できない記録は残す意味がありません。' }, 400);
  }

  const securities = await selectFrom<{ code: string }>(c.env, 'securities', {
    select: 'code',
    code: `eq.${code}`,
  });
  if (!securities[0]) return c.json({ error: `未知の銘柄コードです: ${code}` }, 400);

  const today = new Date().toISOString().slice(0, 10);
  const riskPerShare = trigger - stop;
  const created = await insertInto<PlanRow>(c.env, 'trade_plans', [
    {
      account_id: body.account_id ?? 1,
      code,
      setup_key: 'manual',
      created_on: today,
      state: 'armed', // already decided to watch it; there is no scan to arm it
      reference_close: body.reference_close ?? trigger,
      trigger_price: trigger,
      trigger_condition: { type: 'manual', note: '手入力' },
      stop_planned: stop,
      target_planned: target,
      atr: body.atr ?? null,
      time_stop_bars: body.time_stop_bars ?? 10,
      expires_on: body.expires_on ?? today,
      invalidation: {
        type: 'manual',
        level: stop,
        note: body.invalidation_note ?? '手入力（ストップ到達を反証とする）',
      },
      thesis: body.thesis.trim(),
      anti_thesis: body.anti_thesis?.trim() || null,
      expected_rr: Number(((target - trigger) / riskPerShare).toFixed(3)),
    },
  ]);

  return c.json({ plan: created[0] }, 201);
});

app.get('/plans/:id', async (c) => {
  const id = c.req.param('id');
  const rows = await selectFrom<PlanRow>(c.env, 'trade_plans_view', { select: '*', id: `eq.${id}` });
  if (!rows[0]) return c.json({ error: 'not found' }, 404);
  return c.json(rows[0]);
});

/** thesis / anti_thesis / scenarios only — everything else on a plan is
 * either resolved once by the scan batch (levels, trigger, invalidation)
 * or advanced by the state-machine batch. This is the one write a human
 * makes to a plan before deciding on it. */
app.patch('/plans/:id', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ thesis?: string; anti_thesis?: string; scenarios?: unknown }>();
  const patch: Record<string, unknown> = {};
  if (body.thesis !== undefined) patch.thesis = body.thesis;
  if (body.anti_thesis !== undefined) patch.anti_thesis = body.anti_thesis;
  if (body.scenarios !== undefined) patch.scenarios = body.scenarios;
  if (Object.keys(patch).length === 0) {
    return c.json({ error: 'nothing to update' }, 400);
  }
  const updated = await updateWhere<PlanRow>(c.env, 'trade_plans', { id: `eq.${id}` }, patch);
  if (!updated[0]) return c.json({ error: 'not found' }, 404);
  return c.json(updated[0]);
});

/** The Risk Engine verdict for a plan against the CURRENT portfolio state
 * — not a batch-precomputed value, since heat and open-position count
 * change the moment another position opens or closes. */
app.get('/plans/:id/risk', async (c) => {
  const id = c.req.param('id');
  const rows = await selectFrom<PlanRow>(c.env, 'trade_plans_view', { select: '*', id: `eq.${id}` });
  const plan = rows[0];
  if (!plan) return c.json({ error: 'not found' }, 404);

  const accountRow = await loadAccount(c.env, plan.account_id);
  const ctx = await loadPortfolioContext(c.env, plan.account_id);
  const verdict = evaluateRisk(toAccount(accountRow), toPlanLevels(plan), ctx);
  return c.json(verdict);
});

const VALID_DECISIONS: Decision[] = ['BUY', 'WAIT', 'PASS'];

/** BUY or WAIT both arm the plan (design's stated draft->armed arrow for
 * either outcome — WAIT means the setup itself is fine but the portfolio
 * has no room right now, and armed lets it keep watching for the trigger
 * while capacity frees up). PASS is terminal. Every decision requires a
 * reason_code — that is the No-Trade Engine: a rejection with no reason
 * attached teaches nothing on review. thesis is required before BUY/WAIT
 * arms the plan (DB also enforces this at the state level, migration
 * 0023) — checked here first so the caller gets a clear 400 instead of a
 * raw constraint-violation message. */
app.post('/plans/:id/decide', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{ decision: string; reason_code: string; reason_note?: string }>();

  if (!VALID_DECISIONS.includes(body.decision as Decision)) {
    return c.json({ error: `decision must be one of ${VALID_DECISIONS.join('/')}` }, 400);
  }
  if (!body.reason_code?.trim()) {
    return c.json({ error: 'reason_code is required' }, 400);
  }

  const rows = await selectFrom<PlanRow>(c.env, 'trade_plans_view', { select: '*', id: `eq.${id}` });
  const plan = rows[0];
  if (!plan) return c.json({ error: 'not found' }, 404);
  if (plan.state !== 'draft') {
    return c.json({ error: `plan is already ${plan.state}, not draft` }, 409);
  }

  const decision = body.decision as Decision;
  if (decision !== 'PASS' && !plan.thesis?.trim()) {
    return c.json({ error: 'thesis is required before BUY or WAIT' }, 400);
  }

  const accountRow = await loadAccount(c.env, plan.account_id);
  const ctx = await loadPortfolioContext(c.env, plan.account_id);
  const verdict = evaluateRisk(toAccount(accountRow), toPlanLevels(plan), ctx);

  await insertInto(c.env, 'plan_decisions', [
    {
      plan_id: Number(id),
      decision,
      reason_code: body.reason_code,
      reason_note: body.reason_note ?? null,
      gate_results: verdict.gates,
    },
  ]);

  const newState = decision === 'PASS' ? 'passed' : 'armed';
  const patch: Record<string, unknown> =
    decision === 'PASS'
      ? { state: newState }
      : {
          state: newState,
          shares_planned: verdict.shares,
          risk_amount: verdict.riskAmount,
          risk_pct: verdict.riskPct,
        };

  const updated = await updateWhere<PlanRow>(c.env, 'trade_plans', { id: `eq.${id}` }, patch);
  return c.json({ plan: updated[0], verdict });
});

// ---------------------------------------------------------------------
app.get('/positions', async (c) => {
  const status = c.req.query('status');
  const query: Record<string, string> = { select: '*', order: 'opened_on.desc' };
  if (status) query.status = `eq.${status}`;
  const positions = await selectFrom<PositionRow>(c.env, 'positions_view', query);
  return c.json({ positions });
});

/** Records an actual fill against a triggered plan. Shares/prices are
 * supplied by the caller (the real fill, not necessarily the planned one —
 * see execution_adherence in trade_journal for judging the gap) rather than
 * recomputed, since what happened is what happened. */
app.post('/positions', async (c) => {
  const body = await c.req.json<{
    plan_id: number;
    opened_on: string;
    entry_price: number;
    shares: number;
  }>();

  const rows = await selectFrom<PlanRow>(c.env, 'trade_plans_view', {
    select: '*',
    id: `eq.${body.plan_id}`,
  });
  const plan = rows[0];
  if (!plan) return c.json({ error: 'plan not found' }, 404);
  if (plan.state !== 'triggered') {
    return c.json({ error: `plan is ${plan.state}, not triggered` }, 409);
  }

  const setupRows = await selectFrom<{ time_stop_bars: number }>(c.env, 'setups', {
    select: 'time_stop_bars',
    key: `eq.${plan.setup_key}`,
  });
  const timeStopBars = setupRows[0]?.time_stop_bars ?? 10;
  const timeStopOn = addTradingDays(body.opened_on, timeStopBars);

  const created = await insertInto<PositionRow>(c.env, 'positions', [
    {
      plan_id: body.plan_id,
      account_id: plan.account_id,
      code: plan.code,
      opened_on: body.opened_on,
      entry_price: body.entry_price,
      shares: body.shares,
      stop_current: plan.stop_planned,
      target_current: plan.target_planned,
      time_stop_on: timeStopOn,
      status: 'open',
    },
  ]);

  await updateWhere(c.env, 'trade_plans', { id: `eq.${plan.id}` }, { state: 'open' });

  return c.json({ position: created[0] });
});

app.post('/positions/:id/events', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{
    occurred_on: string;
    event_type: string;
    price?: number;
    note?: string;
    thesis_status?: string;
    new_stop?: number;
    new_target?: number;
  }>();

  const created = await insertInto(c.env, 'position_events', [
    {
      position_id: Number(id),
      occurred_on: body.occurred_on,
      event_type: body.event_type,
      price: body.price ?? null,
      note: body.note ?? null,
      thesis_status: body.thesis_status ?? null,
    },
  ]);

  // A stop/target move is both an event (the record of why) and a change
  // to the position's live levels (what heat and future barrier checks use).
  const patch: Record<string, unknown> = {};
  if (body.new_stop !== undefined) patch.stop_current = body.new_stop;
  if (body.new_target !== undefined) patch.target_current = body.new_target;
  if (Object.keys(patch).length > 0) {
    await updateWhere(c.env, 'positions', { id: `eq.${id}` }, patch);
  }

  return c.json({ event: created[0] });
});

/** Closes a position and forces the review fields in the same call —
 * design PART 9's point that a decision is not fully recorded without them.
 * There is no way to close a position through this API without answering
 * "was the thesis right" and "was execution as planned". */
app.post('/positions/:id/close', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<{
    closed_on: string;
    exit_price: number;
    exit_reason: string;
    thesis_was_correct: boolean;
    execution_adherence: string;
    review_note?: string;
  }>();

  const rows = await selectFrom<PositionRow>(c.env, 'positions_view', { select: '*', id: `eq.${id}` });
  const position = rows[0];
  if (!position) return c.json({ error: 'not found' }, 404);
  if (position.status === 'closed') return c.json({ error: 'already closed' }, 409);

  const entry = Number(position.entry_price);
  const stop = Number(position.stop_current);
  const riskPerShare = entry - stop;
  const pnlYen = (body.exit_price - entry) * position.shares;
  const rMultiple = riskPerShare > 0 ? (body.exit_price - entry) / riskPerShare : null;

  await updateWhere(
    c.env,
    'positions',
    { id: `eq.${id}` },
    {
      status: 'closed',
      closed_on: body.closed_on,
      exit_price: body.exit_price,
      exit_reason: body.exit_reason,
      pnl_yen: Math.round(pnlYen * 100) / 100,
      r_multiple: rMultiple !== null ? Math.round(rMultiple * 10000) / 10000 : null,
    }
  );

  await insertInto(c.env, 'trade_journal', [
    {
      position_id: Number(id),
      thesis_was_correct: body.thesis_was_correct,
      execution_adherence: body.execution_adherence,
      review_note: body.review_note ?? null,
      reviewed_at: new Date().toISOString(),
    },
  ]);

  return c.json({ ok: true });
});

app.get('/journal', async (c) => {
  const [positions, journal] = await Promise.all([
    selectFrom<PositionRow>(c.env, 'positions_view', {
      select: '*',
      status: 'eq.closed',
      order: 'closed_on.desc',
    }),
    selectFrom<Record<string, unknown>>(c.env, 'trade_journal', { select: '*' }),
  ]);
  const journalByPosition = new Map(journal.map((j) => [j.position_id, j]));
  const rows = positions.map((p) => ({ ...p, journal: journalByPosition.get(p.id) ?? null }));
  return c.json({ journal: rows });
});

// ---------------------------------------------------------------------
/** Everything the home screen needs in one round trip, in the order the
 * design puts them: action items first, then open positions, then plans
 * still watching for a trigger, then Regime (context, not a gate), then a
 * capped preview of fresh draft candidates. Zero action items and zero new
 * candidates are both normal, valid responses — nothing here backfills a
 * quota to avoid an empty section. */
app.get('/home', async (c) => {
  const accountRow = await loadAccount(c.env);
  const account = toAccount(accountRow);

  const [openPositions, monitoring, drafts, regimeRows] = await Promise.all([
    selectFrom<PositionRow>(c.env, 'positions_view', {
      select: '*',
      account_id: `eq.${accountRow.id}`,
      status: 'eq.open',
      order: 'opened_on.asc',
    }),
    selectFrom<PlanRow>(c.env, 'trade_plans_view', {
      select: '*',
      account_id: `eq.${accountRow.id}`,
      state: 'in.(armed,triggered)',
      order: 'expires_on.asc',
    }),
    selectFrom<PlanRow>(c.env, 'trade_plans_view', {
      select: '*',
      account_id: `eq.${accountRow.id}`,
      state: 'eq.draft',
      order: 'setup_key.asc,expected_rr.desc',
      limit: '30',
    }),
    selectFrom<Record<string, unknown>>(c.env, 'regime_snapshots', {
      select: '*',
      order: 'date.desc',
      limit: '1',
    }),
  ]);

  const ctx = await loadPortfolioContext(c.env, accountRow.id);

  const triggeredAwaitingEntry = monitoring.filter((p) => p.state === 'triggered');
  const armedWatching = monitoring.filter((p) => p.state === 'armed');
  const expiringSoon = armedWatching.filter((p) => {
    const days = (new Date(p.expires_on).getTime() - Date.now()) / 86_400_000;
    return days <= 2;
  });

  const actions: { kind: string; message: string; ref_id: number }[] = [];
  for (const p of triggeredAwaitingEntry) {
    actions.push({
      kind: 'record_entry',
      message: `${p.ticker4} ${p.security_name ?? ''} がトリガー到達 — 約定を記録してください`,
      ref_id: p.id,
    });
  }
  for (const p of expiringSoon) {
    actions.push({
      kind: 'expiring',
      message: `${p.ticker4} ${p.security_name ?? ''} の計画がまもなく期限切れ（${p.expires_on}）`,
      ref_id: p.id,
    });
  }
  for (const pos of openPositions) {
    if (pos.current_r != null && Number(pos.current_r) >= 1.0) {
      actions.push({
        kind: 'review_stop',
        message: `${pos.ticker4} ${pos.security_name ?? ''} が+1R到達 — 損切り引き上げを検討`,
        ref_id: pos.id,
      });
    }
  }

  return c.json({
    account: accountRow,
    actions,
    open_positions: openPositions,
    portfolio_heat: ctx.currentHeat,
    max_heat: account.max_heat,
    armed_watching: armedWatching,
    triggered_awaiting_entry: triggeredAwaitingEntry,
    regime: regimeRows[0] ?? null,
    new_candidates: drafts,
  });
});

// ---------------------------------------------------------------------
// Replay training: turns the Free plan's 84-day lag into practice reps.
// A live account trades ~250 times a year; at the per-trade R spread this
// screen already measures (stdev 1.2-1.9 in the theme system), detecting a
// real edge needs on the order of 1,800 trades — about 7 years. Replay
// pulls a past session's Setup candidates from setup_outcomes (built by
// pipeline_py/setups/replay.py) WITHOUT their outcome fields, lets the user
// decide blind, then reveals what actually happened. It does not turn a
// short replay history into statistical proof of anything — see PART 11's
// same caution against reading `theme_edge`-style numbers off a handful of
// sessions.

interface SetupOutcomeRow {
  as_of: string;
  setup_key: string;
  code: string;
  trigger_price: string;
  stop_planned: string;
  target_planned: string;
  entry_fill: string | null;
  exit_price: string | null;
  exit_date: string | null;
  bars_held: number | null;
  outcome: string;
  r_multiple: string | null;
  ticker4: string;
  security_name: string | null;
  setup_name: string;
  setup_hypothesis: string;
}

interface ReplayDecision {
  code: string;
  setup_key: string;
  decision: Decision;
  reason_code: string;
}

/** Your BUY calls vs adopting every candidate vs buying everything, over
 * the same revealed sessions. Three cohorts rather than two because a
 * two-way comparison can't separate "you picked well" from "the Setup
 * picked well" — if your_buy beats baseline but mechanical beats it by
 * just as much, the Setup earned that, not your selection. */
app.get('/replay/scorecard', async (c) => {
  const rows = await selectFrom<Record<string, unknown>>(c.env, 'replay_scorecard', {
    select: '*',
  });
  return c.json({ scorecard: rows });
});

app.post('/replay/start', async (c) => {
  // Pick from sessions that actually have judged outcomes, uniformly at
  // random client-side (PostgREST has no simple "random row" primitive
  // without a stored proc, and the candidate set is small enough this is
  // cheap).
  const allDates = await selectFrom<{ as_of: string }>(c.env, 'setup_outcomes', {
    select: 'as_of',
  });
  const distinctDates = [...new Set(allDates.map((d) => d.as_of))];
  if (distinctDates.length === 0) {
    return c.json({ error: 'no replay data yet — run pipeline_py.setups.replay first' }, 404);
  }
  const asOf = distinctDates[Math.floor(Math.random() * distinctDates.length)];

  const rows = await selectFrom<SetupOutcomeRow>(c.env, 'setup_outcomes_view', {
    select: 'as_of,setup_key,code,trigger_price,stop_planned,target_planned,ticker4,security_name,setup_name,setup_hypothesis',
    as_of: `eq.${asOf}`,
    order: 'setup_key.asc,code.asc',
  });

  const accountRow = await loadAccount(c.env);
  const created = await insertInto<{ id: number }>(c.env, 'replay_sessions', [
    { account_id: accountRow.id, as_of: asOf, revealed: false, decisions: [] },
  ]);

  // outcome fields deliberately stripped before returning — this is the
  // "blind" part of blind replay.
  const blind = rows.map(({ entry_fill, exit_price, exit_date, bars_held, outcome, r_multiple, ...rest }) => rest);

  return c.json({ session_id: created[0]!.id, as_of: asOf, candidates: blind });
});

app.post('/replay/:id/decide', async (c) => {
  const id = c.req.param('id');
  const body = await c.req.json<ReplayDecision>();
  if (!['BUY', 'WAIT', 'PASS'].includes(body.decision)) {
    return c.json({ error: 'decision must be BUY/WAIT/PASS' }, 400);
  }

  const rows = await selectFrom<{ id: number; decisions: ReplayDecision[]; revealed: boolean }>(
    c.env,
    'replay_sessions',
    { select: '*', id: `eq.${id}` }
  );
  const session = rows[0];
  if (!session) return c.json({ error: 'not found' }, 404);
  if (session.revealed) return c.json({ error: 'session already revealed' }, 409);

  const decisions = session.decisions.filter(
    (d) => !(d.code === body.code && d.setup_key === body.setup_key)
  );
  decisions.push(body);

  const updated = await updateWhere(c.env, 'replay_sessions', { id: `eq.${id}` }, { decisions });
  return c.json({ decisions: (updated[0] as { decisions: ReplayDecision[] } | undefined)?.decisions ?? decisions });
});

app.post('/replay/:id/reveal', async (c) => {
  const id = c.req.param('id');
  const rows = await selectFrom<{ id: number; as_of: string; decisions: ReplayDecision[] }>(
    c.env,
    'replay_sessions',
    { select: '*', id: `eq.${id}` }
  );
  const session = rows[0];
  if (!session) return c.json({ error: 'not found' }, 404);

  const outcomes = await selectFrom<SetupOutcomeRow>(c.env, 'setup_outcomes_view', {
    select: '*',
    as_of: `eq.${session.as_of}`,
  });
  const byKey = new Map(outcomes.map((o) => [`${o.code}/${o.setup_key}`, o]));

  const results = session.decisions.map((d) => ({
    ...d,
    outcome: byKey.get(`${d.code}/${d.setup_key}`) ?? null,
  }));

  await updateWhere(c.env, 'replay_sessions', { id: `eq.${id}` }, {
    revealed: true,
    revealed_at: new Date().toISOString(),
  });

  return c.json({ as_of: session.as_of, results });
});

function addTradingDays(start: string, n: number): string {
  const d = new Date(`${start}T00:00:00Z`);
  let remaining = n;
  while (remaining > 0) {
    d.setUTCDate(d.getUTCDate() + 1);
    const day = d.getUTCDay();
    if (day !== 0 && day !== 6) remaining -= 1;
  }
  return d.toISOString().slice(0, 10);
}

export default app;
