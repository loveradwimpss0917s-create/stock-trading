-- PostgRESTのmax_rows(1000)により「全行取得してクライアント側でcount」は
-- 頭打ちになる。集計はDB側で行い、行数ではなく結果1行だけを返す。
-- security_invoker=on で、参照元テーブルのRLSがそのまま適用される
-- （＝anonから見えるのは公開ポリシーのある範囲だけ）。

create or replace view ingest_coverage
with (security_invoker = on) as
select
  (select count(*) from securities)                as securities_count,
  (select count(*) from daily_quotes)              as daily_quotes_count,
  (select count(distinct code) from daily_quotes)  as covered_codes,
  (select min(date) from daily_quotes)             as earliest_date,
  (select max(date) from daily_quotes)             as latest_date;

-- 日足が実際に入っている銘柄だけ。daily_quotesを1000行引いてコードを
-- 抽出する方式は取得件数に依存して壊れるため、DB側のexistsで絞る。
create or replace view securities_with_data
with (security_invoker = on) as
select s.code, s.ticker4, s.name_ja, s.name_en, s.market_code,
       s.sector17, s.sector33, s.scale_category
from securities s
where exists (select 1 from daily_quotes q where q.code = s.code);

grant select on ingest_coverage, securities_with_data to anon, authenticated;
