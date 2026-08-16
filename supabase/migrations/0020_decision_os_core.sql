-- kabu を「候補を並べるスクリーナー」から「計画を状態機械として管理するOS」へ
-- 拡張する中核スキーマ。設計は kabu-decision-os 設計書 PART 13.1/13.2 に対応する。
--
-- 認証について：現在このアプリにはログインが無く（auth.users は0件）、
-- Worker は anon key で全テーブルに触れる。新設のテーブル群もこれに合わせ
-- RLSは有効化した上で anon/authenticated に using(true) を与える —
-- 既存の candidate_outcomes 等と同じ姿勢であり、後退ではない。
-- ただし建玉・計画・資金設定という個人の意思決定データが世界に書き込み可能
-- になる点は、既存の「読み取り専用の研究データ」とは性質が違う。
-- 認証を足す際は各テーブルに user_id を追加し、このポリシーを
-- auth.uid() 制約に差し替えるだけで済むよう、bigint identity PKと
-- 素直な外部キーで設計してある。

create table if not exists accounts (
  id bigint generated always as identity primary key,
  name text not null default 'default',
  capital numeric(18,2) not null,
  risk_per_trade numeric(6,4) not null default 0.005,   -- 1トレード許容損失率
  max_positions int not null default 5,
  max_heat numeric(6,4) not null default 0.03,           -- Portfolio heat上限
  max_notional_pct numeric(6,4) not null default 0.30,   -- 1建玉の投下資金上限(資金比)
  min_rr numeric(6,3) not null default 1.5,
  max_sector_positions int not null default 2,           -- 同一sector33の同時建玉上限
  created_at timestamptz not null default now()
);

alter table accounts enable row level security;
drop policy if exists accounts_all on accounts;
create policy accounts_all on accounts for all to anon, authenticated using (true) with check (true);
grant select, insert, update on accounts to anon, authenticated;

-- MVPは単一アカウント運用。後で複数アカウントに拡張しても行が増えるだけ。
insert into accounts (name, capital, risk_per_trade)
select 'default', 5000000, 0.005
where not exists (select 1 from accounts);

-- ---------------------------------------------------------------------
-- Setup: 「取引仮説の分類」。trigger/invalidation の必須化がテーマとの
-- 決定的な違い — この2つを書けないものは登録できない。
create table if not exists setups (
  key text primary key,
  name_ja text not null,
  horizon text not null check (horizon in ('day', 'swing')),
  hypothesis text not null,              -- 成立を主張しない。検証対象の文
  context jsonb not null default '{}',   -- 前提条件。記録軸であってゲートではない
  candidate_rule jsonb not null,         -- 候補になる絶対基準（相対順位ではない）
  trigger_rule jsonb not null,           -- 何が起きたら入るか
  invalidation_rule jsonb not null,      -- 何が起きたら仮説が死ぬか
  stop_rule jsonb not null,
  target_rule jsonb not null,
  time_stop_bars int not null,
  expiry_bars int not null,              -- トリガー未到達で計画を破棄するまで
  min_rr numeric(6,3) not null default 1.5,
  enabled boolean not null default true,
  sort_order int not null default 100
);

alter table setups enable row level security;
drop policy if exists setups_read on setups;
create policy setups_read on setups for select to anon, authenticated using (true);
grant select on setups to anon, authenticated;

-- ---------------------------------------------------------------------
-- Regime: 指数を取得していないため、保有ユニバース自身のBreadthから構成する。
-- regime_label はゲートではなく分析軸。有効性が未検証なので取引を止める
-- 理由にしない — これがEdge発見の母集団を汚さないための唯一の担保。
create table if not exists regime_snapshots (
  date date primary key,
  pct_above_ma25 numeric(6,4),
  pct_above_ma75 numeric(6,4),
  adv_decline_ratio numeric(6,4),
  new_high_minus_low int,
  dispersion numeric(10,6),        -- 当日リターンの断面標準偏差
  regime_label text check (regime_label in ('offense', 'neutral', 'defense')),
  computed_from_n int not null,
  created_at timestamptz not null default now()
);

alter table regime_snapshots enable row level security;
drop policy if exists regime_snapshots_read on regime_snapshots;
create policy regime_snapshots_read on regime_snapshots for select to anon, authenticated using (true);
grant select on regime_snapshots to anon, authenticated;

-- ---------------------------------------------------------------------
-- trade_plans: スナップショットではなく状態機械。
--
--   draft ──▶ armed ──▶ triggered ──▶ open ──▶ closed
--      │         │            │
--      │         ├──▶ expired       (expires_on到達・トリガー未達)
--      │         ├──▶ invalidated   (反証条件が先に成立)
--      │         └──▶ passed        (ユーザーがPASS)
--      └──▶ discarded
--
-- draft→armed        ユーザーがBUY/WAIT判断（plan_decisions経由）
-- armed→triggered    バッチ（終値でtrigger_ruleを評価）
-- triggered→open     ユーザーが約定を記録
-- armed→expired      バッチ
-- armed→invalidated  バッチ
-- open→closed        ユーザーが決済記録、またはバッチが損切り/期限を検出
create table if not exists trade_plans (
  id bigint generated always as identity primary key,
  account_id bigint not null references accounts(id),
  code text not null references securities(code),
  setup_key text not null references setups(key),
  created_on date not null,
  regime_snapshot_id date references regime_snapshots(date),

  state text not null default 'draft' check (state in (
    'draft', 'armed', 'triggered', 'open', 'closed',
    'expired', 'invalidated', 'passed', 'discarded'
  )),

  reference_close numeric(18,4) not null,   -- created_on時点の終値（トリガー計算の基準）
  trigger_price numeric(18,4) not null,
  trigger_condition jsonb not null,          -- 評価に使った具体条件のスナップショット
  stop_planned numeric(18,4) not null,
  target_planned numeric(18,4) not null,
  time_stop_bars int not null,
  expires_on date not null,
  invalidation jsonb not null,

  thesis text not null,
  anti_thesis text,                          -- AI生成はP2。手動記入は今から可
  expected_rr numeric(8,3) not null,
  shares_planned int,                        -- Risk Engine計算後に埋まる
  risk_amount numeric(18,2),
  risk_pct numeric(6,4),
  scenarios jsonb,                           -- { bull:{}, base:{}, bear:{} }

  triggered_on date,
  triggered_price numeric(18,4),

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint trigger_above_stop check (trigger_price > stop_planned),
  constraint target_above_trigger check (target_planned > trigger_price)
);

create index if not exists trade_plans_state_idx on trade_plans (account_id, state);
create index if not exists trade_plans_code_idx on trade_plans (code);
create index if not exists trade_plans_expires_idx on trade_plans (expires_on) where state = 'armed';

alter table trade_plans enable row level security;
drop policy if exists trade_plans_all on trade_plans;
create policy trade_plans_all on trade_plans for all to anon, authenticated using (true) with check (true);
grant select, insert, update on trade_plans to anon, authenticated;

-- plan_decisions: BUY/WAIT/PASSの判断記録。理由コード必須 — これがNO TRADE
-- ENGINEの実体。「なぜ見送ったか」を後から分析できることが目的なので、
-- 理由の無いdecisionは記録として無意味であり、アプリ側で弾く（DBはtext必須のみ強制）。
create table if not exists plan_decisions (
  id bigint generated always as identity primary key,
  plan_id bigint not null references trade_plans(id),
  decided_at timestamptz not null default now(),
  decision text not null check (decision in ('BUY', 'WAIT', 'PASS')),
  reason_code text not null,
  reason_note text,
  gate_results jsonb not null   -- Risk Engineの各ゲート通過状況の全記録
);

create index if not exists plan_decisions_plan_idx on plan_decisions (plan_id);

alter table plan_decisions enable row level security;
drop policy if exists plan_decisions_all on plan_decisions;
create policy plan_decisions_all on plan_decisions for all to anon, authenticated using (true) with check (true);
grant select, insert on plan_decisions to anon, authenticated;

-- ---------------------------------------------------------------------
create table if not exists positions (
  id bigint generated always as identity primary key,
  plan_id bigint not null references trade_plans(id),
  account_id bigint not null references accounts(id),
  code text not null references securities(code),

  opened_on date not null,
  entry_price numeric(18,4) not null,
  shares int not null,

  stop_current numeric(18,4) not null,
  target_current numeric(18,4) not null,
  time_stop_on date not null,

  closed_on date,
  exit_price numeric(18,4),
  exit_reason text check (exit_reason in (
    'target', 'stop', 'time_stop', 'invalidation', 'discretionary', 'regime_change'
  )),
  pnl_yen numeric(18,2),
  r_multiple numeric(10,4),
  mae_r numeric(10,4),    -- 最大逆行(R)
  mfe_r numeric(10,4),    -- 最大順行(R)

  status text not null default 'open' check (status in ('open', 'closed')),
  created_at timestamptz not null default now()
);

create index if not exists positions_status_idx on positions (account_id, status);
create index if not exists positions_code_idx on positions (code);

alter table positions enable row level security;
drop policy if exists positions_all on positions;
create policy positions_all on positions for all to anon, authenticated using (true) with check (true);
grant select, insert, update on positions to anon, authenticated;

create table if not exists position_events (
  id bigint generated always as identity primary key,
  position_id bigint not null references positions(id),
  occurred_on date not null,
  event_type text not null check (event_type in (
    'stop_moved', 'target_moved', 'partial_exit', 'thesis_review',
    'volume_deterioration', 'regime_shift', 'gap', 'note'
  )),
  price numeric(18,4),
  note text,
  thesis_status text check (thesis_status in ('intact', 'weakening', 'broken')),
  created_at timestamptz not null default now()
);

create index if not exists position_events_position_idx on position_events (position_id);

alter table position_events enable row level security;
drop policy if exists position_events_all on position_events;
create policy position_events_all on position_events for all to anon, authenticated using (true) with check (true);
grant select, insert on position_events to anon, authenticated;

-- ---------------------------------------------------------------------
-- trade_journal: Before/During/Afterを1レコードに集約するビュー的な実体テーブル。
-- Beforeはtrade_plans作成時に確定し以後不変（計画レコード自体がBeforeを保持する
-- ため、ここではpositionとの1:1の後追い情報だけを持つ）。
create table if not exists trade_journal (
  position_id bigint primary key references positions(id),
  during jsonb not null default '[]',     -- position_eventsの要約キャッシュ（表示高速化用）
  thesis_was_correct boolean,
  execution_adherence text check (execution_adherence in (
    'as_planned', 'entered_early', 'entered_late', 'stop_moved_against_plan',
    'exited_early', 'exited_late', 'size_deviated'
  )),
  review_note text,
  reviewed_at timestamptz
);

alter table trade_journal enable row level security;
drop policy if exists trade_journal_all on trade_journal;
create policy trade_journal_all on trade_journal for all to anon, authenticated using (true) with check (true);
grant select, insert, update on trade_journal to anon, authenticated;

-- ---------------------------------------------------------------------
-- replay_sessions: 84日遅延を逆手に取った訓練モード。過去日を「今日」として
-- 提示し、以降のデータを隠したまま判断させる。統計的検出力を得る唯一の
-- 現実的手段（実弾では年数百取引、Rの標準偏差1.2〜1.9では優位性の検出に
-- 数年を要する）。
create table if not exists replay_sessions (
  id bigint generated always as identity primary key,
  account_id bigint not null references accounts(id),
  as_of date not null,             -- 「今日」として提示する過去日
  revealed boolean not null default false,
  decisions jsonb not null default '[]',
  created_at timestamptz not null default now(),
  revealed_at timestamptz
);

create index if not exists replay_sessions_account_idx on replay_sessions (account_id, revealed);

alter table replay_sessions enable row level security;
drop policy if exists replay_sessions_all on replay_sessions;
create policy replay_sessions_all on replay_sessions for all to anon, authenticated using (true) with check (true);
grant select, insert, update on replay_sessions to anon, authenticated;
