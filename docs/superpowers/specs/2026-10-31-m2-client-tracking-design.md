# M2: client tracking: design

Date: 2026-10-31
Status: implemented (M2)
Parent spec: `2026-10-31-trainer-platform-design.md` (M2 row of Section 11). Where this document is more specific, it wins; where it is silent, the parent applies.

## 1. Goal

A client gets full value alone, before any trainer exists: meals with photos, goal and calculator details saved to the account, weight log, weekly check-ins with progress photos, and a reminder when a check-in is due.

Done when:
- A client logs a meal with a photo on one phone and sees it (thumbnail and full size) on another.
- Calculator details and goal survive a new device; existing browser values are moved to the account once.
- A client logs weight in kg or lb, completes a weekly check-in (weight + front/side/back, any photo skippable) and compares two check-ins side by side.
- A client who allowed notifications receives "Weekly check-in due" on an Android phone.
- Meal photos older than 90 days are removed by the daily job; meal data stays.
- No user can read another user's settings, weights, check-ins or photos, proven at API, database and storage level.

Out of scope for M2: trainer access (M3/M4, but RLS is written ready for it), editing a saved meal's photo, email or Viber reminders, iPhone push without home-screen install.

## 2. Decisions

| Topic | Decision |
|---|---|
| Weight unit | Stored in kg. Shown in kg or lb per user (`client_settings.weight_unit`), default kg |
| Weight range | 30–300 kg (66–661 lb). One entry per day; a second entry that day replaces the first |
| Check-in | Weekly: weight + front, side, back photos, each photo skippable. Due when the latest check-in is 7+ days old (or none exists) |
| Reminder | Web push only (Chrome on Android). Asked for after the first completed check-in, never on page load. Toggle in Settings |
| Reminder rule | At most 2 per due check-in: on the due day, and again 3 days later if still not done |
| Meal photo retention | Photo deleted 90 days after the meal; meal row kept, `photo_path` set to null |
| Progress photo retention | Kept until the user deletes it |
| Daily job | Vercel Cron, 02:30 UTC (09:00 Myanmar), `GET /api/cron/daily` with `Authorization: Bearer $CRON_SECRET` |
| Privileged access | Service-role key used only by `app/cron.py`; a test fails if any other module imports it |
| Approach | FastAPI does all access checks (parent spec Section 5); no Supabase Edge Functions or pg_cron |

## 3. Data model (migration `…_m2_client_tracking.sql`)

```
client_settings     user_id PK → profiles, height_cm, weight_kg, age, sex, activity,
                    weight_goal ('lose'|'maintain'|'gain'), goal_kcal, goal_set_by uuid,
                    weight_unit ('kg'|'lb') default 'kg',
                    reminders_enabled bool default false,
                    reminders_sent smallint default 0, last_reminded_on date,
                    updated_at
weight_logs         id, user_id, logged_on date, weight_kg numeric(5,1)
                    UNIQUE (user_id, logged_on)
checkins            id, user_id, checked_on date, weight_log_id → weight_logs (nullable), created_at
progress_photos     id, user_id, checkin_id → checkins, pose ('front'|'side'|'back'),
                    photo_path, created_at   UNIQUE (checkin_id, pose)
meals               + photo_path text null
push_subscriptions  id, user_id, endpoint text UNIQUE, p256dh, auth, created_at
deletion_failures   id, kind ('storage'), ref, attempts, last_error, created_at   (from parent spec)
```

Notes:
- `checkins` is its own table (refining the in-chat design) so a check-in with every photo skipped still counts and resets the reminder.
- Saving a weight also sets `client_settings.weight_kg`, so the calculator uses the latest weight.
- Recording a check-in resets `reminders_sent` to 0.
- Dates (`logged_on`, `checked_on`) are the user's local date sent by the browser; the daily job computes "today" in `Asia/Yangon`.

Storage buckets (private): `meal-photos`, `progress-photos`. Object path `<user_id>/<uuid>.jpg`.

RLS, same pattern as M1:
- Owner: select/insert/delete own rows; update own `client_settings`, `weight_logs`; no update on photos or check-ins.
- Active trainer: select on `client_settings`, `weight_logs`, `checkins`, `progress_photos`, and storage objects in the client's folder, via `is_active_trainer_of`. Unused until M3, tested now.
- `push_subscriptions` and the reminder columns: owner only, never trainers.
- `deletion_failures`: no policies (service role only).
- Storage `storage.objects`: insert/select/delete where the first path segment equals `auth.uid()`; select also for the active trainer.

## 4. API

All routes require login and a profile (M1 rules). Another user's IDs return 404.

| Route | Purpose |
|---|---|
| `GET /api/settings`, `PUT /api/settings` | Calculator details, goal, weight unit, reminders flag |
| `PUT /api/meals/{id}/photo` | Upload the small meal photo (≤ 300 KB JPEG) after the meal is saved; also used by "retry" |
| `GET /api/meals/{id}/photo` | Redirect to a 5-minute signed URL |
| `GET /api/weights?from=&to=`, `PUT /api/weights/{date}`, `DELETE /api/weights/{date}` | Weight log |
| `POST /api/checkins` | Create a check-in (date, optional weight) → returns id |
| `POST /api/checkins/{id}/photos/upload-url` | Body `{pose}` → signed upload URL for a server-chosen path |
| `POST /api/checkins/{id}/photos` | Body `{pose, path}` → records the photo after verifying the path is the caller's and the object exists |
| `GET /api/checkins` | Check-ins with signed thumbnail URLs, plus `next_due_on` |
| `DELETE /api/progress-photos/{id}` | Delete row and storage object |
| `POST /api/push/subscribe`, `DELETE /api/push/subscribe` | Save or remove the browser's push subscription |
| `GET /api/push/public-key` | VAPID public key |
| `GET /api/cron/daily` | Daily job (Section 6) |

Meal photo flow (refines the in-chat "stored from /api/analyze"): `/api/analyze` receives the ~1600 px image for analysis only. After `POST /api/meals` succeeds, the browser uploads a ~800 px, ~100 KB copy to `PUT /api/meals/{id}/photo`. Reason: the meal ID does not exist at analysis time, and the meal must save even when the photo cannot.

## 5. Screens

Bottom bar: **Today**, **Progress**. Header **Settings** button opens a panel: weight unit, weekly reminders on/off (with blocked-permission help), Log out.

**Today:** as now, plus:
- browser resize before analysis (longest side 1600 px, JPEG 0.85) and a stored copy (800 px, JPEG 0.7);
- meal row thumbnail, full-size view on tap;
- "Photo not uploaded – retry" when the photo upload failed (kept in memory until the page is closed);
- "Photo removed after 90 days" when `photo_path` is null for a meal older than 90 days;
- goal and calculator read from `/api/settings`; on first load, `localStorage` `profile` and `goal` are sent with `PUT /api/settings` once if the server has none, then removed.

**Progress** (top to bottom): check-in card ("Weekly check-in due" + Start, or "Next check-in in N days"); weight chart, last 12 weeks, in the chosen unit, latest value and change since first entry, "+ Log weight"; calories vs goal, last 7 days as bars with a goal line; check-in timeline with front/side/back thumbnails, "Compare" two dates by pose; "Visible only to you".

**Check-in flow:** Weight → Front → Side → Back → Done, one step per screen, Skip on photo steps, tip "Same spot, same light, every week". A failed photo shows "Not uploaded – retry" without losing the rest. On the first Done only: "Remind me next week?"; Yes triggers the browser permission prompt and `POST /api/push/subscribe`.

Errors under fields use the login page style (inline message, red border). Figma wireframes 03 and 04 are updated to match before building the screens.

## 6. Daily job

`GET /api/cron/daily`, 401 without the correct `CRON_SECRET`. Runs in batches of 100 and stops before 50 s, leaving the rest for the next day.

1. **Reminders.** For each user with `reminders_enabled` and at least one push subscription, where the check-in is due today (Asia/Yangon):
   - send if `reminders_sent = 0`, or `reminders_sent = 1` and today ≥ `last_reminded_on + 3`;
   - payload `{"title":"Weekly check-in due","url":"/progress"}`, no health data;
   - on success increment `reminders_sent`, set `last_reminded_on`; a 404/410 from the push service deletes that subscription.
2. **Photo cleanup.** Meals with `photo_path` not null and `eaten_at` older than 90 days: delete the storage object, then set `photo_path` null. Failures go to `deletion_failures`; earlier failures are retried first.

`vercel.json` gains `"crons": [{"path": "/api/cron/daily", "schedule": "30 2 * * *"}]`. New environment variables: `CRON_SECRET`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (a `mailto:` address), and `SUPABASE_SERVICE_ROLE_KEY` now also on Vercel. Library: `pywebpush`.

## 7. Error handling

- Photo upload failure never blocks saving the meal or the rest of a check-in.
- Signed URLs expire after 5 minutes; the page requests fresh ones when it reloads.
- Push permission denied: Settings shows "Notifications are blocked. In Chrome: ⋮ → Settings → Site settings → Notifications".
- Upload size: meal photo upload rejects over 300 KB (413); progress photo signed uploads are limited by bucket setting to 2 MB and image types.
- Logs carry IDs and error types only, never weights, photos or meal contents (parent spec Section 9).

## 8. Testing

- Unit (pytest): settings validation, kg/lb conversion and ranges, `next_due_on`, reminder rule (0, 1, 2 sent; 3-day gap), cron secret check, service-role import guard, path ownership check for recorded photos.
- Unit (node): resize dimension calculation, unit formatting, check-in due label.
- Integration (local Supabase): RLS for every new table and both buckets (owner yes, other user no, active trainer read, ended trainer no); check-in with one failed photo; 90-day cleanup removes only old photos and records failures; weight upsert replaces same-day entry.
- Push: `pywebpush.webpush` replaced with a fake that records calls and can return 410.
- Manual (user): a real notification on an Android phone; resize quality on a real phone photo.

## 9. Parent spec changes

- Section 1 non-goals: "Real-time push" becomes "Real-time push (weekly check-in reminders by web push are in scope from M2)".
- Section 4: add `checkins`, `push_subscriptions`, reminder and unit columns; `meals.photo_path` nullable after 90 days.
- Section 8: add the daily reminder job.
- Section 12: the service-role key is on Vercel, used only by the daily job.
