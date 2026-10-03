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
