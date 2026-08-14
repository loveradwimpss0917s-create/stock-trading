-- 業種テーマは実データに存在するsector33コードから定義する。
-- 存在しないコードを並べても空テーマが増えるだけなので、
-- 現ユニバースに実際に銘柄があるものに限定。
insert into themes (key, name_ja, kind, horizon, description, definition, sort_order) values
  ('semiconductor', '半導体・電機', 'sector', 'both',
   '電気機器。値動きが大きく日計り〜スイング両方に向く',
   '{"sector33": ["3650", "3750"]}', 10),
  ('telecom', '情報通信', 'sector', 'swing',
   '通信。ディフェンシブでトレンドが継続しやすい',
   '{"sector33": ["5250", "9050"]}', 20),
  ('bank_insurance', '銀行・保険', 'sector', 'swing',
   '金利感応度が高く、金融政策イベントで動く',
   '{"sector33": ["7050", "7150"]}', 30),
  ('trading_house', '卸売（商社）', 'sector', 'swing',
   '商社。資源価格と為替に連動',
   '{"sector33": ["6050"]}', 40),
  ('pharma', '医薬品', 'sector', 'swing',
   '医薬品。個別材料で単独に動きやすい',
   '{"sector33": ["3250"]}', 50),
  ('auto_machinery', '自動車・機械', 'sector', 'swing',
   '輸送用機器と機械。為替感応度が高い',
   '{"sector33": ["3700", "3600"]}', 60),
  ('retail_consumer', '小売・消費', 'sector', 'swing',
   '小売と食品。内需系',
   '{"sector33": ["6100", "3050", "0050"]}', 70),

  -- ファクターテーマ（業種横断）
  ('breakout', 'ブレイクアウト', 'factor', 'swing',
   '高値圏で推移し上昇トレンドが継続している銘柄',
   '{"weights": {"dist_52w_high": 1.0, "ret_20d": 0.8, "adx_14": 0.5, "above_ma25": 0.5}}', 110),
  ('pullback', '押し目（順張り調整）', 'factor', 'swing',
   '上昇トレンド中に一時的に売られた銘柄',
   '{"weights": {"ret_20d": 1.0, "rsi_oversold": 1.0, "above_ma75": 0.6, "ret_5d_neg": 0.8}}', 120),
  ('day_reversal', 'デイ・リバーサル', 'factor', 'day',
   '直近1日の下落が大きく、値幅（ATR）も確保できる銘柄',
   '{"weights": {"ret_1d_neg": 1.2, "atr_pct": 0.8, "rsi_oversold": 0.6}}', 130),
  ('momentum', 'モメンタム', 'factor', 'swing',
   '中期の上昇が強い銘柄への順張り',
   '{"weights": {"ret_20d": 1.2, "ret_5d": 0.6, "adx_14": 0.4}}', 140),
  ('volatility_expansion', 'ボラティリティ拡大', 'factor', 'day',
   '値幅が平常より広がり、日計りの利幅を取りやすい銘柄',
   '{"weights": {"atr_pct": 1.2, "vol_20d": 0.8, "abs_ret_1d": 0.5}}', 150)
on conflict (key) do update set
  name_ja     = excluded.name_ja,
  kind        = excluded.kind,
  horizon     = excluded.horizon,
  description = excluded.description,
  definition  = excluded.definition,
  sort_order  = excluded.sort_order;
