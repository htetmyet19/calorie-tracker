-- Set by the daily job when it removes a meal photo after 90 days, so the app can
-- tell "photo removed" from "never had a photo". Not granted to authenticated:
-- only the service role (daily job) writes it.
alter table public.meals add column photo_removed boolean not null default false;
