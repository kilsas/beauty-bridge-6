-- Beauty Bridge update (2026-10-20): Singapore + "climate where you used it" on reviews.
-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run. Safe to run again.

-- 1) Allow Singapore as the country a product was bought / used in
alter table public.reviews drop constraint if exists reviews_market_check;
alter table public.reviews add constraint reviews_market_check
  check (market is null or market in ('KR','US','JP','CN','SG'));

-- 2) Optional climate the reviewer used the product in
alter table public.reviews add column if not exists climate text;
alter table public.reviews drop constraint if exists reviews_climate_check;
alter table public.reviews add constraint reviews_climate_check
  check (climate is null or climate in ('hot_humid','hot_dry','temperate','cold_dry'));
