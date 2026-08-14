import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { selectFrom, type SupabaseEnv } from './db/supabase';

type Bindings = SupabaseEnv & {
  ASSETS: Fetcher;
};

interface Security {
  code: string;
  ticker4: string;
  name_ja: string | null;
  name_en: string | null;
  market_code: string | null;
  sector17: string | null;
  sector33: string | null;
  scale_category: string | null;
  /** Whether daily bars have been backfilled for this code yet. */
  has_data?: boolean;
}

interface DailyQuote {
  code: string;
  date: string;
  open: string | null;
  high: string | null;
  low: string | null;
  close: string | null;
  volume: number | null;
  turnover_value: number | null;
}

const app = new Hono<{ Bindings: Bindings }>();

app.use('/api/*', cors());

app.onError((err, c) => {
  console.error(err);
  return c.json({ error: err.message, code: 'internal_error' }, 500);
});

app.get('/api/health', (c) =>
  c.json({ status: 'ok', service: 'kabu-quant-api', time: new Date().toISOString() })
);

const SECURITY_COLUMNS =
  'code,ticker4,name_ja,name_en,market_code,sector17,sector33,scale_category';

/** PostgREST treats , . : ( ) as syntax inside an or=(...) filter, so a query
 * containing them would corrupt the expression. Strip them rather than trying
 * to escape — none of them are meaningful in a ticker or a company name. */
function sanitizeSearch(raw: string): string {
  return raw.replace(/[,.:()*\\]/g, '').trim();
}

/**
 * Without `q`: the securities that actually have bars (the browsable list).
 * With `q`: searches all 4,446 master rows, so a code that hasn't been
 * backfilled yet is still findable — each result carries `has_data` so the
 * UI can say so rather than showing an empty chart.
 */
app.get('/api/stocks', async (c) => {
  const raw = c.req.query('q')?.trim();

  if (!raw) {
    const securities = await selectFrom<Security>(c.env, 'securities_with_data', {
      select: SECURITY_COLUMNS,
      order: 'code.asc',
    });
    return c.json({ stocks: securities.map((s) => ({ ...s, has_data: true })) });
  }

  const q = sanitizeSearch(raw);
  if (!q) return c.json({ stocks: [] });

  // Matched in Postgres, not by filtering a fetched page — the master table
  // is far past PostgREST's max_rows, so client-side filtering would only
  // ever search the first 1000 codes.
  const stocks = await selectFrom<Security>(c.env, 'securities_searchable', {
    select: `${SECURITY_COLUMNS},has_data`,
    or: `(code.ilike.*${q}*,name_ja.ilike.*${q}*,name_en.ilike.*${q}*)`,
    // Codes with data first, then by code, so the useful hits lead.
    order: 'has_data.desc,code.asc',
    limit: '100',
  });

  return c.json({ stocks });
});

/** One security's profile plus its recent daily bars. */
app.get('/api/stocks/:code', async (c) => {
  const code = c.req.param('code');
  const limit = Math.min(Number(c.req.query('limit') ?? 120), 1000);

  const [securities, quotes] = await Promise.all([
    selectFrom<Security>(c.env, 'securities', {
      select: SECURITY_COLUMNS,
      code: `eq.${code}`,
      limit: '1',
    }),
    selectFrom<DailyQuote>(c.env, 'daily_quotes', {
      select: 'code,date,open,high,low,close,volume,turnover_value',
      code: `eq.${code}`,
      order: 'date.desc',
      limit: String(limit),
    }),
  ]);

  if (securities.length === 0) {
    return c.json({ error: 'not found', code: 'not_found' }, 404);
  }

  return c.json({
    security: securities[0],
    // Ascending is what charts and indicator functions expect.
    quotes: quotes.slice().reverse(),
  });
});

/** Ingestion coverage, for the dashboard's status panel.
 *
 * Aggregated by the ingest_coverage view (migration 0007) rather than by
 * counting fetched rows: PostgREST caps responses at max_rows (1000), so
 * counting client-side reported exactly 1000/1000 and a truncated date
 * range once the table grew past that.
 */
app.get('/api/sync/status', async (c) => {
  const rows = await selectFrom<{
    securities_count: number;
    daily_quotes_count: number;
    covered_codes: number;
    earliest_date: string | null;
    latest_date: string | null;
  }>(c.env, 'ingest_coverage', { select: '*' });

  return c.json(
    rows[0] ?? {
      securities_count: 0,
      daily_quotes_count: 0,
      covered_codes: 0,
      earliest_date: null,
      latest_date: null,
    }
  );
});

/** Backtested strategies with their statistical verdict. */
app.get('/api/strategies', async (c) => {
  const rows = await selectFrom<Record<string, unknown>>(c.env, 'strategy_results', {
    select: '*',
    order: 'dsr.desc.nullslast',
  });
  return c.json({
    strategies: rows,
    // Surfaced so the UI can state the gate outcome rather than leaving the
    // reader to infer it from four rows of numbers.
    passed_count: rows.filter((r) => r.passed === true).length,
    gate: { dsr: '> 0.95', pbo: '< 0.5', oos_sharpe: '> 0' },
  });
});

/** How stale the data is — the reason this is a research tool, not a
 * trading one. Computed rather than hardcoded so it stays true. */
app.get('/api/freshness', async (c) => {
  const rows = await selectFrom<{ latest_date: string | null; days_behind: number | null }>(
    c.env,
    'data_freshness',
    { select: '*' }
  );
  return c.json(rows[0] ?? { latest_date: null, days_behind: null });
});

app.get('*', (c) => c.env.ASSETS.fetch(c.req.raw));

export default app;
