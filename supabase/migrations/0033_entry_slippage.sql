-- エントリー滑りを、初めて数字として出す。
--
-- 「終値がXを超えたら翌日の寄りで買う」という入り方は、実測すると
-- 平均で 0.30〜0.41R 高い値段で約定していた。手数料でもスプレッドでもなく、
-- 入り方そのものが払っているコストで、しかも往復コスト（0.10〜0.18R）より
-- 大きい。
--
-- r_multiple は元から実約定値を基準に計算しているので、この滑りは
-- 最初から支払われていた。ただ一度も表示されていなかっただけである。
-- 別列にするのは、これが誤差ではなく最大の費目だからで、
-- 「手数料の安い証券会社に移せば解決する」という誤った結論を防ぐ意味もある。
alter table setup_outcomes add column if not exists entry_slip_r numeric(10,4);

comment on column setup_outcomes.entry_slip_r is
  'トリガー価格に対して実際にいくら高く約定したかをRで表したもの。約定しなかった計画はnull。';

drop view if exists replay_scorecard;
drop view if exists setup_edge;
drop view if exists setup_outcomes_summary;

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
  round(avg(entry_slip_r) filter (where entry_slip_r is not null), 4) as avg_entry_slip_r,
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
