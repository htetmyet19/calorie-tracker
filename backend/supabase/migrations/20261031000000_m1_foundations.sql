create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('client','trainer','admin')),
  display_name text not null default '' check (char_length(display_name) <= 80),
  created_at timestamptz not null default now()
);
create table public.coaching_links (
  id bigint generated always as identity primary key,
  client_id uuid not null references public.profiles(id) on delete cascade,
  trainer_id uuid not null references public.profiles(id) on delete cascade,
  status text not null check (status in ('requested','active','declined','ended')),
  requested_at timestamptz not null default now(),
  responded_at timestamptz, ended_at timestamptz, ended_by uuid
);
create unique index one_open_link_per_client on public.coaching_links(client_id)
  where status in ('requested','active');
create table public.meals (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  eaten_at timestamp not null,          -- user's local time, as today
  meal_type text not null check (meal_type in ('breakfast','lunch','dinner','snack')),
  items jsonb not null,
  total_calories real not null
);
create index meals_user_eaten on public.meals(user_id, eaten_at);

create function public.is_active_trainer_of(client uuid) returns boolean
  language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.coaching_links
    where client_id = client and trainer_id = auth.uid() and status = 'active') $$;

alter table public.profiles enable row level security;
alter table public.coaching_links enable row level security;
alter table public.meals enable row level security;

create policy profiles_select on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_active_trainer_of(id)
         or exists (select 1 from public.coaching_links l where l.trainer_id = auth.uid()
                    and l.client_id = profiles.id and l.status = 'requested'));
create policy profiles_insert on public.profiles for insert to authenticated
  with check (id = auth.uid() and role in ('client','trainer'));
revoke update on public.profiles from authenticated;
grant update (display_name) on public.profiles to authenticated;
create policy profiles_update on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

create policy links_select on public.coaching_links for select to authenticated
  using (client_id = auth.uid() or trainer_id = auth.uid());
-- no write policies in M1 (requests arrive in M3)

create policy meals_select on public.meals for select to authenticated
  using (user_id = auth.uid() or public.is_active_trainer_of(user_id));
create policy meals_insert on public.meals for insert to authenticated with check (user_id = auth.uid());
create policy meals_delete on public.meals for delete to authenticated using (user_id = auth.uid());
-- no update policy: meals are not edited in place today
