-- M2: client settings, weight logs, check-ins, progress photos, push, private photo buckets.

create table public.client_settings (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  height_cm real,
  weight_kg numeric(6,2),
  age smallint,
  sex text check (sex in ('male','female','unspecified')),
  activity numeric(4,3) check (activity in (1.2,1.375,1.55,1.725,1.9)),
  weight_goal text check (weight_goal in ('lose','maintain','gain')),
  goal_kcal integer check (goal_kcal between 500 and 9000),
  goal_set_by uuid,
  weight_unit text not null default 'kg' check (weight_unit in ('kg','lb')),
  reminders_enabled boolean not null default false,
  reminders_sent smallint not null default 0,
  last_reminded_on date,
  updated_at timestamptz not null default now()
);

create table public.weight_logs (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  logged_on date not null,
  weight_kg numeric(6,2) not null check (weight_kg between 30 and 300),
  unique (user_id, logged_on)
);

create table public.checkins (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  checked_on date not null,
  weight_log_id bigint references public.weight_logs(id) on delete set null,
  created_at timestamptz not null default now()
);
create index checkins_user_checked on public.checkins(user_id, checked_on desc);

create table public.progress_photos (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  checkin_id bigint not null references public.checkins(id) on delete cascade,
  pose text not null check (pose in ('front','side','back')),
  photo_path text not null,
  created_at timestamptz not null default now(),
  unique (checkin_id, pose)
);

alter table public.meals add column photo_path text;

create table public.push_subscriptions (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);

create table public.deletion_failures (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('storage')),
  ref text not null unique,
  attempts int not null default 1,
  last_error text not null,
  created_at timestamptz not null default now()
);

alter table public.client_settings enable row level security;
alter table public.weight_logs enable row level security;
alter table public.checkins enable row level security;
alter table public.progress_photos enable row level security;
alter table public.push_subscriptions enable row level security;
alter table public.deletion_failures enable row level security;  -- no policies: service role only

-- client_settings
create policy settings_select on public.client_settings for select to authenticated
  using (user_id = (select auth.uid()) or public.is_active_trainer_of(user_id));
create policy settings_insert on public.client_settings for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy settings_update on public.client_settings for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- weight_logs
create policy weights_select on public.weight_logs for select to authenticated
  using (user_id = (select auth.uid()) or public.is_active_trainer_of(user_id));
create policy weights_insert on public.weight_logs for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy weights_update on public.weight_logs for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy weights_delete on public.weight_logs for delete to authenticated
  using (user_id = (select auth.uid()));

-- checkins
create policy checkins_select on public.checkins for select to authenticated
  using (user_id = (select auth.uid()) or public.is_active_trainer_of(user_id));
create policy checkins_insert on public.checkins for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy checkins_delete on public.checkins for delete to authenticated
  using (user_id = (select auth.uid()));

-- progress_photos (update is needed for the retry-replace path)
create policy photos_select on public.progress_photos for select to authenticated
  using (user_id = (select auth.uid()) or public.is_active_trainer_of(user_id));
create policy photos_insert on public.progress_photos for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy photos_update on public.progress_photos for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy photos_delete on public.progress_photos for delete to authenticated
  using (user_id = (select auth.uid()));

-- meals: owner may only set photo_path
revoke update on public.meals from authenticated;
grant update (photo_path) on public.meals to authenticated;
create policy meals_update on public.meals for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- push_subscriptions: owner only, never trainers
create policy push_select on public.push_subscriptions for select to authenticated
  using (user_id = (select auth.uid()));
create policy push_insert on public.push_subscriptions for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy push_delete on public.push_subscriptions for delete to authenticated
  using (user_id = (select auth.uid()));

-- private buckets
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types) values
  ('meal-photos', 'meal-photos', false, 307200, array['image/jpeg','image/png','image/webp']),
  ('progress-photos', 'progress-photos', false, 2097152, array['image/jpeg','image/png','image/webp']);

create policy photos_objects_insert on storage.objects for insert to authenticated
  with check (bucket_id in ('meal-photos','progress-photos')
    and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy photos_objects_select on storage.objects for select to authenticated
  using (bucket_id in ('meal-photos','progress-photos')
    and ((storage.foldername(name))[1] = (select auth.uid())::text
         or public.is_active_trainer_of(((storage.foldername(name))[1])::uuid)));
create policy photos_objects_update on storage.objects for update to authenticated
  using (bucket_id in ('meal-photos','progress-photos')
    and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id in ('meal-photos','progress-photos')
    and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy photos_objects_delete on storage.objects for delete to authenticated
  using (bucket_id in ('meal-photos','progress-photos')
    and (storage.foldername(name))[1] = (select auth.uid())::text);
