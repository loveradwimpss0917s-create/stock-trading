export interface Security {
  code: string;
  ticker4: string;
  name_ja: string | null;
  name_en: string | null;
  market_code: string | null;
  sector17: string | null;
  sector33: string | null;
  scale_category: string | null;
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

export const fetchSyncStatus = () => get<SyncStatus>('/api/sync/status');
export const fetchStocks = () => get<{ stocks: Security[] }>('/api/stocks');
export const fetchStock = (code: string) =>
  get<{ security: Security; quotes: DailyQuote[] }>(`/api/stocks/${code}`);
