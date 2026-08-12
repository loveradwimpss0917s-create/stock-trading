-- 0005で漏れていた公開テーブルへのRLS適用（設計書K章「全公開テーブルでRLS必須」の徹底）
-- Supabaseセキュリティアドバイザーの指摘を受けて追加。

-- WorkerのAPIが読む必要がある派生データ系テーブル：RLS有効化＋公開read-only
alter table securities enable row level security;
alter table strategies enable row level security;
alter table backtest_runs enable row level security;
alter table backtest_metrics enable row level security;
alter table stats_validation enable row level security;
alter table model_generations enable row level security;

create policy "public_read_securities" on securities for select using (true);
create policy "public_read_strategies" on strategies for select using (true);
create policy "public_read_backtest_runs" on backtest_runs for select using (true);
create policy "public_read_backtest_metrics" on backtest_metrics for select using (true);
create policy "public_read_stats_validation" on stats_validation for select using (true);
create policy "public_read_model_generations" on model_generations for select using (true);

grant select on securities, strategies, backtest_runs, backtest_metrics, stats_validation, model_generations
  to anon, authenticated;

-- 生データ系テーブル：RLS有効化するがポリシーは作らない＝service_roleのみアクセス可
-- (J-Quants生データの再配布禁止規約に準拠。派生値のみpublicに出す)
alter table financials enable row level security;
alter table margin_short enable row level security;
alter table disclosure_events enable row level security;

-- daily_quotesの月次パーティションは個別テーブルとしてPostgRESTに公開されうるため
-- 親テーブルのRLSを継承しない。親と同じ公開read-onlyポリシーを明示的に付与する。
do $$
declare
  part record;
begin
  for part in
    select relname
    from pg_class
    where relname like 'daily_quotes_2%'
      and relkind = 'r'
  loop
    execute format('alter table %I enable row level security;', part.relname);
    execute format(
      'create policy "public_read_quotes" on %I for select using (true);',
      part.relname
    );
    execute format('grant select on %I to anon, authenticated;', part.relname);
  end loop;
end $$;

-- function_search_path_mutable(WARN)の修正
alter function ensure_month_partition(date) set search_path = public;
