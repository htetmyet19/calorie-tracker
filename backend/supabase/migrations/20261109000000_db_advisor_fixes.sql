-- Database advisor fixes (2026-11-09). Who can read or write what does not change.

-- 1. The limit functions only run as triggers. Triggers fire without checking
--    EXECUTE, so nobody needs to call them through /rest/v1/rpc.
revoke execute on function public.enforce_advice_limit() from public, anon, authenticated;
revoke execute on function public.enforce_routine_limit() from public, anon, authenticated;

-- 2. is_active_trainer_of runs inside RLS policies, so signed-in users must be
--    able to execute it, but it should not be an API endpoint. Move it to a
--    schema the API does not expose. Policies store the function itself, not
--    its name, so every existing policy keeps using it.
create schema if not exists private;
revoke all on schema private from public;
grant usage on schema private to authenticated;
alter function public.is_active_trainer_of(uuid) set schema private;
revoke execute on function private.is_active_trainer_of(uuid) from public, anon;
grant execute on function private.is_active_trainer_of(uuid) to authenticated;

-- 3. Evaluate auth.uid() once per query instead of once per row
--    (later migrations already use this form).
alter policy profiles_select on public.profiles
  using (id = (select auth.uid()) or private.is_active_trainer_of(id)
         or exists (select 1 from public.coaching_links l where l.trainer_id = (select auth.uid())
                    and l.client_id = profiles.id and l.status = 'requested'));
alter policy profiles_insert on public.profiles
  with check (id = (select auth.uid()) and role in ('client','trainer'));
alter policy profiles_update on public.profiles
  using (id = (select auth.uid())) with check (id = (select auth.uid()));
alter policy links_select on public.coaching_links
  using (client_id = (select auth.uid()) or trainer_id = (select auth.uid()));
alter policy meals_select on public.meals
  using (user_id = (select auth.uid()) or private.is_active_trainer_of(user_id));
alter policy meals_insert on public.meals
  with check (user_id = (select auth.uid()));
alter policy meals_delete on public.meals
  using (user_id = (select auth.uid()));

-- 4. Index the foreign keys that had none (deletes on the parent row scan these).
create index checkins_weight_log on public.checkins(weight_log_id);
create index coaching_links_trainer on public.coaching_links(trainer_id);
create index progress_photos_user on public.progress_photos(user_id);
create index push_subscriptions_user on public.push_subscriptions(user_id);
