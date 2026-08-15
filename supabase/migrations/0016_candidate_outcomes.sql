-- 「その候補は正しかったのか」に答えるための結果テーブル。
-- 候補は as_of 時点の情報だけで作られるので、翌営業日以降のバーで
-- 損切り／目標／期限切れを判定すれば、先読みなしで検証できる。
create table if not exists candidate_outcomes (
  as_of        date not null,
  theme_key    text not null references themes(key) on delete cascade,
  code         text not null,
  horizon      text not null check (horizon in ('day','swing')),
  rank         int  not null,

  -- 約定は翌営業日の寄り。基準日の終値ではない（窓開けの影響を含める）。
  entry_fill   numeric(18,4),
  stop_price   numeric(18,4),
  target_price numeric(18,4),

  exit_price   numeric(18,4),
  exit_date    date,
  bars_held    int,

  -- no_entry: 翌寄りが既に損切り水準を割っていて建てられない状態。
  -- 勝率の分母から外すが、頻度自体が screen の質なので記録は残す。
  outcome      text not null check (outcome in ('target','stop','timeout','no_entry')),
  -- 損切りまでの距離を1Rとした損益。約定値と実際に置く損切り水準から計算する。
  r_multiple   numeric(10,4),

  created_at   timestamptz not null default now(),
  primary key (as_of, theme_key, code, horizon)
);

create index if not exists candidate_outcomes_theme_idx
  on candidate_outcomes (theme_key, horizon);

alter table candidate_outcomes enable row level security;

drop policy if exists candidate_outcomes_read on candidate_outcomes;
create policy candidate_outcomes_read on candidate_outcomes for select to anon, authenticated using (true);

grant select on candidate_outcomes to anon, authenticated;

-- テーマ別の成績。no_entry は勝率の分母から外し、別途件数だけ出す。
create or replace view theme_performance
with (security_invoker = on) as
select
  o.theme_key,
  t.name_ja  as theme_name,
  t.kind     as theme_kind,
  t.sort_order as theme_sort_order,
  o.horizon,
  count(*) filter (where o.outcome <> 'no_entry')                      as n_trades,
  count(*) filter (where o.outcome = 'no_entry')                       as n_no_entry,
  count(*) filter (where o.outcome = 'target')                         as n_target,
  count(*) filter (where o.outcome = 'stop')                           as n_stop,
  count(*) filter (where o.outcome = 'timeout')                        as n_timeout,
  round(avg(o.r_multiple) filter (where o.outcome <> 'no_entry'), 4)   as avg_r,
  round(
    count(*) filter (where o.r_multiple > 0)::numeric
    / nullif(count(*) filter (where o.outcome <> 'no_entry'), 0), 4
  )                                                                     as win_rate,
  min(o.as_of) as first_as_of,
  max(o.as_of) as last_as_of
from candidate_outcomes o
join themes t on t.key = o.theme_key
group by o.theme_key, t.name_ja, t.kind, t.sort_order, o.horizon;

grant select on theme_performance to anon, authenticated;
