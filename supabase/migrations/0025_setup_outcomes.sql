-- Setup版のShadow Book。candidate_outcomes/screen_baselineが旧テーマ
-- スクリーニングに対して果たしていた役割を、新しいSetup体系に対して担う。
-- リプレイ訓練モードはここから過去の候補を引き、結果を種明かしする。
create table if not exists setup_outcomes (
  as_of         date not null,
  setup_key     text not null references setups(key) on delete cascade,
  code          text not null references securities(code),

  trigger_price numeric(18,4) not null,
  stop_planned  numeric(18,4) not null,
  target_planned numeric(18,4) not null,

  entry_fill    numeric(18,4),
  exit_price    numeric(18,4),
  exit_date     date,
  bars_held     int,
  outcome       text not null check (outcome in ('target', 'stop', 'timeout', 'no_entry')),
  r_multiple    numeric(10,4),

  created_at    timestamptz not null default now(),
  primary key (as_of, setup_key, code)
);

create index if not exists setup_outcomes_setup_idx on setup_outcomes (setup_key);

alter table setup_outcomes enable row level security;
drop policy if exists setup_outcomes_read on setup_outcomes;
create policy setup_outcomes_read on setup_outcomes for select to anon, authenticated using (true);
grant select on setup_outcomes to anon, authenticated;

-- リプレイ画面用：securities/setupsを結合した表示ビュー。
create or replace view setup_outcomes_view
with (security_invoker = on) as
select
  o.*,
  s.ticker4,
  s.name_ja as security_name,
  st.name_ja as setup_name,
  st.hypothesis as setup_hypothesis
from setup_outcomes o
join securities s on s.code = o.code
join setups st on st.key = o.setup_key;

grant select on setup_outcomes_view to anon, authenticated;

-- 対照群と同じ理由でこちらにも必要：無選別に買った場合との比較無しに
-- Setup単体の平均Rを「効いている」と読んではいけない。既存の
-- screen_baselineとは母集団もSetupの水準計算も異なるため独立に持つ。
create or replace view setup_outcomes_summary
with (security_invoker = on) as
select
  setup_key,
  count(*) filter (where outcome <> 'no_entry')                    as n_trades,
  count(*) filter (where outcome = 'no_entry')                     as n_no_entry,
  round(avg(r_multiple) filter (where outcome <> 'no_entry'), 4)   as avg_r,
  round(
    count(*) filter (where r_multiple > 0)::numeric
    / nullif(count(*) filter (where outcome <> 'no_entry'), 0), 4
  ) as win_rate
from setup_outcomes
group by setup_key;

grant select on setup_outcomes_summary to anon, authenticated;
