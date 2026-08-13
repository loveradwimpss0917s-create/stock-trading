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

/** Securities that actually have price data ingested. */
app.get('/api/stocks', async (c) => {
  const search = c.req.query('q');

  // securities_with_data (migration 0007) does the "has bars?" join in the
  // DB. Deriving it here from daily_quotes rows instead would silently
  // truncate at PostgREST's max_rows.
  const securities = await selectFrom<Security>(c.env, 'securities_with_data', {
    select: 'code,ticker4,name_ja,name_en,market_code,sector17,sector33,scale_category',
    order: 'code.asc',
  });

  const filtered = search
    ? securities.filter(
        (s) =>
          s.code.includes(search) ||
          (s.name_ja ?? '').includes(search) ||
          (s.name_en ?? '').toLowerCase().includes(search.toLowerCase())
      )
    : securities;

  return c.json({ stocks: filtered });
});

/** One security's profile plus its recent daily bars. */
app.get('/api/stocks/:code', async (c) => {
  const code = c.req.param('code');
  const limit = Math.min(Number(c.req.query('limit') ?? 120), 1000);

  const [securities, quotes] = await Promise.all([
    selectFrom<Security>(c.env, 'securities', {
      select: 'code,ticker4,name_ja,name_en,market_code,sector17,sector33,scale_category',
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

app.get('*', (c) => c.env.ASSETS.fetch(c.req.raw));

export default app;
