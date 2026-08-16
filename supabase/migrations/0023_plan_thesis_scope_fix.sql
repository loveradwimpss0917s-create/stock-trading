-- 0022の制約は「state != draft なら thesis必須」だったが、これは広すぎる。
-- PASSは'passed'状態に遷移するがthesis（買う理由の言語化）を要求する意味が
-- ない — 却下する理由は plan_decisions.reason_code が既に必須で担っている。
-- thesisが必要なのは実際に「見張る／建てる」に進む armed 以降のみ。
alter table trade_plans drop constraint thesis_required_past_draft;

alter table trade_plans add constraint thesis_required_from_armed
  check (thesis is not null or state in ('draft', 'expired', 'invalidated', 'passed', 'discarded'));
