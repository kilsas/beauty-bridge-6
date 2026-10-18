-- Beauty Bridge update (2026-10-18): skin type on shade answers + "wrong category" reports.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run. Safe to run again.
-- (Needs supabase/shade_votes.sql to have been run before. setup.sql already includes everything.)

-- 1) Optional skin type on "did this shade suit you?" answers
alter table public.shade_votes add column if not exists skin_type text
  check (skin_type is null or skin_type in ('oily','dry','combination','normal','sensitive'));

drop view if exists public.shade_vote_stats;
create view public.shade_vote_stats as
  select product_id, shade, pc_type, skin_type,
         count(*)                                   as n,
         count(*) filter (where verdict = 'suits')  as suits,
         count(*) filter (where verdict = 'okay')   as okay,
         count(*) filter (where verdict = 'not')    as "not"
  from public.shade_votes
  group by product_id, shade, pc_type, skin_type;
grant select on public.shade_vote_stats to anon, authenticated;

-- 2) "This product belongs in another category" (one suggestion per person per product)
create table if not exists public.category_reports (
  reporter_id uuid        not null default auth.uid(),
  product_id  text        not null check (char_length(product_id) between 1 and 20),
  suggested   text        not null check (char_length(suggested) between 1 and 40),
  note        text        check (note is null or char_length(note) <= 200),
  created_at  timestamptz not null default now(),
  primary key (reporter_id, product_id)
);
alter table public.category_reports enable row level security;

drop policy if exists "read own report"   on public.category_reports;
drop policy if exists "insert own report" on public.category_reports;
drop policy if exists "update own report" on public.category_reports;
drop policy if exists "delete own report" on public.category_reports;
create policy "read own report"   on public.category_reports for select to authenticated using (reporter_id = auth.uid());
create policy "insert own report" on public.category_reports for insert to authenticated with check (reporter_id = auth.uid());
create policy "update own report" on public.category_reports for update to authenticated using (reporter_id = auth.uid()) with check (reporter_id = auth.uid());
create policy "delete own report" on public.category_reports for delete to authenticated using (reporter_id = auth.uid());

-- Public totals only (no reporter ids, no notes).
create or replace view public.category_report_stats as
  select product_id, suggested, count(*) as n
  from public.category_reports
  group by product_id, suggested;
grant select on public.category_report_stats to anon, authenticated;
grant select, insert, update, delete on public.category_reports to authenticated;
