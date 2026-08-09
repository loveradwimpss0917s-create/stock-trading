import { Hono } from 'hono';
import { cors } from 'hono/cors';

type Bindings = {
  ASSETS: Fetcher;
};

const app = new Hono<{ Bindings: Bindings }>();

app.use('/api/*', cors());

app.get('/api/health', (c) =>
  c.json({ status: 'ok', service: 'kabu-quant-api', time: new Date().toISOString() })
);

app.get('*', (c) => c.env.ASSETS.fetch(c.req.raw));

export default app;
