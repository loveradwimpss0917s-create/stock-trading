-- 「結果」タブはテーマ単位の集計しか出していなかったが、実際に知りたいのは
-- 「売買候補に出たあの銘柄を買っていたら、いくらになったか」である。
-- 1件ずつの明細は candidate_outcomes に既にあるので、銘柄名とテーマ名を
-- 付けて引けるようにする。
create or replace view candidate_outcomes_view
with (security_invoker = on) as
select
  o.as_of,
  o.theme_key,
  t.name_ja    as theme_name,
  t.kind       as theme_kind,
  t.sort_order as theme_sort_order,
  o.horizon,
  o.rank,
  o.code,
  s.ticker4,
  s.name_ja,
  o.entry_fill,
  o.stop_price,
  o.target_price,
  o.exit_price,
  o.exit_date,
  o.bars_held,
  o.outcome,
  o.r_multiple,
  -- 1株あたりの損益。株数は資金と許容損失から画面側で決まるので、
  -- 円建ての損益はここでは出さず単価差のみを返す。
  case when o.exit_price is not null and o.entry_fill is not null
       then o.exit_price - o.entry_fill end as pnl_per_share
from candidate_outcomes o
join themes t     on t.key  = o.theme_key
join securities s on s.code = o.code;

grant select on candidate_outcomes_view to anon, authenticated;

-- 「全候補を機械的に取っていたら」の合計。1件ずつ眺めるだけでは
-- 全体でプラスなのかマイナスなのかが分からない。
create or replace view candidate_outcomes_totals
with (security_invoker = on) as
select
  horizon,
  count(*) filter (where outcome <> 'no_entry')  as n_trades,
  count(*) filter (where outcome = 'no_entry')   as n_no_entry,
  count(*) filter (where r_multiple > 0)         as n_wins,
  round(sum(r_multiple) filter (where outcome <> 'no_entry'), 3) as total_r,
  round(avg(r_multiple) filter (where outcome <> 'no_entry'), 4) as avg_r,
  round(avg(bars_held)  filter (where outcome <> 'no_entry'), 2) as avg_bars_held,
  min(as_of) as first_as_of,
  max(as_of) as last_as_of
from candidate_outcomes
group by horizon;

grant select on candidate_outcomes_totals to anon, authenticated;
