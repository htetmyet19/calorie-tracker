-- photo paths must live in the row owner's storage folder and contain no '..' segments
alter table public.meals add constraint meals_photo_path_owner
  check (photo_path is null
         or (photo_path like user_id::text || '/%' and position('..' in photo_path) = 0));
alter table public.progress_photos add constraint progress_photos_path_owner
  check (photo_path like user_id::text || '/%' and position('..' in photo_path) = 0);
