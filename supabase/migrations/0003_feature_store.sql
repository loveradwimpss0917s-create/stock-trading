create table if not exists features (
  code        text not null references securities(code),
  date        date not null,
  feature_set text not null default 'v1',
  -- テクニカル
  ret_1d numeric, ret_5d numeric, ret_20d numeric,
  ma_25 numeric, ma_75 numeric, ema_12 numeric, ema_26 numeric,
  rsi_14 numeric, macd numeric, macd_signal numeric,
  atr_14 numeric, adx_14 numeric, bb_upper numeric, bb_lower numeric,
  vol_20d numeric, dist_52w_high numeric,
  -- ファンダ/クオリティ/バリュー
  per numeric, pbr numeric, roe numeric, roic numeric,
  accruals numeric, gross_profitability numeric,
  -- イベント/需給フラグ
  is_buyback boolean default false,
  is_div_up boolean default false,
  margin_ratio numeric,
  short_balance_ratio numeric,
  known_from  timestamptz not null default now(),  -- as-of強制用
  primary key (code, date, feature_set)
);
create index on features (date, feature_set);
