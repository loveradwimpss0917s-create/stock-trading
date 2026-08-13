-- バックフィルの進捗。J-Quants Freeの4req/min下では全銘柄取得が
-- GitHub Actionsの6時間上限に収まらないため、複数回の実行に分割する。
-- どこまで終わったかをDBに持たせ、次の実行が続きから再開できるようにする。
create table if not exists ingest_checkpoint (
  code              text primary key references securities(code),
  last_backfilled_at timestamptz,
  quotes_ingested   int,
  last_error        text,
  updated_at        timestamptz not null default now()
);

create index if not exists ingest_checkpoint_backfilled_idx
  on ingest_checkpoint (last_backfilled_at);

-- 運用データであり公開する必要がないため、RLS有効・ポリシーなし
-- （＝service_roleのバッチのみ読み書き可能）
alter table ingest_checkpoint enable row level security;
