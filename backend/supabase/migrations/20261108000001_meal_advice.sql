-- Meal advice: count requests (each may call the AI) for a per-user daily limit.
-- Nothing about the meal or the advice is stored, only that a request happened.

create table public.advice_requests (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now()
);
create index advice_requests_user_created on public.advice_requests(user_id, created_at desc);

create function public.enforce_advice_limit() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  -- Someone else's row: leave it to RLS (a permission error), so another user's
  -- limit status is never revealed.
  if new.user_id is distinct from (select auth.uid()) then
    return new;
  end if;
  -- Serialise one user's requests so two at once can't both see 29.
  perform pg_advisory_xact_lock(hashtext('advice_requests:' || new.user_id::text));
  if (select count(*) from public.advice_requests
      where user_id = new.user_id and created_at > now() - interval '24 hours') >= 30 then
    raise exception 'advice_limit' using errcode = 'P0001';
  end if;
  new.created_at := now();
  return new;
end $$;
revoke execute on function public.enforce_advice_limit() from public;
create trigger advice_requests_limit before insert on public.advice_requests
  for each row execute function public.enforce_advice_limit();

alter table public.advice_requests enable row level security;

-- Insert your own (the trigger stamps created_at), read your own; nothing else.
create policy advice_select on public.advice_requests for select to authenticated
  using (user_id = (select auth.uid()));
create policy advice_insert on public.advice_requests for insert to authenticated
  with check (user_id = (select auth.uid()));
revoke insert, update, delete on public.advice_requests from authenticated;
grant insert (user_id) on public.advice_requests to authenticated;

-- Same guard for routine builds (20261108000000): before it, inserting a row for
-- another user answered with that user's limit status instead of an RLS refusal.
create or replace function public.enforce_routine_limit() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.user_id is distinct from (select auth.uid()) then
    return new;
  end if;
  perform pg_advisory_xact_lock(hashtext('routine_builds:' || new.user_id::text));
  if (select count(*) from public.routine_builds
      where user_id = new.user_id and created_at > now() - interval '24 hours') >= 5 then
    raise exception 'routine_limit' using errcode = 'P0001';
  end if;
  new.created_at := now();
  return new;
end $$;
