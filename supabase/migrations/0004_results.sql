create table if not exists strategies (
  id serial primary key,
  name text not null unique,
  definition jsonb not null,        -- 特徴量重み・ルール
  created_at timestamptz default now()
);

create table if not exists scores (
  code text not null references securities(code),
  date date not null,
  strategy_id int not null references strategies(id),
  raw_score numeric,
  z_score numeric,
  rank int,
  sector_neutral_score numeric,
  primary key (code, date, strategy_id)
);
create index on scores (date, strategy_id, rank);

create table if not exists backtest_runs (
  id bigint generated always as identity primary key,
  strategy_id int references strategies(id),
  params jsonb not null,
  period_start date, period_end date,
  n_trials int,                     -- DSR用の試行回数
  created_at timestamptz default now()
);

create table if not exists backtest_metrics (
  run_id bigint references backtest_runs(id),
  expectancy numeric, profit_factor numeric,
  sharpe numeric, sortino numeric, calmar numeric,
  max_dd numeric, win_rate numeric, n_trades int,
  avg_holding_days numeric, turnover numeric,
  primary key (run_id)
);

create table if not exists stats_validation (
  run_id bigint references backtest_runs(id),
  dsr numeric,                      -- Deflated Sharpe Ratio
  psr numeric,
  expected_max_sharpe numeric,
  pbo numeric,                      -- Probability of Backtest Overfitting
  n_trials int,
  skew numeric, kurtosis numeric,
  passed boolean,                   -- 採用ゲート結果
  primary key (run_id)
);

create table if not exists model_generations (
  id serial primary key,
  version text not null,
  description text,
  feature_set text,
  created_at timestamptz default now()
);
