-- Workout routines: a curated library of YouTube exercise demos, each client's
-- routines built from it, and the sessions they tick off.

create table public.exercise_videos (
  id bigint generated always as identity primary key,
  youtube_id text not null unique check (youtube_id ~ '^[A-Za-z0-9_-]{11}$'),
  title text not null check (length(title) between 1 and 120),
  channel text not null check (length(channel) between 1 and 120),
  category text not null
    check (category in ('warm_up','push','pull','legs','core','cardio','mobility')),
  level text not null check (level in ('beginner','intermediate','advanced')),
  equipment text not null check (equipment in ('none','dumbbells','gym')),
  duration_sec int not null check (duration_sec > 0),
  active boolean not null default true
);

create table public.routines (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  days_per_week smallint not null check (days_per_week between 2 and 6),
  level text not null check (level in ('beginner','intermediate','advanced')),
  equipment text not null check (equipment in ('none','dumbbells','gym')),
  session_min smallint not null check (session_min in (20,30,45,60)),
  goal text not null check (goal in ('lose','maintain','gain')),
  source text not null check (source in ('ai','rules')),
  fallback_reason text,
  plan jsonb not null,
  active boolean not null default true
);
create unique index routines_one_active on public.routines(user_id) where active;
create index routines_user_created on public.routines(user_id, created_at desc);

create table public.workout_sessions (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  routine_id bigint not null references public.routines(id) on delete cascade,
  day_index smallint not null check (day_index between 0 and 5),
  done_on date not null,
  created_at timestamptz not null default now(),
  unique (routine_id, day_index, done_on)
);
create index workout_sessions_user_done on public.workout_sessions(user_id, done_on);

alter table public.exercise_videos enable row level security;
alter table public.routines enable row level security;
alter table public.workout_sessions enable row level security;

-- exercise_videos: anyone signed in may read (old routines still show inactive
-- videos); only the service role (scripts/sync_videos.py) writes.
create policy videos_select on public.exercise_videos for select to authenticated
  using (true);

-- routines: owner only
create policy routines_select on public.routines for select to authenticated
  using (user_id = (select auth.uid()));
create policy routines_insert on public.routines for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy routines_update on public.routines for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy routines_delete on public.routines for delete to authenticated
  using (user_id = (select auth.uid()));

-- workout_sessions: owner only, and only on the owner's own routine
create policy sessions_select on public.workout_sessions for select to authenticated
  using (user_id = (select auth.uid()));
create policy sessions_insert on public.workout_sessions for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and exists (select 1 from public.routines r
                where r.id = routine_id and r.user_id = (select auth.uid()))
  );
create policy sessions_delete on public.workout_sessions for delete to authenticated
  using (user_id = (select auth.uid()));
