create or replace view trade_candidates_view
with (security_invoker = on) as
select
  c.as_of, c.theme_key, t.name_ja as theme_name, t.kind as theme_kind,
  t.description as theme_description,
  c.horizon, c.side, c.rank, c.score,
  c.entry_ref, c.stop_price, c.target_price, c.atr_14, c.rr_ratio,
  c.rationale,
  s.code, s.ticker4, s.name_ja, s.sector33, s.scale_category
from trade_candidates c
join themes t     on t.key  = c.theme_key
join securities s on s.code = c.code;

grant select on trade_candidates_view to anon, authenticated;

-- 候補の基準日。UIが「いつ時点か」を必ず出せるようにする。
create or replace view candidates_asof
with (security_invoker = on) as
select max(as_of) as as_of, (current_date - max(as_of)) as days_behind
from trade_candidates;

grant select on candidates_asof to anon, authenticated;
