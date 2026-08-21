-- 計画の「コスト後R:R」を可視化する。
--
-- expected_rr はチャート上の2つの価格から出る建前の数字で、実際に取れる
-- 数字ではない。往復コストは勝ちトレードの利益を削るだけでなく、負けトレード
-- の損失も深くする（1R + 往復コスト）ので、比率は単純な引き算より速く落ちる。
--
-- expected_rr の意味は変えない。この変更以前に書かれた行はグロスであり、
-- 列の意味を後から書き換えると過去の行が黙って嘘になるため、正味の数字は
-- 隣の新しい列に置く。NULL は「コストを課す前に作られた計画」を正しく表す。
alter table trade_plans
  add column if not exists expected_rr_net numeric(10,3),
  add column if not exists expected_cost_r numeric(10,4);

comment on column trade_plans.expected_rr is
  'グロスR:R（コスト控除前）。チャート上の価格差のみ。';
comment on column trade_plans.expected_rr_net is
  '往復コスト控除後のR:R。実際に取れる数字。NULLはコスト導入前に作成された計画。';
comment on column trade_plans.expected_cost_r is
  '往復コストをRで表したもの。損切り幅が狭いほど大きくなる（2×slippage率÷ATR倍率）。';

-- Risk Engine が決定時にコストを計算するには ATR が要る。ATR 自体は
-- trade_plans に持っていないが、stop_planned = trigger_price − mult × ATR
-- という定義から厳密に逆算できるので、倍率をビューに出すだけで足りる。
drop view if exists trade_plans_view;
create view trade_plans_view
with (security_invoker = on) as
select
  tp.*,
  st.name_ja     as setup_name,
  st.horizon     as setup_horizon,
  st.hypothesis  as setup_hypothesis,
  st.stop_rule   as setup_stop_rule,
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
