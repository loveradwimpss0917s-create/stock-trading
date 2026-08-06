-- 銘柄マスタ（上場廃止銘柄も保持＝サバイバーシップバイアス対策）
create table if not exists securities (
  code            text primary key,               -- J-Quants 5桁コード (例 72030)
  ticker4         text not null,                   -- 4桁 (7203)
  name_ja         text,
  name_en         text,
  market_code     text,                            -- プライム/スタンダード/グロース
  sector17        text,
  sector33        text,
  scale_category  text,
  listed_date     date,
  delisted_date   date,                            -- NULL=上場中。非NULL=廃止済(保持)
  is_active       boolean generated always as (delisted_date is null) stored,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index on securities (sector33);
create index on securities (market_code);

-- 日次四本値（親テーブル。月次RANGEパーティション）
create table if not exists daily_quotes (
  code            text not null references securities(code),
  date            date not null,
  open            numeric(12,2),
  high            numeric(12,2),
  low             numeric(12,2),
  close           numeric(12,2),
  volume          bigint,
  turnover_value  bigint,
  adj_factor      numeric(18,8) default 1.0,
  adj_close       numeric(12,2),
  known_from      timestamptz not null default now(),  -- このレコードを我々が知り得た時刻
  primary key (code, date)
) partition by range (date);

-- 財務データ（bitemporal: valid_from/valid_to + known_from/known_to）
create table if not exists financials (
  id              bigint generated always as identity,
  code            text not null references securities(code),
  disclosure_date date not null,                   -- 開示日
  fiscal_period   text not null,                   -- 1Q/2Q/3Q/FY
  period_start    date,
  period_end      date,
  net_sales       numeric(20,0),
  operating_profit numeric(20,0),
  ordinary_profit numeric(20,0),
  net_income      numeric(20,0),
  total_assets    numeric(20,0),
  equity          numeric(20,0),
  eps             numeric(12,4),
  bps             numeric(12,4),
  dividend_per_share numeric(12,4),
  forecast_flag   boolean default false,
  -- bitemporal 4列
  valid_from      date not null,                   -- 会計期間ベースで事実が有効な開始
  valid_to        date not null default 'infinity',
  known_from      timestamptz not null,            -- 我々/市場が知り得た時刻(=開示)
  known_to        timestamptz not null default 'infinity',
  source          text not null default 'jquants',
  primary key (id)
);
create index on financials (code, known_from);
create index on financials (code, period_end);
create index on financials (code, disclosure_date);

-- 信用残・空売り残（JPX公開CSV or Standard以上のJ-Quantsから）
create table if not exists margin_short (
  code            text not null references securities(code),
  date            date not null,
  margin_long     bigint,                          -- 信用買い残
  margin_short    bigint,                          -- 信用売り残
  margin_ratio    numeric(10,4),                   -- 信用倍率 = long/short
  short_balance_ratio numeric(8,4),                -- 空売り残高割合(0.5%超公表)
  data_freq       text not null default 'weekly',  -- weekly/daily
  source          text not null default 'jpx_csv',
  known_from      timestamptz not null default now(),
  primary key (code, date, data_freq)
);

-- 適時開示イベント（TDnet/EDINET由来）
create table if not exists disclosure_events (
  id              bigint generated always as identity,
  code            text references securities(code),
  disclosed_at    timestamptz not null,
  event_type      text not null,   -- buyback/dividend_up/pbr_improvement/index_change 等
  title           text,
  doc_id          text,            -- EDINET docID / TDnet開示番号
  source          text not null,   -- edinet/tdnet
  raw_url         text,
  known_from      timestamptz not null default now(),
  primary key (id)
);
create index on disclosure_events (code, disclosed_at);
create index on disclosure_events (event_type, disclosed_at);
