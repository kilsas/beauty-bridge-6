-- Beauty Bridge: "Buy" button clicks (purchase intent), for the click ranking and the user study.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Safe to run again. (setup.sql already includes this for new projects.)

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

-- Visitors can record their own clicks but cannot read anyone's raw clicks.
drop policy if exists "insert own click" on public.buy_clicks;
create policy "insert own click" on public.buy_clicks
  for insert to authenticated with check (visitor_id = auth.uid());

-- Public totals only: how many different people went to buy each product.
-- Counting people, not clicks, means one person clicking 100 times counts once.
create or replace view public.buy_click_stats as
  select product_id,
         count(distinct visitor_id)                                                   as people,
         count(distinct visitor_id) filter (where created_at > now() - interval '7 days') as people_7d,
         count(*)                                                                      as clicks
  from public.buy_clicks
  group by product_id;

grant select on public.buy_click_stats to anon, authenticated;
