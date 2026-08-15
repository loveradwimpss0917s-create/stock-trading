-- 対照群。同じ基準日・同じ損切り/目標条件で「全銘柄を無選別に買った」場合の成績。
--
-- これが無いとテーマの平均Rは読めない。検証期間は日本株が上昇した局面で、
-- 買いのみのスクリーニングは銘柄選択が無意味でも上昇相場ではプラスになる。
-- テーマが超えるべき基準は0ではなく、この対照群である。
--
-- 1取引ずつではなく基準日ごとの集計で保存する（全銘柄×全基準日は数万件になり、
-- 平均を出す以上の使い道がない）。合計Rを持つのは、セッション間で件数が違うため
-- 平均の平均では正しい加重にならないから。
create table if not exists screen_baseline (
  as_of      date not null,
  horizon    text not null check (horizon in ('day','swing')),
  n_trades   int not null,
  n_no_entry int not null default 0,
  sum_r      numeric(18,6) not null,
  n_wins     int not null,
  created_at timestamptz not null default now(),
  primary key (as_of, horizon)
);

alter table screen_baseline enable row level security;

drop policy if exists screen_baseline_read on screen_baseline;
create policy screen_baseline_read on screen_baseline for select to anon, authenticated using (true);

grant select on screen_baseline to anon, authenticated;

create or replace view screen_baseline_summary
with (security_invoker = on) as
select
  horizon,
  sum(n_trades)                                as n_trades,
  sum(n_no_entry)                              as n_no_entry,
  round(sum(sum_r) / nullif(sum(n_trades), 0), 4) as avg_r,
  round(sum(n_wins)::numeric / nullif(sum(n_trades), 0), 4) as win_rate
from screen_baseline
group by horizon;

grant select on screen_baseline_summary to anon, authenticated;

-- テーマの成績を対照群との差で表す。edge_r が正でなければ、
-- そのテーマは無選別に買うのと比べて何も足していない。
create or replace view theme_edge
with (security_invoker = on) as
select
  p.*,
  b.avg_r    as baseline_avg_r,
  b.win_rate as baseline_win_rate,
  round(p.avg_r - b.avg_r, 4)       as edge_r,
  round(p.win_rate - b.win_rate, 4) as edge_win_rate
from theme_performance p
left join screen_baseline_summary b on b.horizon = p.horizon;

grant select on theme_edge to anon, authenticated;
