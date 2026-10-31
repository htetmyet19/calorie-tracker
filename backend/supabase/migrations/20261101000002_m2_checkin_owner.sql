-- Same-owner integrity: a check-in's photos and weight link must belong to the caller.
drop policy checkins_insert on public.checkins;
create policy checkins_insert on public.checkins for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and (weight_log_id is null
         or exists (select 1 from public.weight_logs w
                    where w.id = weight_log_id and w.user_id = (select auth.uid())))
  );

drop policy photos_insert on public.progress_photos;
create policy photos_insert on public.progress_photos for insert to authenticated
  with check (
    user_id = (select auth.uid())
    and exists (select 1 from public.checkins c
                where c.id = checkin_id and c.user_id = (select auth.uid()))
  );

drop policy photos_update on public.progress_photos;
create policy photos_update on public.progress_photos for update to authenticated
  using (user_id = (select auth.uid()))
  with check (
    user_id = (select auth.uid())
    and exists (select 1 from public.checkins c
                where c.id = checkin_id and c.user_id = (select auth.uid()))
  );
