-- 手入力の計画を受け入れる。
--
-- ここまでのkabuは、遅延データから作られたバッチ候補しか計画にできなかった。
-- つまり実際に自分の証券口座で今日建てたトレードは、このアプリの外にあり、
-- Risk Engineも規律の記録も一度もそれを見ていない。
--
-- C路線（銘柄選択ではなく規律と리スク管理を担う）を採る以上、これは
-- 空白ではなく前提の欠落である。手入力を入れて初めて、規律パネルにデータが
-- 入り、破産確率の入力が自分の実績になる。
alter table trade_plans add column if not exists atr numeric(18,4);

comment on column trade_plans.atr is
  'この計画を立てた時点のATR(14)。コスト計算に使う。NULLなら最低スリッページ率にフォールバックし、コストは実際より小さく出る。';

-- 'manual' Setup は仮説を主張しない入れ物。enabled=false なので scan は
-- これを走査しない（stop_rule が atr_mult ではないため resolve_plan_levels
-- が扱えない、という実装上の理由でもある）。
insert into setups (
  key, name_ja, horizon, hypothesis, context,
  candidate_rule, trigger_rule, invalidation_rule,
  stop_rule, target_rule, time_stop_bars, expiry_bars, min_rr, enabled, sort_order
) values (
  'manual', '手入力', 'swing',
  'このSetupは仮説を主張しない。ユーザーが自分の判断で建てたトレードを、同じ規律とリスク計算の下に置くための入れ物である。',
  '{}'::jsonb,
  '{"type": "manual"}'::jsonb,
  '{"type": "manual"}'::jsonb,
  '{"type": "manual"}'::jsonb,
  '{"type": "manual"}'::jsonb,
  '{"type": "manual"}'::jsonb,
  10, 5, 0.0,
  false,
  999
)
on conflict (key) do nothing;

-- `select tp.*` はビュー作成時に列が展開されるため、後から足した atr は
-- 自動では現れない。作り直す。
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
