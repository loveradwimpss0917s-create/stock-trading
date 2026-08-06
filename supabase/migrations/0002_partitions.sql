create or replace function ensure_month_partition(p_month date)
returns void language plpgsql as $$
declare
  start_d date := date_trunc('month', p_month);
  end_d   date := (date_trunc('month', p_month) + interval '1 month');
  part    text := format('daily_quotes_%s', to_char(start_d,'YYYYMM'));
begin
  if not exists (select 1 from pg_class where relname = part) then
    execute format(
      'create table %I partition of daily_quotes for values from (%L) to (%L);',
      part, start_d, end_d);
    execute format('create index on %I (code);', part);
  end if;
end $$;

-- 直近26ヶ月分を一括作成
do $$
declare m date;
begin
  for m in select generate_series(date_trunc('month', now()) - interval '25 months',
                                  date_trunc('month', now()), interval '1 month')::date
  loop perform ensure_month_partition(m); end loop;
end $$;
