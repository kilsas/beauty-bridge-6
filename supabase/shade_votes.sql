-- Beauty Bridge: "Did this shade suit you?" answers, used to check the estimated shade labels.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Safe to run again. (setup.sql already includes this for new projects.)

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
