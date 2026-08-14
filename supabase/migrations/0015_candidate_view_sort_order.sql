-- trade_candidates_view はテーマの sort_order を出していなかったため、
-- APIは theme_key のアルファベット順で返すしかなかった。テーマが12→20に
-- 増えて、業種テーマとファクターテーマが交互に並ぶようになったので
-- 並び順を制御できるようにする。
--
-- create or replace view は末尾への列追加のみ許すため、sort_order は最後に置く。
create or replace view trade_candidates_view
with (security_invoker = on) as
select
  c.as_of, c.theme_key, t.name_ja as theme_name, t.kind as theme_kind,
  t.description as theme_description,
  c.horizon, c.side, c.rank, c.score,
  c.entry_ref, c.stop_price, c.target_price, c.atr_14, c.rr_ratio,
  c.rationale,
  s.code, s.ticker4, s.name_ja, s.sector33, s.scale_category,
  t.sort_order as theme_sort_order
from trade_candidates c
join themes t     on t.key  = c.theme_key
join securities s on s.code = c.code;

grant select on trade_candidates_view to anon, authenticated;
