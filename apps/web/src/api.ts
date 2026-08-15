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
