-- Joined read views for the decision-OS API, matching the existing
-- convention (trade_candidates_view, candidate_outcomes_view): the Worker
-- reads through a view carrying the display fields it needs, and writes go
-- straight to the base tables (trade_plans, positions) — a view is never a
-- write target here.
create or replace view trade_plans_view
with (security_invoker = on) as
select
  tp.*,
  st.name_ja     as setup_name,
  st.horizon     as setup_horizon,
  st.hypothesis  as setup_hypothesis,
  s.ticker4,
  s.name_ja      as security_name,
  s.sector33,
  dq.close       as current_price
from trade_plans tp
join setups st     on st.key  = tp.setup_key
join securities s  on s.code  = tp.code
left join lateral (
  select close from daily_quotes q
  where q.code = tp.code
  order by q.date desc
  limit 1
) dq on true;

grant select on trade_plans_view to anon, authenticated;

-- current_risk: what's still at stake right now if this position hit its
-- CURRENT stop (not the entry stop) — a stop moved to breakeven or better
-- shows 0 or negative, which is exactly how a profitable, de-risked
-- position frees up new heat capacity (design PART 8).
create or replace view positions_view
with (security_invoker = on) as
select
  p.*,
  s.ticker4,
  s.name_ja  as security_name,
  s.sector33,
  dq.close   as current_price,
  case when dq.close is not null
    then round(((dq.close - p.stop_current) * p.shares)::numeric, 2)
    else null end as current_risk,
  case when dq.close is not null and p.entry_price > p.stop_current
    then round(((dq.close - p.entry_price) / (p.entry_price - p.stop_current))::numeric, 4)
    else null end as current_r
from positions p
join securities s on s.code = p.code
left join lateral (
  select close from daily_quotes q
  where q.code = p.code
  order by q.date desc
  limit 1
) dq on true;

grant select on positions_view to anon, authenticated;
