-- MVPは3 Setupのみ。多いほど多重比較で分析が汚れるため、少数で始める
-- （設計書PART12）。ルールの語彙は pipeline_py/setups/rules.py の評価器と
-- 1対1で対応する — この語彙を増やすときは両方を同時に変更すること。
--
-- 全トリガー/反証は終値ベースに限定する。日足しか無いためザラ場中の
-- 「出来高を伴う突破」は判定不可能（設計書PART7の制約）。
insert into setups (
  key, name_ja, horizon, hypothesis, context, candidate_rule,
  trigger_rule, invalidation_rule, stop_rule, target_rule,
  time_stop_bars, expiry_bars, min_rr, sort_order
) values
  (
    'breakout_20d', 'ブレイクアウト（20日高値）', 'swing',
    '20日高値更新は短期的な上昇継続を伴う',
    '{"note": "業種テーマの t 値検証は業種ベータと未分離。この Setup は業種横断で単独評価する"}',
    '{"close_above_ma25": true, "dist_from_high20_pct_max": 0.03, "adx_14_min": 20, "min_turnover": 300000000}',
    '{"type": "close_above", "ref": "high_20", "buffer_pct": 0.0}',
    '{"type": "close_below", "ref": "low_10"}',
    '{"type": "atr_mult", "mult": 1.8}',
    '{"type": "atr_mult", "mult": 3.0}',
    10, 5, 1.5, 10
  ),
  (
    'pullback_ma25', '押し目（25日線）', 'swing',
    '上昇トレンド中に25日線まで調整した銘柄は買われ直す',
    '{}',
    '{"close_above_ma75": true, "dist_to_ma25_pct_max": 0.03, "ret_20d_min": 0.05, "min_turnover": 300000000}',
    '{"type": "close_above", "ref": "prior_high"}',
    '{"type": "close_below", "ref": "ma_75"}',
    '{"type": "atr_mult", "mult": 1.8}',
    '{"type": "atr_mult", "mult": 3.0}',
    10, 5, 1.5, 20
  ),
  (
    'reversal_3d', 'デイ・リバーサル（3日続落）', 'day',
    '3営業日続落した銘柄は短期的に戻りやすい',
    '{}',
    '{"consecutive_down_days_min": 3, "atr_pct_min": 0.012, "min_turnover": 300000000}',
    '{"type": "close_above", "ref": "prior_high"}',
    '{"type": "additional_atr_drawdown", "mult": 1.5}',
    '{"type": "atr_mult", "mult": 1.0}',
    '{"type": "atr_mult", "mult": 1.5}',
    1, 2, 1.5, 30
  )
on conflict (key) do update set
  name_ja         = excluded.name_ja,
  horizon         = excluded.horizon,
  hypothesis      = excluded.hypothesis,
  context         = excluded.context,
  candidate_rule  = excluded.candidate_rule,
  trigger_rule    = excluded.trigger_rule,
  invalidation_rule = excluded.invalidation_rule,
  stop_rule       = excluded.stop_rule,
  target_rule     = excluded.target_rule,
  time_stop_bars  = excluded.time_stop_bars,
  expiry_bars     = excluded.expiry_bars,
  min_rr          = excluded.min_rr,
  sort_order      = excluded.sort_order;
