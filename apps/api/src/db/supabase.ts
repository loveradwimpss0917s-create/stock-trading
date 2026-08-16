/** Thin PostgREST client.
 *
 * Uses the anon key only. Most of the schema is read-only research data
 * protected by public-read RLS (migrations 0005/0006) — the service_role
 * key that could write there or see the service_role-only raw tables
 * (financials / margin_short / disclosure_events) never reaches the Worker.
 *
 * The decision-OS tables (accounts, trade_plans, plan_decisions,
 * positions, position_events, trade_journal, replay_sessions —
 * migration 0020) are the one place this Worker writes, via the same anon
 * key: their RLS policies are deliberately `using (true) with check (true)`
 * for anon+authenticated, documented in 0020's header. There is no login
 * yet, so this is already the full extent of write access anyone with the
 * app's URL has — using service_role instead would additionally expose
 * every read-only research table's write path too, which is strictly
 * worse. See migration 0020 for the tradeoff this accepts.
 */
export interface SupabaseEnv {
  SUPABASE_URL: string;
  SUPABASE_ANON_KEY: string;
}

function headers(env: SupabaseEnv, extra: Record<string, string> = {}): Record<string, string> {
  return {
    apikey: env.SUPABASE_ANON_KEY,
    Authorization: `Bearer ${env.SUPABASE_ANON_KEY}`,
    Accept: 'application/json',
    ...extra,
  };
}

async function checkOk(res: Response): Promise<void> {
  if (!res.ok) {
    throw new Error(`Supabase ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
}

export async function selectFrom<T>(
  env: SupabaseEnv,
  table: string,
  query: Record<string, string>
): Promise<T[]> {
  const url = new URL(`${env.SUPABASE_URL.replace(/\/$/, '')}/rest/v1/${table}`);
  for (const [key, value] of Object.entries(query)) {
    url.searchParams.set(key, value);
  }

  const res = await fetch(url.toString(), { headers: headers(env) });
  await checkOk(res);
  return (await res.json()) as T[];
}

/** Insert and return the created row(s) — used when the caller needs the
 * generated identity id (e.g. a new trade_plans row) rather than just
 * confirming the write happened. */
export async function insertInto<T>(
  env: SupabaseEnv,
  table: string,
  rows: Record<string, unknown>[]
): Promise<T[]> {
  const url = `${env.SUPABASE_URL.replace(/\/$/, '')}/rest/v1/${table}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: headers(env, { 'Content-Type': 'application/json', Prefer: 'return=representation' }),
    body: JSON.stringify(rows),
  });
  await checkOk(res);
  return (await res.json()) as T[];
}

/** Partial update by filter. Deliberately separate from an upsert helper:
 * PostgREST's upsert (INSERT ... ON CONFLICT) still validates NOT NULL
 * columns omitted from the payload before it reaches the conflict check,
 * so a partial patch like {"state": "open"} would fail there even though
 * the row already exists and only one column needs to change. */
export async function updateWhere<T>(
  env: SupabaseEnv,
  table: string,
  filter: Record<string, string>,
  patch: Record<string, unknown>
): Promise<T[]> {
  const url = new URL(`${env.SUPABASE_URL.replace(/\/$/, '')}/rest/v1/${table}`);
  for (const [key, value] of Object.entries(filter)) {
    url.searchParams.set(key, value);
  }
  const res = await fetch(url.toString(), {
    method: 'PATCH',
    headers: headers(env, { 'Content-Type': 'application/json', Prefer: 'return=representation' }),
    body: JSON.stringify(patch),
  });
  await checkOk(res);
  return (await res.json()) as T[];
}
