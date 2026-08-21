-- リプレイ訓練の成績表。設計書PART11の「ユーザーの選別がShadow Bookを
-- 上回るか」の実装。
--
-- 3者を同じ基準日集合の上で比較する：
--   your_buy   … あなたがBUYと判断した銘柄だけ
--   mechanical … その日に出た候補を全部採用した場合（＝Setupそのもの）
--   baseline   … 取引可能な全銘柄を無選別に買った場合
--
-- なぜ3者必要か：your_buy が baseline を上回っても、mechanical も同じだけ
-- 上回っているなら、それはSetupの手柄であってあなたの選別ではない。
-- 逆に mechanical が baseline を上回らないなら、そもそも選ぶ母集団に
-- 価値が無い。2者比較ではこの区別がつかない。
create or replace view replay_scorecard
with (security_invoker = on) as
with revealed_sessions as (
  select distinct as_of from replay_sessions where revealed = true
),
decided as (
  select
    rs.as_of,
    d->>'code'      as code,
    d->>'setup_key' as setup_key,
    d->>'decision'  as decision
  from replay_sessions rs,
       lateral jsonb_array_elements(rs.decisions) d
  where rs.revealed = true
),
-- 建たずに終わった計画はRの分母から外す（setup_outcomes_summaryと同じ扱い）
traded as (
  select o.as_of, o.code, o.setup_key, o.r_multiple
  from setup_outcomes o
  join revealed_sessions r on r.as_of = o.as_of
  where o.outcome not in ('expired', 'invalidated', 'no_entry')
),
your_buy as (
  select t.r_multiple
  from traded t
  join decided d
    on d.as_of = t.as_of and d.code = t.code and d.setup_key = t.setup_key
  where d.decision = 'BUY'
),
mechanical as (
  select r_multiple from traded
),
base as (
  select b.sum_r, b.n_trades, b.n_wins
  from setup_baseline b
  join revealed_sessions r on r.as_of = b.as_of
)
select 'your_buy' as cohort,
       count(*)                                            as n_trades,
       round(avg(r_multiple), 4)                           as avg_r,
       round(count(*) filter (where r_multiple > 0)::numeric
             / nullif(count(*), 0), 4)                     as win_rate
from your_buy
union all
select 'mechanical',
       count(*),
       round(avg(r_multiple), 4),
       round(count(*) filter (where r_multiple > 0)::numeric / nullif(count(*), 0), 4)
from mechanical
union all
select 'baseline',
       coalesce(sum(n_trades), 0),
       round(sum(sum_r) / nullif(sum(n_trades), 0), 4),
       round(sum(n_wins)::numeric / nullif(sum(n_trades), 0), 4)
from base;

grant select on replay_scorecard to anon, authenticated;
