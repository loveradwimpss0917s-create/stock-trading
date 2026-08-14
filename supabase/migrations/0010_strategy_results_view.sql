-- 戦略ごとの成績＋統計検証を1行にまとめる。
-- フロントが3テーブルを個別に引いてJS側で結合すると、PostgRESTのmax_rows
-- や結合漏れの罠を再び踏むため、DB側で結合する。
create or replace view strategy_results
with (security_invoker = on) as
select
  r.id                as run_id,
  s.name              as strategy,
  s.definition        as definition,
  r.period_start,
  r.period_end,
  m.sharpe,
  m.sortino,
  m.calmar,
  m.max_dd,
  m.win_rate,
  m.n_trades,
  m.avg_holding_days,
  m.profit_factor,
  m.expectancy,
  v.dsr,
  v.pbo,
  v.expected_max_sharpe,
  v.n_trials,
  v.skew,
  v.kurtosis,
  coalesce(v.passed, false) as passed
from backtest_runs r
join strategies s        on s.id = r.strategy_id
left join backtest_metrics m on m.run_id = r.id
left join stats_validation v on v.run_id = r.id;

grant select on strategy_results to anon, authenticated;

-- データ鮮度。売買判断に使えないことを画面上で構造的に示すために、
-- 「最新データが何日前か」を返す。バナー文言だけでは伝わらない。
create or replace view data_freshness
with (security_invoker = on) as
select
  max(date)                                as latest_date,
  (current_date - max(date))               as days_behind
from daily_quotes;

grant select on data_freshness to anon, authenticated;
