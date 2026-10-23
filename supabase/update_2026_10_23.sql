-- Beauty Bridge update (2026-10-23): "Did it hold at noon?" logs.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run. Safe to run again.

create table if not exists public.hold_logs (
  logger_id   uuid        not null default auth.uid(),
  product_id  text        not null check (char_length(product_id) between 1 and 20),
  climate     text        not null check (climate in ('hot_humid','hot_dry','temperate','cold_dry')),
  result      text        not null check (result in ('held','partly','broke')),
  day         date        not null default current_date,
  created_at  timestamptz not null default now(),
  primary key (logger_id, product_id, day)          -- one log per person per product per day
);
alter table public.hold_logs enable row level security;

drop policy if exists "read own log"   on public.hold_logs;
drop policy if exists "insert own log" on public.hold_logs;
drop policy if exists "update own log" on public.hold_logs;
drop policy if exists "delete own log" on public.hold_logs;
create policy "read own log"   on public.hold_logs for select to authenticated using (logger_id = auth.uid());
create policy "insert own log" on public.hold_logs for insert to authenticated with check (logger_id = auth.uid());
create policy "update own log" on public.hold_logs for update to authenticated using (logger_id = auth.uid()) with check (logger_id = auth.uid());
create policy "delete own log" on public.hold_logs for delete to authenticated using (logger_id = auth.uid());

-- Public totals only (no logger ids).
create or replace view public.hold_log_stats as
  select product_id, climate,
         count(*)                                    as n,
         count(*) filter (where result = 'held')     as held,
         count(*) filter (where result = 'partly')   as partly,
         count(*) filter (where result = 'broke')    as broke,
         min(day)                                    as first,
         max(day)                                    as last
  from public.hold_logs
  group by product_id, climate;
grant select on public.hold_log_stats to anon, authenticated;
grant select, insert, update, delete on public.hold_logs to authenticated;
