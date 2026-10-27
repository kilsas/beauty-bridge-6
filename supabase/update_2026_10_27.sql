-- Beauty Bridge update (2026-10-27): how did it break down? (breakdown types on noon logs)
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run. Safe to run again.
-- Needs update_2026_10_23.sql (the hold_logs table) to have been run first.

alter table public.hold_logs add column if not exists breakdown text[] not null default '{}';

alter table public.hold_logs drop constraint if exists hold_logs_breakdown_check;
alter table public.hold_logs add constraint hold_logs_breakdown_check check (
  breakdown <@ array['shine','wear_off','panda','flaking','creasing','cracking','pore_settle','texture']::text[]
  and (result <> 'held' or cardinality(breakdown) = 0)
);

-- Public totals only (no logger ids): how often each breakdown type was reported.
create or replace view public.hold_breakdown_stats as
  select product_id, climate, kind, count(*) as n
  from public.hold_logs, unnest(breakdown) as kind
  group by product_id, climate, kind;
grant select on public.hold_breakdown_stats to anon, authenticated;
