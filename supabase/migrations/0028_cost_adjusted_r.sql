-- コスト後R。ここまで検証系は執行コストを完全に無視しており、
-- どのSetupも「取れない総R」を成績として表示していた。
--
-- 実データで測ったところ往復コストは0.10〜0.18R。対して観測された
-- 選別効果は最大でも0.05R程度なので、コストは効果より一桁大きい。
-- これを入れずに出していた数字は、順位も符号も信用できない。
--
-- 損切り幅とコストの関係が本質的：スリッページ単価は price * (0.10*ATR/price)
-- = 0.10*ATR となり価格に依存しないため、往復コストは
--   cost_r = 2 * 0.10 / stop_multiple
-- に収束する。損切り1.0×ATRなら0.20R、1.8×ATRなら0.11R。
-- 「損切りを狭くするとR単位のコストが膨らむ」は構造的な帰結であって
-- 個別銘柄の事情ではない。
alter table setup_outcomes add column if not exists cost_r numeric(10,4);
alter table setup_baseline add column if not exists sum_cost_r numeric(18,6) not null default 0;

comment on column setup_outcomes.cost_r is
  '往復執行コストをRで表したもの。建たなかった計画はnull（コストも発生しない）';

-- 列の並びが変わるため create or replace は使えない（Postgresは既存列の
-- 改名を拒否する）。依存するビューごと落として作り直す。
drop view if exists replay_scorecard;
drop view if exists setup_edge;
drop view if exists setup_outcomes_summary;
drop view if exists setup_baseline_summary;

create view setup_outcomes_summary
with (security_invoker = on) as
select
  setup_key,
  count(*)                                                     as n_plans,
  count(*) filter (where outcome not in ('expired','invalidated','no_entry')) as n_trades,
  count(*) filter (where outcome = 'expired')                  as n_expired,
  count(*) filter (where outcome = 'invalidated')              as n_invalidated,
  count(*) filter (where outcome = 'no_entry')                 as n_no_entry,
  round(avg(r_multiple) filter (where outcome not in ('expired','invalidated','no_entry')), 4) as gross_avg_r,
  round(avg(cost_r)     filter (where cost_r is not null), 4)  as avg_cost_r,
  round(avg(r_multiple - coalesce(cost_r, 0))
        filter (where outcome not in ('expired','invalidated','no_entry')), 4) as avg_r,
  round(
    count(*) filter (where r_multiple - coalesce(cost_r, 0) > 0)::numeric
    / nullif(count(*) filter (where outcome not in ('expired','invalidated','no_entry')), 0), 4
  ) as win_rate,
  min(as_of) as first_as_of,
  max(as_of) as last_as_of
from setup_outcomes
group by setup_key;

grant select on setup_outcomes_summary to anon, authenticated;

create view setup_baseline_summary
with (security_invoker = on) as
select
  setup_key,
  sum(n_trades)   as n_trades,
  sum(n_no_entry) as n_no_entry,
  round(sum(sum_r) / nullif(sum(n_trades), 0), 4)                        as gross_avg_r,
  round(sum(sum_cost_r) / nullif(sum(n_trades), 0), 4)                   as avg_cost_r,
  round((sum(sum_r) - sum(sum_cost_r)) / nullif(sum(n_trades), 0), 4)    as avg_r,
  round(sum(n_wins)::numeric / nullif(sum(n_trades), 0), 4)              as win_rate
from setup_baseline
group by setup_key;

grant select on setup_baseline_summary to anon, authenticated;

-- edge_r は純R同士の差。コストはSetup側にも対照群側にも同じ前提で
-- 課しているため、片方だけが不利になることはない。
create view setup_edge
with (security_invoker = on) as
with dispersion as (
  select setup_key,
         stddev_samp(r_multiple - coalesce(cost_r, 0)) as sd_r,
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
  (st.stop_rule->>'mult')::numeric as stop_atr_mult,
  b.avg_r       as baseline_avg_r,
  b.gross_avg_r as baseline_gross_avg_r,
  b.avg_cost_r  as baseline_avg_cost_r,
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

-- リプレイ成績も純R基準に揃える。
create view replay_scorecard
with (security_invoker = on) as
with revealed_sessions as (
  select distinct as_of from replay_sessions where revealed = true
),
decided as (
  select rs.as_of, d->>'code' as code, d->>'setup_key' as setup_key, d->>'decision' as decision
  from replay_sessions rs, lateral jsonb_array_elements(rs.decisions) d
  where rs.revealed = true
),
traded as (
  select o.as_of, o.code, o.setup_key, (o.r_multiple - coalesce(o.cost_r, 0)) as net_r
  from setup_outcomes o
  join revealed_sessions r on r.as_of = o.as_of
  where o.outcome not in ('expired', 'invalidated', 'no_entry')
),
your_buy as (
  select t.net_r from traded t
  join decided d on d.as_of = t.as_of and d.code = t.code and d.setup_key = t.setup_key
  where d.decision = 'BUY'
),
mechanical as (select net_r from traded),
base as (
  select b.sum_r, b.sum_cost_r, b.n_trades, b.n_wins
  from setup_baseline b join revealed_sessions r on r.as_of = b.as_of
)
select 'your_buy' as cohort, count(*) as n_trades, round(avg(net_r), 4) as avg_r,
       round(count(*) filter (where net_r > 0)::numeric / nullif(count(*), 0), 4) as win_rate
from your_buy
union all
select 'mechanical', count(*), round(avg(net_r), 4),
       round(count(*) filter (where net_r > 0)::numeric / nullif(count(*), 0), 4)
from mechanical
union all
select 'baseline', coalesce(sum(n_trades), 0),
       round((sum(sum_r) - sum(sum_cost_r)) / nullif(sum(n_trades), 0), 4),
       round(sum(n_wins)::numeric / nullif(sum(n_trades), 0), 4)
from base;

grant select on replay_scorecard to anon, authenticated;
