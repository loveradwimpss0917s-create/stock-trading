-- 全4,446銘柄を検索対象にしつつ、日足が入っているかを1列で持たせる。
-- 取得済みの銘柄だけを検索できても実用にならないため、securities全体を
-- 対象にし、has_dataでUI側が「まだ未取得」を示せるようにする。
create or replace view securities_searchable
with (security_invoker = on) as
select
  s.code, s.ticker4, s.name_ja, s.name_en, s.market_code,
  s.sector17, s.sector33, s.scale_category,
  exists (select 1 from daily_quotes q where q.code = s.code) as has_data
from securities s;

grant select on securities_searchable to anon, authenticated;

-- 前方一致・部分一致検索の実効性のため（ilike '%...%' はindex non-sargableだが
-- 4,446行なら全走査でも十分。将来pg_trgmに切り替える余地は残す）
create index if not exists securities_name_ja_idx on securities (name_ja);
