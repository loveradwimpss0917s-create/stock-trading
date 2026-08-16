-- 0020でthesisをnot nullにしたのは誤り。invalidationやexpected_rrはSetupの
-- ルールから機械的に計算されるが、thesis（仮説の言語化）は設計書PART1で
-- 「初心者との最大の差」と位置づけたユーザー入力そのもの。scan batchが
-- draft計画を作る時点ではまだ書けない。
--
-- draft状態ではNULLを許し、armed以降（ユーザーがBUY/WAIT判断を下した後）
-- は必須にする。DB制約で最終防衛線を張り、API側でも
-- decide(BUY/WAIT)時にthesis空なら400を返す（多重の防御）。
alter table trade_plans alter column thesis drop not null;

alter table trade_plans add constraint thesis_required_past_draft
  check (state = 'draft' or thesis is not null);
