-- Beauty Bridge review storage on Supabase.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Then: Authentication -> Sign In / Providers -> enable "Anonymous sign-ins".

create table if not exists public.reviews (
  reviewer_id uuid        not null default auth.uid(),
  product_id  text        not null check (char_length(product_id) between 1 and 20),
  rating      smallint    not null check (rating between 1 and 5),
  skin_type   text        check (skin_type in ('oily','dry','combination','normal','sensitive')),
  age_band    text        check (age_band in ('10s','20s','30s','40s+')),
  market      text        check (market in ('KR','US','JP','CN')),
  text        text        check (char_length(text) <= 300),
  created_at  timestamptz not null default now(),
  primary key (reviewer_id, product_id)          -- one review per person per product
);

alter table public.reviews enable row level security;

-- Everyone (even signed-out visitors) can read reviews.
drop policy if exists "reviews are public" on public.reviews;
create policy "reviews are public" on public.reviews
  for select using (true);

-- Signed-in visitors (anonymous sign-in counts) can only write their own rows.
drop policy if exists "insert own review" on public.reviews;
create policy "insert own review" on public.reviews
  for insert to authenticated with check (reviewer_id = auth.uid());

drop policy if exists "update own review" on public.reviews;
create policy "update own review" on public.reviews
  for update to authenticated using (reviewer_id = auth.uid()) with check (reviewer_id = auth.uid());

drop policy if exists "delete own review" on public.reviews;
create policy "delete own review" on public.reviews
  for delete to authenticated using (reviewer_id = auth.uid());

-- Push inserts/updates/deletes to open pages so rankings change live.
do $$ begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'reviews') then
    alter publication supabase_realtime add table public.reviews;
  end if;
end $$;

-- "Buy" button clicks (purchase intent): same as supabase/buy_clicks.sql.
create table if not exists public.buy_clicks (
  id          bigint generated always as identity primary key,
  visitor_id  uuid        not null default auth.uid(),
  product_id  text        not null check (char_length(product_id) between 1 and 20),
  store       text        not null check (char_length(store) between 1 and 40),
  market      text        check (market in ('KR','US','JP','CN')),
  created_at  timestamptz not null default now()
);
create index if not exists buy_clicks_product_idx on public.buy_clicks (product_id);
alter table public.buy_clicks enable row level security;
drop policy if exists "insert own click" on public.buy_clicks;
create policy "insert own click" on public.buy_clicks
  for insert to authenticated with check (visitor_id = auth.uid());
create or replace view public.buy_click_stats as
  select product_id,
         count(distinct visitor_id)                                                   as people,
         count(distinct visitor_id) filter (where created_at > now() - interval '7 days') as people_7d,
         count(*)                                                                      as clicks
  from public.buy_clicks
  group by product_id;
grant select on public.buy_click_stats to anon, authenticated;

-- "Did this shade suit you?" answers: same as supabase/shade_votes.sql.
create table if not exists public.shade_votes (
  voter_id    uuid        not null default auth.uid(),
  product_id  text        not null check (char_length(product_id) between 1 and 20),
  shade       text        not null check (char_length(shade) between 1 and 80),
  pc_type     text        not null check (pc_type in ('spring_light','spring_bright','summer_light','summer_mute',
                                                      'autumn_mute','autumn_deep','winter_bright','winter_deep')),
  verdict     text        not null check (verdict in ('suits','okay','not')),
  created_at  timestamptz not null default now(),
  primary key (voter_id, product_id, shade)          -- one answer per person per shade
);

alter table public.shade_votes enable row level security;

-- People can see, add, change and delete only their own answers.
drop policy if exists "read own vote"   on public.shade_votes;
drop policy if exists "insert own vote" on public.shade_votes;
drop policy if exists "update own vote" on public.shade_votes;
drop policy if exists "delete own vote" on public.shade_votes;
create policy "read own vote"   on public.shade_votes for select to authenticated using (voter_id = auth.uid());
create policy "insert own vote" on public.shade_votes for insert to authenticated with check (voter_id = auth.uid());
create policy "update own vote" on public.shade_votes for update to authenticated using (voter_id = auth.uid()) with check (voter_id = auth.uid());
create policy "delete own vote" on public.shade_votes for delete to authenticated using (voter_id = auth.uid());

-- Public totals only (no voter ids).
create or replace view public.shade_vote_stats as
  select product_id, shade, pc_type,
         count(*)                                   as n,
         count(*) filter (where verdict = 'suits')  as suits,
         count(*) filter (where verdict = 'okay')   as okay,
         count(*) filter (where verdict = 'not')    as "not"
  from public.shade_votes
  group by product_id, shade, pc_type;

grant select on public.shade_vote_stats to anon, authenticated;
grant select, insert, update, delete on public.shade_votes to authenticated;

-- 2026-10-18 update: same as supabase/update_2026_10_18.sql.
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

-- 2026-10-20 update: same as supabase/update_2026_10_20.sql.
-- 1) Allow Singapore as the country a product was bought / used in
alter table public.reviews drop constraint if exists reviews_market_check;
alter table public.reviews add constraint reviews_market_check
  check (market is null or market in ('KR','US','JP','CN','SG'));

-- 2) Optional climate the reviewer used the product in
alter table public.reviews add column if not exists climate text;
alter table public.reviews drop constraint if exists reviews_climate_check;
alter table public.reviews add constraint reviews_climate_check
  check (climate is null or climate in ('hot_humid','hot_dry','temperate','cold_dry'));

-- 2026-10-20 update, part 3 (skin depth): also in supabase/update_2026_10_20.sql.
alter table public.reviews add column if not exists skin_depth text;
alter table public.reviews drop constraint if exists reviews_skin_depth_check;
alter table public.reviews add constraint reviews_skin_depth_check
  check (skin_depth is null or skin_depth in ('fair','light','medium','tan','deep'));

-- 2026-10-23 update: same as supabase/update_2026_10_23.sql.
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
