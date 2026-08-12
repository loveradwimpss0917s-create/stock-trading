/** Thin PostgREST read client.
 *
 * Uses the anon key only — every table this reaches is protected by the
 * public-read RLS policies from migrations 0005/0006, so the Worker can
 * never write and can never see the service_role-only raw tables
 * (financials / margin_short / disclosure_events).
 */
export interface SupabaseEnv {
  SUPABASE_URL: string;
  SUPABASE_ANON_KEY: string;
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

  const res = await fetch(url.toString(), {
    headers: {
      apikey: env.SUPABASE_ANON_KEY,
      Authorization: `Bearer ${env.SUPABASE_ANON_KEY}`,
      Accept: 'application/json',
    },
  });

  if (!res.ok) {
    throw new Error(`Supabase ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  return (await res.json()) as T[];
}
