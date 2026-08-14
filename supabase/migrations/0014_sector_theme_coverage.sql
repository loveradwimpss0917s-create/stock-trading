-- 0012の業種テーマは41銘柄しか取得できていなかった時点のsector33から
-- 定義したもので、topix500まで広げた結果196銘柄がどのテーマにも
-- 属さなくなった（化学41、陸運26、建設22…）。
--
-- 事業会社のsector33を全て覆うようテーマを追加する。業種コードは
-- 実データの社名で照合済み（3200=クラレ/旭化成、5050=東武鉄道/東急、
-- 8050=大東建託/ヒューリック 等）。
--
-- 9999（ETF/ファンド）にテーマは作らない。指数連動商品にモメンタムや
-- 押し目の概念を当てても意味がなく、スクリーニング側で除外する。
insert into themes (key, name_ja, kind, horizon, description, definition, sort_order) values
  ('chemicals_materials', '化学・素材', 'sector', 'swing',
   '化学・繊維・紙・ゴム・ガラス土石。原料価格と為替に連動する',
   '{"sector33": ["3200", "3100", "3150", "3350", "3400"]}', 80),

  ('steel_metals', '鉄鋼・非鉄・金属', 'sector', 'swing',
   '鉄鋼・非鉄金属・金属製品。市況変動が大きく循環性が強い',
   '{"sector33": ["3450", "3500", "3550"]}', 82),

  ('construction_realestate', '建設・不動産', 'sector', 'swing',
   '建設と不動産。金利と国内景気に感応する',
   '{"sector33": ["2050", "8050"]}', 84),

  ('utilities', '電力・ガス', 'sector', 'swing',
   '規制産業でディフェンシブ。燃料費と料金改定が主な変動要因',
   '{"sector33": ["4050"]}', 86),

  ('transport_logistics', '運輸・物流', 'sector', 'swing',
   '陸運・海運・空運・倉庫。海運は市況、鉄道と空運は内需と旅客数に連動',
   '{"sector33": ["5050", "5100", "5150", "5200"]}', 88),

  ('securities_finance', '証券・その他金融', 'sector', 'swing',
   '証券とリース・信販。市場出来高と与信環境に感応する',
   '{"sector33": ["7100", "7200"]}', 90),

  ('energy_resources', '資源・エネルギー', 'sector', 'swing',
   '鉱業と石油・石炭。原油価格に直結する。母集団が小さく候補も少ない',
   '{"sector33": ["1050", "3300"]}', 92),

  ('entertainment_goods', 'エンタメ・その他製品', 'sector', 'swing',
   '玩具・ゲーム・文具などその他製品。個別のヒット商品で動きやすい',
   '{"sector33": ["3800"]}', 94)
on conflict (key) do update set
  name_ja     = excluded.name_ja,
  kind        = excluded.kind,
  horizon     = excluded.horizon,
  description = excluded.description,
  definition  = excluded.definition,
  sort_order  = excluded.sort_order;
