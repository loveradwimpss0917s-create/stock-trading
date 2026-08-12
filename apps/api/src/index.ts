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

/** Securities that actually have price data ingested, with their coverage. */
app.get('/api/stocks', async (c) => {
  const search = c.req.query('q');

  // daily_quotes only holds the codes backfilled so far, so drive the list
  // from it rather than from all 4,446 master rows — otherwise the UI is
  // mostly entries with nothing to show.
  const quotes = await selectFrom<{ code: string }>(c.env, 'daily_quotes', {
    select: 'code',
    limit: '10000',
  });
  const codes = [...new Set(quotes.map((q) => q.code))];
  if (codes.length === 0) return c.json({ stocks: [] });

  const securities = await selectFrom<Security>(c.env, 'securities', {
    select: 'code,ticker4,name_ja,name_en,market_code,sector17,sector33,scale_category',
    code: `in.(${codes.join(',')})`,
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

/** Ingestion coverage, for the dashboard's status panel. */
app.get('/api/sync/status', async (c) => {
  const [securities, quotes] = await Promise.all([
    selectFrom<{ code: string }>(c.env, 'securities', { select: 'code', limit: '10000' }),
    selectFrom<{ code: string; date: string }>(c.env, 'daily_quotes', {
      select: 'code,date',
      limit: '100000',
    }),
  ]);

  const dates = quotes.map((q) => q.date).sort();
  return c.json({
    securities_count: securities.length,
    daily_quotes_count: quotes.length,
    covered_codes: new Set(quotes.map((q) => q.code)).size,
    earliest_date: dates[0] ?? null,
    latest_date: dates[dates.length - 1] ?? null,
  });
});

app.get('*', (c) => c.env.ASSETS.fetch(c.req.raw));

export default app;
