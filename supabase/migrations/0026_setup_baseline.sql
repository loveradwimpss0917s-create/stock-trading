-- Setup版の対照群。テーマ方式で screen_baseline を入れた結果、+0.28R が
-- 対照群 +0.077R を引くと実質ゼロだった——あの経緯をSetupでも繰り返さない
-- ための装置。これ無しに setup_outcomes_summary を画面に出すことはしない。

-- 0025のcheck制約は建った後の結末しか想定していなかったが、replayが
-- トリガー待ちを正しく行うようになり、建たずに終わる2つの状態が増えた。
alter table setup_outcomes drop constraint if exists setup_outcomes_outcome_check;
alter table setup_outcomes add constraint setup_outcomes_outcome_check
  check (outcome in ('target', 'stop', 'timeout', 'no_entry', 'expired', 'invalidated'));

create table if not exists setup_baseline (
  as_of      date not null,
  setup_key  text not null references setups(key) on delete cascade,
  n_trades   int not null,
  n_no_entry int not null default 0,
  -- 平均ではなく合計を持つのは、セッションごとに銘柄数が違うため。
  -- 平均の平均では2銘柄の日と200銘柄の日が同じ重みになる。
  sum_r      numeric(18,6) not null,
  n_wins     int not null,
  created_at timestamptz not null default now(),
  primary key (as_of, setup_key)
);

alter table setup_baseline enable row level security;
drop policy if exists setup_baseline_read on setup_baseline;
create policy setup_baseline_read on setup_baseline for select to anon, authenticated using (true);
grant select on setup_baseline to anon, authenticated;

create or replace view setup_baseline_summary
with (security_invoker = on) as
select
  setup_key,
  sum(n_trades)   as n_trades,
  sum(n_no_entry) as n_no_entry,
  round(sum(sum_r) / nullif(sum(n_trades), 0), 4)          as avg_r,
  round(sum(n_wins)::numeric / nullif(sum(n_trades), 0), 4) as win_rate
from setup_baseline
group by setup_key;

grant select on setup_baseline_summary to anon, authenticated;

-- 建たずに終わった計画（expired/invalidated/no_entry）はRの分母から外すが、
-- 件数は残す。「そもそもトリガーに到達しない頻度」はSetupを運用する
-- コストそのものであり、消すと生き残りだけが良く見える。
create or replace view setup_outcomes_summary
with (security_invoker = on) as
select
  setup_key,
  count(*)                                                     as n_plans,
  count(*) filter (where outcome not in ('expired','invalidated','no_entry')) as n_trades,
  count(*) filter (where outcome = 'expired')                  as n_expired,
  count(*) filter (where outcome = 'invalidated')              as n_invalidated,
  count(*) filter (where outcome = 'no_entry')                 as n_no_entry,
  round(avg(r_multiple) filter (where outcome not in ('expired','invalidated','no_entry')), 4) as avg_r,
  round(
    count(*) filter (where r_multiple > 0)::numeric
    / nullif(count(*) filter (where outcome not in ('expired','invalidated','no_entry')), 0), 4
  ) as win_rate,
  min(as_of) as first_as_of,
  max(as_of) as last_as_of
from setup_outcomes
group by setup_key;

grant select on setup_outcomes_summary to anon, authenticated;

-- t値は上限であって下限ではない。週次サンプリングに対し保有が重なるため
-- 実効サンプル数は件数より少なく、複数Setupを同時に見れば帰無仮説の下でも
-- |t|>2 が偶然出る。画面はこれを明記した上で表示する。
create or replace view setup_edge
with (security_invoker = on) as
with dispersion as (
  select setup_key,
         stddev_samp(r_multiple) as sd_r,
         count(*) as n
  from setup_outcomes
  where outcome not in ('expired','invalidated','no_entry')
  group by setup_key
)
select
  s.*,
  st.name_ja    as setup_name,
  st.horizon,
  st.hypothesis,
  b.avg_r       as baseline_avg_r,
  b.win_rate    as baseline_win_rate,
  b.n_trades    as baseline_n_trades,
  round(s.avg_r - b.avg_r, 4)                             as edge_r,
  round(s.win_rate - b.win_rate, 4)                       as edge_win_rate,
  round(d.sd_r::numeric, 4)                               as sd_r,
  round((d.sd_r / sqrt(nullif(d.n, 0)))::numeric, 4)      as se_r,
  round(((s.avg_r - b.avg_r) / nullif(d.sd_r / sqrt(nullif(d.n, 0)), 0))::numeric, 2) as t_stat
from setup_outcomes_summary s
join setups st on st.key = s.setup_key
left join setup_baseline_summary b on b.setup_key = s.setup_key
left join dispersion d on d.setup_key = s.setup_key;

grant select on setup_edge to anon, authenticated;
