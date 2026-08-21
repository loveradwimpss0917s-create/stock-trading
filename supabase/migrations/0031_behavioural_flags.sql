-- 行動的失敗の自動検出。
--
-- ここが「優位性が無くても今日から正しく動く」もう一方の柱。銘柄選択に価値が
-- 見つからなくても、規律の破れは事実として観測できる。予測ではなく、自分が
-- 実際に何をしたかの算術だからである。
--
-- 各フラグは「あなたが計画に対して何をしたか」だけを見る。Setupが有効か、
-- Regimeが正しいかには一切依存しない（未検証の仮説はゲートにせず記録の軸に
-- する、というこのリポジトリの原則そのもの）。
--
-- 注意して設計したこと：フラグは「損したから悪い」ではない。計画どおりに
-- 実行して負けたトレードは正しいトレードであり、フラグは立たない。逆に、
-- 計画を破って勝ったトレードにはフラグが立つ。これが一番大事な区別で、
-- 損益で規律を評価すると必ず壊れる。
create or replace view position_behaviour
with (security_invoker = on) as
select
  p.id                as position_id,
  p.account_id,
  p.code,
  p.opened_on,
  p.closed_on,
  p.status,
  p.exit_reason,
  p.r_multiple,
  p.mae_r,
  p.mfe_r,
  tp.setup_key,
  tp.stop_planned,
  p.stop_current,
  p.time_stop_on,
  round((p.entry_price - tp.stop_planned) * p.shares, 2) as risk_taken_yen,

  -- 1. ストップを不利な方向に動かした。最も損害が大きい破り方で、しかも
  --    その瞬間には「まだ戻る」という合理的に見える説明がつく。
  (p.stop_current < tp.stop_planned)                     as stop_widened,

  -- 2. タイムストップを過ぎても持ち続けた。exit_reasonがtime_stopなら
  --    それは計画どおりの手仕舞いなので除外する。
  (p.closed_on is not null
     and p.closed_on > p.time_stop_on
     and p.exit_reason is distinct from 'time_stop')     as held_past_time_stop,

  -- 3. 伸ばせた利益を途中で切った。裁量手仕舞い限定。ターゲット到達や
  --    ストップ発動は計画どおりなので対象外。
  (p.exit_reason = 'discretionary'
     and p.mfe_r >= 1.0
     and p.r_multiple < p.mfe_r * 0.5)                   as cut_a_winner_short,

  -- 4. ストップ幅を超えて逆行したまま保有していた。窓開けなら無実なので
  --    -1.2Rという窓一つ分の余裕を取ってある。それでも越えるなら、
  --    ストップは執行されずに見送られたと考えるのが自然。
  (p.mae_r < -1.2)                                       as rode_past_the_stop,

  -- 5. Risk EngineがPASSと判定した計画で建玉を持った。判定を上書きする
  --    こと自体は禁じられていない（最終判断は人間）。ただし記録は残る。
  exists (
    select 1 from plan_decisions d
    where d.plan_id = tp.id and d.decision = 'PASS'
  )                                                      as overrode_a_pass,

  -- 6. 判断記録の無い建玉。理由の無いトレードは後から検証できない。
  not exists (
    select 1 from plan_decisions d where d.plan_id = tp.id
  )                                                      as no_recorded_decision
from positions p
join trade_plans tp on tp.id = p.plan_id;

grant select on position_behaviour to anon, authenticated;

-- 直前のトレードの結果と、今回取ったリスクを並べる。
-- 負けた直後にサイズを上げるのは、最も再現性のある破産経路であり、
-- しかも本人には「取り返せる場面だった」としか見えない。
create or replace view risk_escalation
with (security_invoker = on) as
with ordered as (
  select
    b.position_id,
    b.account_id,
    b.opened_on,
    b.risk_taken_yen,
    lag(b.r_multiple) over w  as prev_r,
    lag(b.risk_taken_yen) over w as prev_risk_yen
  from position_behaviour b
  window w as (partition by b.account_id order by b.opened_on, b.position_id)
)
select
  o.*,
  (o.prev_r is not null and o.prev_r < 0
     and o.risk_taken_yen > o.prev_risk_yen * 1.10)   as sized_up_after_a_loss
from ordered o;

grant select on risk_escalation to anon, authenticated;

-- 集計。個別のフラグより、こちらの比率のほうが効く。
--
-- avg_hold_winners / avg_hold_losers は損切りの遅れを直接測る。負けを
-- 勝ちより長く持っているなら、それは相場観の問題ではなく、損失を確定
-- させたくないという一点で説明がつく（disposition effect）。
create or replace view discipline_summary
with (security_invoker = on) as
select
  b.account_id,
  count(*)                                                   as n_positions,
  count(*) filter (where b.status = 'closed')                as n_closed,
  count(*) filter (where b.stop_widened)                     as n_stop_widened,
  count(*) filter (where b.held_past_time_stop)              as n_held_past_time_stop,
  count(*) filter (where b.cut_a_winner_short)               as n_cut_short,
  count(*) filter (where b.rode_past_the_stop)               as n_rode_past_stop,
  count(*) filter (where b.overrode_a_pass)                  as n_overrode_pass,
  count(*) filter (where b.no_recorded_decision)             as n_no_decision,
  (select count(*) from risk_escalation e
    where e.account_id = b.account_id and e.sized_up_after_a_loss)
                                                             as n_sized_up_after_loss,
  round(avg(b.closed_on - b.opened_on)
        filter (where b.r_multiple > 0), 2)                  as avg_hold_winners,
  round(avg(b.closed_on - b.opened_on)
        filter (where b.r_multiple <= 0), 2)                 as avg_hold_losers,
  -- 計画どおりに終わったトレードの比率。これが規律の総合点で、
  -- 損益とは独立に評価できる唯一の数字。
  round(
    count(*) filter (
      where b.status = 'closed'
        and not b.stop_widened and not b.held_past_time_stop
        and not b.cut_a_winner_short and not b.rode_past_the_stop
        and not b.no_recorded_decision
    )::numeric / nullif(count(*) filter (where b.status = 'closed'), 0), 4
  )                                                          as plan_adherence_rate
from position_behaviour b
group by b.account_id;

grant select on discipline_summary to anon, authenticated;
