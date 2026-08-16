export interface Security {
  code: string;
  ticker4: string;
  name_ja: string | null;
  name_en: string | null;
  market_code: string | null;
  sector17: string | null;
  sector33: string | null;
  scale_category: string | null;
  /** False when the code exists in the master list but has no bars yet. */
  has_data?: boolean;
}

export interface DailyQuote {
  code: string;
  date: string;
  open: string | null;
  high: string | null;
  low: string | null;
  close: string | null;
  volume: number | null;
  turnover_value: number | null;
}

export interface SyncStatus {
  securities_count: number;
  daily_quotes_count: number;
  covered_codes: number;
  earliest_date: string | null;
  latest_date: string | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

async function send<T>(method: 'POST' | 'PATCH', path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) => send<T>('POST', path, body);
const patch = <T>(path: string, body?: unknown) => send<T>('PATCH', path, body);

export interface StrategyResult {
  run_id: number;
  strategy: string;
  period_start: string | null;
  period_end: string | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_dd: number | null;
  win_rate: number | null;
  n_trades: number | null;
  avg_holding_days: number | null;
  profit_factor: number | null;
  dsr: number | null;
  pbo: number | null;
  expected_max_sharpe: number | null;
  n_trials: number | null;
  skew: number | null;
  kurtosis: number | null;
  passed: boolean;
}

export interface Theme {
  key: string;
  name_ja: string;
  kind: 'sector' | 'factor';
  horizon: 'day' | 'swing' | 'both';
  description: string | null;
}

export interface Candidate {
  as_of: string;
  theme_key: string;
  theme_name: string;
  theme_kind: string;
  theme_description: string | null;
  horizon: string;
  side: string;
  rank: number;
  score: number;
  entry_ref: number;
  stop_price: number;
  target_price: number;
  atr_14: number;
  rr_ratio: number;
  rationale: { components?: Record<string, number>; atr_pct?: number } | null;
  code: string;
  ticker4: string;
  name_ja: string | null;
  sector33: string | null;
  scale_category: string | null;
  theme_sort_order: number | null;
}

export interface ThemePerformance {
  theme_key: string;
  theme_name: string;
  theme_kind: string;
  horizon: string;
  n_trades: number;
  n_no_entry: number;
  n_target: number;
  n_stop: number;
  n_timeout: number;
  avg_r: number | null;
  win_rate: number | null;
  first_as_of: string | null;
  last_as_of: string | null;
  /** The same measurement over every eligible name — what picking must beat. */
  baseline_avg_r: number | null;
  baseline_win_rate: number | null;
  edge_r: number | null;
  edge_win_rate: number | null;
  sd_r: number | null;
  se_r: number | null;
  /** edge_r in standard errors. An upper bound — see the panel's footnote. */
  t_stat: number | null;
}

export interface Baseline {
  horizon: string;
  n_trades: number;
  avg_r: number | null;
  win_rate: number | null;
}

export const fetchThemePerformance = () =>
  get<{ performance: ThemePerformance[]; baseline: Baseline[] }>('/api/theme-performance');

export interface Outcome {
  as_of: string;
  theme_key: string;
  theme_name: string;
  horizon: string;
  rank: number;
  code: string;
  ticker4: string;
  name_ja: string | null;
  entry_fill: number | null;
  stop_price: number | null;
  target_price: number | null;
  exit_price: number | null;
  exit_date: string | null;
  bars_held: number | null;
  outcome: 'target' | 'stop' | 'timeout' | 'no_entry';
  r_multiple: number | null;
  pnl_per_share: number | null;
}

export interface OutcomeTotals {
  horizon: string;
  n_trades: number;
  n_no_entry: number;
  n_wins: number;
  total_r: number | null;
  avg_r: number | null;
  avg_bars_held: number | null;
  first_as_of: string | null;
  last_as_of: string | null;
}

export const fetchOutcomes = (params: {
  horizon?: string;
  theme?: string;
  as_of?: string;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, String(v));
  const s = qs.toString();
  return get<{ outcomes: Outcome[]; totals: OutcomeTotals[] }>(
    s ? `/api/outcomes?${s}` : '/api/outcomes'
  );
};

export const fetchThemes = () => get<{ themes: Theme[] }>('/api/themes');

export const fetchCandidates = (theme?: string, horizon?: string) => {
  const params = new URLSearchParams();
  if (theme) params.set('theme', theme);
  if (horizon) params.set('horizon', horizon);
  const qs = params.toString();
  return get<{ as_of: string | null; days_behind: number | null; candidates: Candidate[] }>(
    qs ? `/api/candidates?${qs}` : '/api/candidates'
  );
};

export interface Freshness {
  latest_date: string | null;
  days_behind: number | null;
}

export const fetchStrategies = () =>
  get<{ strategies: StrategyResult[]; passed_count: number; gate: Record<string, string> }>(
    '/api/strategies'
  );
export const fetchFreshness = () => get<Freshness>('/api/freshness');

export const fetchSyncStatus = () => get<SyncStatus>('/api/sync/status');
export const fetchStocks = (q?: string) =>
  get<{ stocks: Security[] }>(q ? `/api/stocks?q=${encodeURIComponent(q)}` : '/api/stocks');
export const fetchStock = (code: string) =>
  get<{ security: Security; quotes: DailyQuote[] }>(`/api/stocks/${code}`);

// ---------------------------------------------------------------------
// Decision OS
export interface Setup {
  key: string;
  name_ja: string;
  horizon: 'day' | 'swing';
  hypothesis: string;
  time_stop_bars: number;
  expiry_bars: number;
  min_rr: number;
}

export interface RegimeSnapshot {
  date: string;
  pct_above_ma25: number;
  pct_above_ma75: number;
  adv_decline_ratio: number;
  new_high_minus_low: number;
  dispersion: number;
  regime_label: 'offense' | 'neutral' | 'defense';
  computed_from_n: number;
}

export type PlanState =
  | 'draft'
  | 'armed'
  | 'triggered'
  | 'open'
  | 'closed'
  | 'expired'
  | 'invalidated'
  | 'passed'
  | 'discarded';

export interface TradePlan {
  id: number;
  account_id: number;
  code: string;
  setup_key: string;
  setup_name: string;
  setup_horizon: 'day' | 'swing';
  setup_hypothesis: string;
  ticker4: string;
  security_name: string | null;
  sector33: string | null;
  state: PlanState;
  created_on: string;
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
  scenarios: { bull?: string; base?: string; bear?: string } | null;
  current_price: string | null;
  triggered_on: string | null;
  triggered_price: string | null;
}

export interface GateResult {
  passed: boolean;
  value: number | null;
  threshold?: number;
}

export interface RiskVerdict {
  decision: 'BUY' | 'WAIT' | 'PASS';
  reasonCode: string;
  shares: number;
  riskAmount: number;
  riskPct: number;
  notional: number;
  rr: number;
  gates: Record<string, GateResult>;
}

export interface Position {
  id: number;
  plan_id: number;
  account_id: number;
  code: string;
  ticker4: string;
  security_name: string | null;
  sector33: string | null;
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
  current_price: string | null;
  current_risk: string | null;
  current_r: string | null;
}

export interface HomeAction {
  kind: string;
  message: string;
  ref_id: number;
}

export interface HomeResponse {
  account: { id: number; capital: string; max_heat: string };
  actions: HomeAction[];
  open_positions: Position[];
  portfolio_heat: number;
  max_heat: number;
  armed_watching: TradePlan[];
  triggered_awaiting_entry: TradePlan[];
  regime: RegimeSnapshot | null;
  new_candidates: TradePlan[];
}

export const fetchHome = () => get<HomeResponse>('/api/home');
export const fetchSetups = () => get<{ setups: Setup[] }>('/api/setups');
export const fetchRegime = () => get<RegimeSnapshot | null>('/api/regime');
export const fetchPlans = (state?: string) =>
  get<{ plans: TradePlan[] }>(state ? `/api/plans?state=${state}` : '/api/plans');
export const fetchPlan = (id: number) => get<TradePlan>(`/api/plans/${id}`);
export const fetchPlanRisk = (id: number) => get<RiskVerdict>(`/api/plans/${id}/risk`);
export const updatePlan = (
  id: number,
  body: { thesis?: string; anti_thesis?: string; scenarios?: unknown }
) => patch<TradePlan>(`/api/plans/${id}`, body);
export const decidePlan = (
  id: number,
  body: { decision: 'BUY' | 'WAIT' | 'PASS'; reason_code: string; reason_note?: string }
) => post<{ plan: TradePlan; verdict: RiskVerdict }>(`/api/plans/${id}/decide`, body);

export const fetchPositions = (status?: string) =>
  get<{ positions: Position[] }>(status ? `/api/positions?status=${status}` : '/api/positions');
export const createPosition = (body: {
  plan_id: number;
  opened_on: string;
  entry_price: number;
  shares: number;
}) => post<{ position: Position }>('/api/positions', body);
export const addPositionEvent = (
  id: number,
  body: {
    occurred_on: string;
    event_type: string;
    price?: number;
    note?: string;
    thesis_status?: string;
    new_stop?: number;
    new_target?: number;
  }
) => post(`/api/positions/${id}/events`, body);
export const closePosition = (
  id: number,
  body: {
    closed_on: string;
    exit_price: number;
    exit_reason: string;
    thesis_was_correct: boolean;
    execution_adherence: string;
    review_note?: string;
  }
) => post(`/api/positions/${id}/close`, body);

export const fetchJournal = () => get<{ journal: (Position & { journal: unknown })[] }>('/api/journal');

// ---------------------------------------------------------------------
// Replay training
export interface ReplayCandidate {
  as_of: string;
  setup_key: string;
  code: string;
  trigger_price: string;
  stop_planned: string;
  target_planned: string;
  ticker4: string;
  security_name: string | null;
  setup_name: string;
  setup_hypothesis: string;
}

export interface ReplayOutcome {
  entry_fill: string | null;
  exit_price: string | null;
  outcome: 'target' | 'stop' | 'timeout' | 'no_entry';
  r_multiple: string | null;
  bars_held: number | null;
}

export interface ReplayResult {
  code: string;
  setup_key: string;
  decision: 'BUY' | 'WAIT' | 'PASS';
  reason_code: string;
  outcome: (ReplayOutcome & ReplayCandidate) | null;
}

export const startReplay = () =>
  post<{ session_id: number; as_of: string; candidates: ReplayCandidate[] }>('/api/replay/start');

export const decideReplay = (
  sessionId: number,
  body: { code: string; setup_key: string; decision: 'BUY' | 'WAIT' | 'PASS'; reason_code: string }
) => post<{ decisions: unknown[] }>(`/api/replay/${sessionId}/decide`, body);

export const revealReplay = (sessionId: number) =>
  post<{ as_of: string; results: ReplayResult[] }>(`/api/replay/${sessionId}/reveal`);
