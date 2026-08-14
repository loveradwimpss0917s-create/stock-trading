-- テーマ（業種テーマ＋ファクターテーマ）
create table if not exists themes (
  key         text primary key,
  name_ja     text not null,
  kind        text not null,          -- 'sector' | 'factor'
  horizon     text not null,          -- 'day' | 'swing' | 'both'
  description text,
  definition  jsonb not null,         -- sector33コード配列 or ファクター重み
  enabled     boolean not null default true,
  sort_order  int not null default 100
);

-- 日次の売買候補。as_of は「シグナル算出の基準営業日」であって
-- 「実行日」ではない。Freeプランでは as_of が約12週間前になるため、
-- UIは必ずこの日付を出して「今日の推奨」と誤認させないこと。
create table if not exists trade_candidates (
  as_of        date not null,
  theme_key    text not null references themes(key),
  code         text not null references securities(code),
  horizon      text not null,         -- 'day' | 'swing'
  side         text not null,         -- 'long' | 'short'
  rank         int  not null,
  score        numeric,
  entry_ref    numeric,               -- 基準終値（実際の約定は翌寄付想定）
  stop_price   numeric,
  target_price numeric,
  atr_14       numeric,
  rr_ratio     numeric,               -- 目標/損切りのリスクリワード
  rationale    jsonb,                 -- スコアの内訳。なぜ選ばれたかを説明できるように
  created_at   timestamptz not null default now(),
  primary key (as_of, theme_key, code, horizon)
);

create index if not exists trade_candidates_asof_idx
  on trade_candidates (as_of desc, theme_key, rank);

alter table themes enable row level security;
alter table trade_candidates enable row level security;

create policy "public_read_themes" on themes for select using (true);
create policy "public_read_candidates" on trade_candidates for select using (true);

grant select on themes, trade_candidates to anon, authenticated;
