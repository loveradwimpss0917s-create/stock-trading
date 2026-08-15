-- 選別効果(edge_r)だけを出すと、0.02Rの差を「効果あり」と読んでしまう。
-- 1取引あたりのRのばらつきは標準偏差1.2〜1.9あり、800件でも標準誤差は0.04〜0.10R。
-- t値を併記しないと、ノイズを実力として提示することになる。
--
-- t値は上限であって下限ではない点に注意：
--   * 週次サンプリング×10営業日保有なので取引期間が重複しており、
--     実効サンプル数は件数より少ない
--   * 21テーマを同時に比較しているので、帰無仮説の下でも |t|>2 が
--     1つ程度は偶然出る
create or replace view theme_edge
with (security_invoker = on) as
with dispersion as (
  select theme_key, horizon,
         stddev_samp(r_multiple) as sd_r,
         count(*)                as n
  from candidate_outcomes
  where outcome <> 'no_entry'
  group by theme_key, horizon
)
select
  p.*,
  b.avg_r    as baseline_avg_r,
  b.win_rate as baseline_win_rate,
  round(p.avg_r - b.avg_r, 4)       as edge_r,
  round(p.win_rate - b.win_rate, 4) as edge_win_rate,
  round(d.sd_r::numeric, 4)                               as sd_r,
  round((d.sd_r / sqrt(nullif(d.n, 0)))::numeric, 4)      as se_r,
  round(((p.avg_r - b.avg_r) / nullif(d.sd_r / sqrt(nullif(d.n, 0)), 0))::numeric, 2) as t_stat
from theme_performance p
left join screen_baseline_summary b on b.horizon = p.horizon
left join dispersion d on d.theme_key = p.theme_key and d.horizon = p.horizon;

grant select on theme_edge to anon, authenticated;
