-- 価格・特徴量・スコアは全ユーザー read-only（書込はservice_roleのみ）
alter table daily_quotes enable row level security;
alter table features enable row level security;
alter table scores enable row level security;

create policy "public_read_quotes"   on daily_quotes for select using (true);
create policy "public_read_features" on features     for select using (true);
create policy "public_read_scores"   on scores       for select using (true);
-- INSERT/UPDATE ポリシーを作らない＝anon/authenticatedは書込不可。
-- service_role キーはRLSをbypassするのでGitHub Actionsのバッチはそのまま書込可。

-- PostgREST(Data API)経由での読取に必須の明示的GRANT。
-- 2026-05-30以降作成の新規Supabaseプロジェクトはこのステートメントがないと
-- anon/authenticatedからのSELECTが404/権限エラーになる(既存Freeプロジェクトも2026-10-30から影響)。
grant select on daily_quotes, features, scores to anon, authenticated;

-- ユーザーポートフォリオは auth.uid() で分離
create table if not exists user_portfolios (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid(),
  name text,
  holdings jsonb,
  created_at timestamptz default now()
);
alter table user_portfolios enable row level security;
create policy "own_portfolio_select" on user_portfolios
  for select using (auth.uid() = user_id);
create policy "own_portfolio_modify" on user_portfolios
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

grant select, insert, update, delete on user_portfolios to authenticated;
grant usage, select on sequence user_portfolios_id_seq to authenticated;
