# M2 Client Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client, alone, logs meals with photos, keeps goal and calculator details in their account, logs weight in kg or lb, completes weekly check-ins with progress photos, and gets a web push reminder when a check-in is due; meal photos are removed after 90 days.

**Architecture:** One new migration adds the tables, RLS and two private storage buckets. FastAPI keeps acting as the logged-in user (PostgREST and Storage with the user's JWT); a new `app/storage.py` wraps Supabase Storage the same way `app/store.py` wraps PostgREST. Only `app/cron.py` uses the service-role key, for the daily Vercel Cron job (reminders + photo cleanup). The browser gains `progress.html`, a bottom bar, a settings panel, a check-in flow and a service worker for push.

**Tech Stack:** existing FastAPI 0.143 / httpx 0.28 / PyJWT / pytest 8.3.4; new `pywebpush==2.0.3`; Supabase Storage REST API; Vercel Cron; plain HTML/CSS/JS with inline SVG charts (no chart library).

**Spec:** `docs/superpowers/specs/2026-10-31-m2-client-tracking-design.md` (all sections); parent `docs/superpowers/specs/2026-10-31-trainer-platform-design.md` Sections 5, 9, 12.

## Global Constraints

- Requests for another user's rows or files return **404**, never 403. A PostgREST PATCH/DELETE denied by RLS returns 200 with an empty body: treat "no row returned" as not found.
- Every new store query filters `user_id = <caller>` explicitly (RLS also exposes active trainers' clients).
- New RLS policies use `(select auth.uid())`, not bare `auth.uid()` (M1 deferred perf item).
- The service-role key is read only in `app/config.py`, `app/cron.py`, `scripts/` and `tests/integration/`. A unit test enforces this for `app/`.
- Logs carry IDs and error types only: never weights, photos, meal contents, push endpoints or keys.
- Signed URLs for reading photos expire after **300 seconds**.
- Weight range **30–300 kg**; shown as **66–661 lb**; `1 lb = 0.45359237 kg`. Stored as `numeric(6,2)` kg (refines spec's `numeric(5,1)` so lb values round-trip; see Review Focus 3).
- Meal photo upload limit **300 KB**, JPEG/PNG/WebP. Progress-photo bucket limit **2 MB**, `image/jpeg`, `image/png`, `image/webp`. Meal-photo bucket limit **300 KB**.
- Browser resize: analysis copy longest side **1600 px**, JPEG quality **0.85**; stored meal copy **800 px**, quality **0.7**; progress photo **1600 px**, quality **0.8**.
- Check-in due when the latest check-in is **7+ days** old, or none exists. Reminders: at most **2** per due check-in, second **3 days** after the first. "Today" for the cron job is computed in **`Asia/Yangon`**.
- Meal photo retention **90 days** from `eaten_at`.
- Cron: `GET /api/cron/daily`, schedule `30 2 * * *`, header `Authorization: Bearer <CRON_SECRET>`; batches of **100**, stop starting new work after **50 s**.
- Push payload exactly `{"title":"Weekly check-in due","url":"/progress.html"}` (the spec's `/progress` becomes `/progress.html`: static pages, no router).
- English copy. Plain HTML/CSS/JS, no build step; reuse `styles.css` tokens and the `$()` helper. App pages keep the existing light/dark theme (only login/sign-up are always dark).
- Python 3.10-compatible syntax. Docker commands in this session go through `sg docker -c "..."`.
- Integration tests: `cd backend && sg docker -c ".venv/bin/pytest -m integration -q"`; unit: `.venv/bin/pytest -q`; JS: `node --test "tests/*.test.js"`.

## Review Focus

1. **Retrying a photo that partly succeeded.** Recording the same pose twice in one check-in (retry after a timeout) must replace the first photo and delete its old file, not fail on the unique index. Test in Task 5.
2. **Deleting a meal that has a photo** must also delete the stored file, so no orphan health photo outlives its meal. Test in Task 4.
3. **lb round-trip.** Every lb value 66.0–661.0 in 0.1 steps, saved and shown again, must display the same number the user typed. Test in Task 8 (JS) with the `numeric(6,2)` column from Task 1.
4. **Two devices migrating old browser settings.** The one-time `localStorage` move must never overwrite settings already on the server. Test in Task 2 (`PUT /api/settings?only_if_empty=1` returns 409 when a row exists).
5. **Midnight in Myanmar.** A check-in done at 23:30 Yangon time on day D, and the cron job at 02:30 UTC on day D+7 (09:00 Yangon), must treat the check-in as due that day. Test in Task 6 using Yangon dates.

---

### Task 1: Migration — tables, RLS, buckets

**Files:**
- Create: `backend/supabase/migrations/20261101000000_m2_client_tracking.sql`
- Create: `backend/tests/integration/test_rls_m2.py`
- Modify: `backend/tests/integration/conftest.py` (fixtures `storage`, `upload_object`)

**Interfaces:**
- Produces tables exactly as spec Section 3, with these concrete choices:
  - `client_settings(user_id uuid pk → profiles on delete cascade, height_cm real, weight_kg numeric(6,2), age smallint, sex text check in ('male','female','unspecified'), activity real check in (1.2,1.375,1.55,1.725,1.9), weight_goal text check in ('lose','maintain','gain'), goal_kcal integer check between 500 and 9000, goal_set_by uuid, weight_unit text not null default 'kg' check in ('kg','lb'), reminders_enabled boolean not null default false, reminders_sent smallint not null default 0, last_reminded_on date, updated_at timestamptz not null default now())`; all body fields nullable.
  - `weight_logs(id bigint identity pk, user_id, logged_on date, weight_kg numeric(6,2) not null check between 30 and 300, unique(user_id, logged_on))`.
  - `checkins(id bigint identity pk, user_id, checked_on date not null, weight_log_id bigint → weight_logs on delete set null, created_at)`; index `(user_id, checked_on desc)`.
  - `progress_photos(id bigint identity pk, user_id, checkin_id → checkins on delete cascade, pose text check in ('front','side','back'), photo_path text not null, created_at, unique(checkin_id, pose))`.
  - `meals.photo_path text` (nullable).
  - `push_subscriptions(id bigint identity pk, user_id, endpoint text not null unique, p256dh text not null, auth text not null, created_at)`.
  - `deletion_failures(id bigint identity pk, kind text check in ('storage'), ref text not null unique, attempts int not null default 1, last_error text not null, created_at)`.
- Policies (owner = `user_id = (select auth.uid())`):
  - `client_settings`: select owner or `is_active_trainer_of(user_id)`; insert/update owner.
  - `weight_logs`: select owner or active trainer; insert/update/delete owner.
  - `checkins`: select owner or active trainer; insert/delete owner.
  - `progress_photos`: select owner or active trainer; insert/update/delete owner (update needed for the retry-replace path).
  - `meals`: add update policy owner-only, and column grant so `authenticated` may update only `photo_path`.
  - `push_subscriptions`: select/insert/delete owner only.
  - `deletion_failures`: RLS on, no policies.
- Buckets inserted into `storage.buckets`: `meal-photos` (public false, `file_size_limit` 307200, mime jpeg/png/webp) and `progress-photos` (public false, 2097152, same mimes).
- `storage.objects` policies for both buckets: insert/select/update/delete when `(storage.foldername(name))[1] = (select auth.uid())::text`; select also when `public.is_active_trainer_of(((storage.foldername(name))[1])::uuid)`.
- Fixtures: `storage` → httpx client at `/storage/v1` with the service key; `upload_object(user, bucket, path, data=b"\xff\xd8\xff", content_type="image/jpeg")` → uploads as that user's token, returns status code.

- [ ] **Step 1: Write the failing tests** in `test_rls_m2.py` (mark `pytestmark = pytest.mark.integration`):
  - `test_settings_owner_only`: A upserts own settings (201); B selects A's → `[]`; B insert with `user_id=A` → 401/403.
  - `test_weight_unique_per_day`: A inserts 2026-10-31 twice without upsert → second 409.
  - `test_weight_range`: insert 29.99 → 400; 300.00 → 201.
  - `test_trainer_reads_client_tracking`: active link → trainer reads A's `client_settings`, `weight_logs`, `checkins`, `progress_photos`; `ended` link → all `[]`.
  - `test_push_subscriptions_never_visible_to_trainer`: active trainer selects A's subscriptions → `[]`.
  - `test_meal_update_only_photo_path`: owner PATCH `photo_path` → row returned; owner PATCH `total_calories` → 401/403.
  - `test_deletion_failures_hidden`: any user select → `[]` or 401/403.
  - `test_storage_own_folder_only`: A uploads `meal-photos/<A>/x.jpg` → 200; A uploads `meal-photos/<B>/x.jpg` → 400/403; B downloads A's object (authenticated GET `/object/authenticated/meal-photos/<A>/x.jpg`) → 400/404; active trainer of A downloads → 200.
  - `test_bucket_limits`: A uploads 400 KB to `meal-photos` → 413 (or 400 with size error); A uploads `text/plain` → 400/415.
- [ ] **Step 2: Run** `cd backend && sg docker -c ".venv/bin/pytest tests/integration/test_rls_m2.py -m integration -q"` — expected: FAIL (relations do not exist).
- [ ] **Step 3: Write the migration** with the tables, grants and policies above. Apply with `sg docker -c "npx --yes supabase@2 db reset"` from `backend/` (resets local data; local only).
- [ ] **Step 4: Run** the new tests and the full integration suite — expected: all pass, including M1's 26.
- [ ] **Step 5: Commit** `feat(db): M2 tables, RLS and private photo buckets`.

### Task 2: Settings API and cookie-free HTTP client

**Files:**
- Modify: `backend/app/store.py`, `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_settings.py`, `backend/tests/integration/test_store_m2.py` (create)

**Interfaces:**
- Consumes: Task 1 `client_settings`.
- Produces:
  - `schemas.SettingsIn` (all optional except as noted): `height_cm: float|None (120–230)`, `weight_kg: float|None (30–300)`, `age: int|None (18–100)`, `sex: Literal['male','female','unspecified']|None`, `activity: Literal[1.2,1.375,1.55,1.725,1.9]|None`, `weight_goal: Literal['lose','maintain','gain']|None`, `goal_kcal: int|None (500–9000)`, `weight_unit: Literal['kg','lb'] = 'kg'`, `reminders_enabled: bool = False`. `SettingsOut(SettingsIn)` adds `goal_set_by: str|None`.
  - `Store.get_settings() -> dict | None`; `Store.put_settings(s: SettingsIn, only_if_empty: bool = False) -> dict` raising `store.SettingsExist` when `only_if_empty` and a row exists. `put_settings` sets `goal_set_by` to the caller when `goal_kcal` changes.
  - `GET /api/settings` → `SettingsOut` (defaults when no row: all body fields null, `weight_unit 'kg'`, `reminders_enabled false`). `PUT /api/settings[?only_if_empty=1]` → 200 `SettingsOut`; 409 `{"detail":"settings_exist"}`; 422 on out-of-range values. Both require a profile.
  - `store._client()` builds `httpx.Client(timeout=..., cookies=http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[])))` so no cookie is ever stored or replayed between users (M1 parked finding).

- [ ] **Step 1: Write failing unit tests** (`test_settings.py`, FakeStore pattern from `tests/test_api.py`): `test_get_settings_defaults`, `test_put_settings_roundtrip`, `test_put_settings_rejects_out_of_range` (height 119 → 422, goal 9050 → 422, activity 1.3 → 422), `test_put_only_if_empty_conflict` (409 `settings_exist`), `test_settings_require_profile` (409 `choose_role`), `test_http_client_stores_no_cookies` (build `_client()`, call `client.cookies.extract_cookies` via a fake response with `Set-Cookie`, assert `len(client.cookies) == 0`).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_settings.py -q` — expected: FAIL.
- [ ] **Step 3: Implement** schemas, store methods (PostgREST upsert: `POST /client_settings?on_conflict=user_id` with `Prefer: resolution=merge-duplicates,return=representation`; `only_if_empty` uses plain insert and maps 409 to `SettingsExist`), routes, cookie policy.
- [ ] **Step 4: Integration test** `test_store_m2.py::test_settings_upsert_and_only_if_empty` (real store as user A: put, put again updates, `only_if_empty` raises). Run unit + integration — expected: pass.
- [ ] **Step 5: Commit** `feat(api): account settings with one-time migration guard; drop cookies in Supabase client`.

### Task 3: Weight log API

**Files:**
- Modify: `backend/app/store.py`, `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_weights.py`, `backend/tests/integration/test_store_m2.py`

**Interfaces:**
- Consumes: Task 2 `Store.put_settings` semantics (only `weight_kg` changes).
- Produces:
  - `schemas.WeightIn(weight_kg: float 30–300)`; `WeightOut(logged_on: str, weight_kg: float)`.
  - `Store.weights_between(start: date, end: date) -> list[WeightOut]` (ascending, inclusive); `Store.upsert_weight(day: date, kg: float) -> WeightOut` (upsert on `user_id,logged_on`, then sets `client_settings.weight_kg` via upsert of that one column); `Store.delete_weight(day: date) -> bool`.
  - `GET /api/weights?from=YYYY-MM-DD&to=YYYY-MM-DD` (both required, `to - from ≤ 400 days`), `PUT /api/weights/{date}` body `WeightIn` → 200, `DELETE /api/weights/{date}` → 204 / 404.
  - Shared helper `main.parse_day(value: str, field: str) -> date` (the existing `DATE_RE` + `fromisoformat` check, now reused by meals, weights, check-ins) → 400 `"<field> must be a real YYYY-MM-DD date"`.

- [ ] **Step 1: Failing unit tests:** `test_put_weight_roundtrip`, `test_weight_out_of_range_422` (29.9, 300.1), `test_weights_bad_dates_400` (`2026-02-30`, `from > to`, span 401 days), `test_delete_missing_weight_404`, `test_meals_date_still_validated` (existing behaviour through `parse_day`).
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.** Store `weight_kg` rounded to 2 decimals.
- [ ] **Step 4: Integration:** `test_weight_upsert_replaces_same_day_and_updates_settings` (put 70.0 then 71.25 same day → one row 71.25; `get_settings()['weight_kg'] == 71.25`). Run all — expected: pass.
- [ ] **Step 5: Commit** `feat(api): weight log`.

### Task 4: Storage wrapper and meal photos

**Files:**
- Create: `backend/app/storage.py`
- Modify: `backend/app/store.py`, `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_storage.py`, `backend/tests/test_meal_photos.py`, `backend/tests/integration/test_storage_live.py`

**Interfaces:**
- Produces:
  - `storage.Storage(user)` using the same pooled client as `store` (import `store._client`), raising `store.StoreUnavailable` on network/5xx:
    - `upload(bucket: str, path: str, data: bytes, content_type: str, upsert: bool = False) -> None` (raises `storage.UploadRejected(status)` on 4xx)
    - `signed_url(bucket: str, path: str, expires: int = 300) -> str` (absolute URL)
    - `signed_upload_url(bucket: str, path: str) -> str` (absolute URL the browser PUTs to)
    - `exists(bucket: str, path: str) -> bool`
    - `remove(bucket: str, paths: list[str]) -> None`
    - `new_path(user_id: str) -> str` → `f"{user_id}/{uuid4().hex}.jpg"` (module function)
  - `MealOut` gains `has_photo: bool` (default False); store `_to_meal` maps `photo_path is not None`.
  - `Store.meal_photo_path(meal_id) -> str | None | Literal[False]` (False = meal not found/not owner); `Store.set_meal_photo(meal_id, path) -> bool`; `Store.delete_meal` now returns the deleted row's `photo_path` via a new `Store.delete_meal_returning(meal_id) -> dict | None` used by the route.
  - `PUT /api/meals/{id}/photo` (multipart field `photo`): 404 unknown meal; 400 non-image; 413 > 300 KB; stores at `new_path`, sets `photo_path`, removes the previous object if any; 204.
  - `GET /api/meals/{id}/photo` → 307 redirect to signed URL; 404 when no meal or no photo.
  - `DELETE /api/meals/{id}` also removes the photo object; a storage failure is logged as `meal_photo_delete_failed meal_id=<id> error=<type>` and does not fail the request.

- [ ] **Step 1: Failing unit tests:** `test_storage.py` with `httpx.MockTransport`: correct URLs/headers per method (user JWT, publishable key), 5xx → `StoreUnavailable`, 4xx upload → `UploadRejected`, signed URL made absolute. `test_meal_photos.py` with fakes: `test_photo_upload_sets_path`, `test_photo_too_large_413` (300 KB + 1), `test_photo_not_image_400`, `test_photo_other_users_meal_404`, `test_photo_get_redirects_307`, `test_photo_get_none_404`, `test_reupload_removes_old_object`, `test_delete_meal_removes_photo` (Review Focus 2), `test_delete_meal_survives_storage_error`.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement** against Supabase Storage REST: `POST /storage/v1/object/{bucket}/{path}` (header `x-upsert`), `POST /object/sign/{bucket}/{path}` body `{"expiresIn":300}` → `signedURL`, `POST /object/upload/sign/{bucket}/{path}` → `url`, `HEAD /object/authenticated/{bucket}/{path}`, `DELETE /object/{bucket}` body `{"prefixes":[...]}`.
- [ ] **Step 4: Integration** `test_storage_live.py`: upload as A, signed URL downloads the same bytes, B's `exists` on A's path is False, remove then `exists` False; meal photo end to end through the API with a real token (pattern from `test_api_live.py`). Run all — expected: pass.
- [ ] **Step 5: Commit** `feat(api): private meal photos with signed links`.

### Task 5: Check-ins and progress photos API

**Files:**
- Create: `backend/app/checkin_rules.py`
- Modify: `backend/app/store.py`, `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_checkin_rules.py`, `backend/tests/test_checkins.py`, `backend/tests/integration/test_checkins_live.py`

**Interfaces:**
- Consumes: Task 3 `upsert_weight`, Task 4 `Storage`, `new_path`.
- Produces:
  - `checkin_rules.CHECKIN_DAYS = 7`; `next_due_on(last: date | None, today: date) -> date` (`today` when `last` is None, else `last + 7 days`); `is_due(last, today) -> bool`.
  - Schemas: `CheckinIn(checked_on: str YYYY-MM-DD, weight_kg: float|None 30–300)`; `PhotoUploadIn(pose: Literal['front','side','back'])`; `PhotoRecordIn(pose, path: str)`; `PhotoOut(id: int, pose, url: str)`; `CheckinOut(id: int, checked_on: str, weight_kg: float|None, photos: list[PhotoOut])`; `CheckinList(checkins: list[CheckinOut], next_due_on: str, due: bool)`.
  - `POST /api/checkins` → 201 `CheckinOut` (empty photos). With a weight it calls `upsert_weight` and links `weight_log_id`. Resets `client_settings.reminders_sent` to 0.
  - `POST /api/checkins/{id}/photos/upload-url` body `PhotoUploadIn` → `{"upload_url": str, "path": str}`; 404 if check-in not the caller's.
  - `POST /api/checkins/{id}/photos` body `PhotoRecordIn` → 201 `PhotoOut`; 400 when `path` does not start with `f"{user_id}/"` or contains `..`; 400 `"photo_not_uploaded"` when the object does not exist; same pose already recorded → replace row's `photo_path` and remove the old object (Review Focus 1).
  - `GET /api/checkins?limit=26` → `CheckinList`, newest first, each photo with a 300 s signed URL; `today` for `next_due_on` comes from query `today=YYYY-MM-DD` (browser local date, required).
  - `DELETE /api/progress-photos/{id}` → 204 (row + object) / 404.

- [ ] **Step 1: Failing tests:** `test_checkin_rules.py`: none → due today; last 7 days ago → due; 6 days → not due, `next_due_on` = last + 7. `test_checkins.py` (fakes): create with/without weight, weight out of range 422, upload-url for other user's check-in 404, record with foreign path 400, with `../` 400, missing object 400 `photo_not_uploaded`, re-record same pose replaces and removes old object, list returns `due`/`next_due_on`, delete photo 404 for others, create resets reminders.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Integration** `test_checkins_live.py`: full flow as A — create check-in with weight, get upload URL, PUT bytes to it with `content-type: image/jpeg`, record, list shows a signed URL that downloads; second pose skipped; B lists → no A data. Run all — expected: pass.
- [ ] **Step 5: Commit** `feat(api): weekly check-ins with progress photos`.

### Task 6: Push subscriptions, daily cron job and reminders

**Files:**
- Create: `backend/app/reminders.py`, `backend/app/cron.py`, `backend/scripts/gen_vapid.py`
- Modify: `backend/app/config.py`, `backend/app/main.py`, `backend/app/store.py`, `backend/app/schemas.py`, `backend/requirements.txt` (`pywebpush==2.0.3`), `backend/vercel.json`, `backend/.env.example`, `backend/README.md`
- Test: `backend/tests/test_reminders.py`, `backend/tests/test_cron.py`, `backend/tests/test_service_key_guard.py`, `backend/tests/integration/test_cron_live.py`

**Interfaces:**
- Consumes: `checkin_rules.is_due`, Task 1 tables.
- Produces:
  - Config: `CRON_SECRET`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (env, default `""`); `TIMEZONE = "Asia/Yangon"`.
  - `reminders.should_remind(due: bool, sent: int, last_reminded_on: date | None, today: date) -> bool` (rule in spec Section 6; `sent >= 2` → False).
  - `reminders.yangon_today(now_utc: datetime) -> date` (uses `zoneinfo`).
  - Schemas `PushSubscriptionIn(endpoint: HttpUrl (https only), keys: {p256dh: str, auth: str})`.
  - `POST /api/push/subscribe` → 201 (upsert on endpoint, owner), also sets `reminders_enabled=true`; `DELETE /api/push/subscribe` body `{endpoint}` → 204 and sets `reminders_enabled=false` when no subscriptions remain; `GET /api/push/public-key` → `{"key": VAPID_PUBLIC_KEY}` (503 when unset).
  - `cron.run_daily(now_utc: datetime, send=pywebpush.webpush, deadline_s: float = 50) -> dict` returning `{"reminded": int, "photos_removed": int, "failures": int}`; uses a service-key PostgREST + Storage client built inside `cron.py`.
  - `GET /api/cron/daily`: 401 unless `Authorization == f"Bearer {CRON_SECRET}"` and `CRON_SECRET` is non-empty (compare with `hmac.compare_digest`); returns the `run_daily` dict.
  - `vercel.json` adds `"crons": [{"path": "/api/cron/daily", "schedule": "30 2 * * *"}]`.
  - `scripts/gen_vapid.py` prints `VAPID_PUBLIC_KEY=...`/`VAPID_PRIVATE_KEY=...` lines for the user to paste into `.env` (never writes files, never runs in tests).

- [ ] **Step 1: Failing tests:**
  - `test_reminders.py`: not due → False; due & sent 0 → True; sent 1 & last 2 days ago → False; 3 days ago → True; sent 2 → False; `yangon_today(datetime(2026,11,7,2,30,tzinfo=UTC)) == date(2026,11,7)` and `yangon_today(datetime(2026,11,6,18,0,tzinfo=UTC)) == date(2026,11,7)` (Review Focus 5: a check-in on 2026-10-31 Yangon is due on 2026-11-07).
  - `test_cron.py`: missing/wrong/empty-secret → 401; correct → 200 with counts (run_daily patched).
  - `test_service_key_guard.py`: scan `app/*.py`; only `config.py` and `cron.py` may contain `SUPABASE_SERVICE_ROLE_KEY`.
  - Push route unit tests: subscribe non-https endpoint 422; subscribe sets reminders_enabled; public key 503 when unset.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement** reminders, push routes, cron (reminders part: query due users in batches of 100 via service key; payload exactly as Global Constraints; 404/410 from `WebPushException.response.status_code` deletes that subscription; success increments `reminders_sent`, sets `last_reminded_on`), config, vercel.json, `.env.example` (names only), README section "Daily job and push" (how to generate keys, set `CRON_SECRET` on Vercel, service key on Vercel only for this job).
- [ ] **Step 4: Integration** `test_cron_live.py::test_reminder_sent_once_then_after_3_days` with a fake `send` that records calls: user with subscription and last check-in 7 days before → run on due day sends 1; run next day sends 0; run 3 days later sends 1; run again sends 0; fake returning 410 deletes the subscription. Run all — expected: pass.
- [ ] **Step 5: Commit** `feat: daily job with weekly check-in push reminders`.

### Task 7: 90-day meal photo cleanup

**Files:**
- Modify: `backend/app/cron.py`
- Test: `backend/tests/integration/test_cron_live.py`, `backend/tests/test_cron.py`

**Interfaces:**
- Consumes: Task 6 `run_daily` and its service client; Task 1 `deletion_failures`.
- Produces: `cron.cleanup_meal_photos(client, now_utc: datetime, deadline: float) -> tuple[int, int]` (removed, failures), called by `run_daily` after reminders. Cutoff: `eaten_at < (Yangon today − 90 days)`. Retries rows in `deletion_failures` first (delete the failure row on success, increment `attempts` and update `last_error` with the exception type on failure). Storage object removed first, then `photo_path` set null; a failure leaves `photo_path` unchanged.

- [ ] **Step 1: Failing tests:** integration `test_cleanup_removes_only_old_photos` (meals at 91 and 89 days with uploaded objects → only the 91-day object and path removed); `test_cleanup_records_and_retries_failure` (point one meal at a path whose removal is forced to fail via a patched remove → one `deletion_failures` row; next run with remove working clears it). Unit: `run_daily` stops starting batches after the deadline (fake clock).
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all** — expected: pass.
- [ ] **Step 5: Commit** `feat: remove meal photos after 90 days`.

### Task 8: Figma wireframes 03 and 04 (controller task)

Done by the controller with the Figma tools, not a code subagent. File `KK4rKfkgUHfKn8lYraFpPJ`.
- [ ] Update **03 Client Today**: bottom bar (Today / Progress), Settings button in header, meal row thumbnail, "Photo not uploaded – retry", "Photo removed after 90 days".
- [ ] Update **04 Client Progress** to spec Section 5 order: check-in card, weight chart with unit, calories vs goal (7 bars + goal line), check-in timeline, Compare.
- [ ] Add **04b Check-in flow** (Weight → Front → Side → Back → Done with "Remind me next week?") and **04c Settings panel**.
- [ ] Screenshot each, record node IDs in the ledger for Tasks 9–11.

### Task 9: Shared front-end modules, settings panel and Today changes

**Files:**
- Create: `backend/static/units.js`, `backend/static/images.js`, `backend/static/nav.js`
- Modify: `backend/static/index.html`, `backend/static/app.js`, `backend/static/styles.css`
- Test: `backend/tests/units.test.js`, `backend/tests/images.test.js`

**Interfaces:**
- Consumes: Tasks 2–4 routes; Figma 03 and 04c.
- Produces:
  - `units.js` (CommonJS guard like `energy.js`): `KG_PER_LB = 0.45359237`; `toKg(value: number, unit: 'kg'|'lb') -> number` (rounded to 2 dp); `fromKg(kg, unit) -> number` (rounded to 1 dp); `formatWeight(kg, unit) -> string` (e.g. `"68.0 kg"`, `"150.0 lb"`); `weightRange(unit) -> {min, max}` (30/300 or 66/661).
  - `images.js`: `fitWithin(w, h, maxSide) -> {width, height}` (never upscales; integers); `async resizeImage(file: Blob, maxSide: number, quality: number) -> Blob` (JPEG via `createImageBitmap(file, {imageOrientation: 'from-image'})` + canvas).
  - `nav.js`: renders the bottom bar (`<nav class="tabbar">` with links `/` and `/progress.html`, `aria-current="page"` on the active one) and the Settings panel (`<dialog id="settings">`: weight unit radio, reminders switch, Log out). Exposes `loadSettings() -> Promise<SettingsOut>` (cached for the page) and `saveSettings(partial) -> Promise<SettingsOut>`. The reminders switch calls `enableReminders()` / `disableReminders()` defined in Task 11; until then it is hidden.
  - Today: `/api/analyze` receives the 1600 px / 0.85 copy; after `POST /api/meals` the 800 px / 0.7 copy goes to `PUT /api/meals/{id}/photo`; failure keeps the blob in a `Map<mealId, Blob>` and the row shows "Photo not uploaded – retry". Rows with `has_photo` show a 40 px round thumbnail (`<img loading="lazy" src="/api/meals/{id}/photo">`, fetched with the token — use `api()` to fetch a blob and `URL.createObjectURL`), tap opens full size in a `<dialog>`. Meals older than 90 days without a photo show "Photo removed after 90 days".
  - Goal and calculator read from `loadSettings()`; changes saved with `saveSettings`. One-time move: if `localStorage` has `profile` or `goal`, `PUT /api/settings?only_if_empty=1`; on 200 or 409 remove both keys.

- [ ] **Step 1: Failing JS tests:** `units.test.js`: `toKg(150,'lb') === 68.04`; `fromKg(68.04,'lb') === 150`; **every** lb value from 66.0 to 661.0 step 0.1 satisfies `fromKg(toKg(v,'lb'),'lb') === v` (Review Focus 3; compare with tenths as integers to avoid float noise); `formatWeight(68,'kg') === "68.0 kg"`; ranges. `images.test.js`: `fitWithin(4000,3000,1600)` → `{1600,1200}`; `fitWithin(3000,4000,800)` → `{600,800}`; `fitWithin(500,400,1600)` → `{500,400}`.
- [ ] **Step 2: Run** `node --test "tests/*.test.js"` — expected: FAIL.
- [ ] **Step 3: Implement** modules and Today changes; Log out moves from the header into the Settings panel (keep `id="logout"` behaviour from `auth.js`).
- [ ] **Step 4: Run** JS + Python unit tests — expected: pass. Scripted check: start uvicorn on port 8765, sign in a local test user via the auth API, `POST /api/meals`, `PUT` a 50 KB JPEG to its photo route, `GET` → 307; stop the server.
- [ ] **Step 5: Commit** `feat(web): settings panel, bottom bar, meal photos on Today`.

### Task 10: Progress page

**Files:**
- Create: `backend/static/progress.html`, `backend/static/progress.js`, `backend/static/charts.js`
- Modify: `backend/static/styles.css`, `backend/app/main.py`, `backend/app/store.py`
- Test: `backend/tests/charts.test.js`, `backend/tests/test_daily_totals.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 9 (`units.js`, `nav.js`), Figma 04.
- Produces:
  - `GET /api/meals/daily-totals?from=&to=` (span ≤ 31 days) → `[{"date": "YYYY-MM-DD", "total_calories": float}]` with zero-filled days; `Store.daily_totals(start, end)`.
  - `charts.js` (CommonJS guard): `linePoints(values: {date, value}[], width, height, pad) -> string` (SVG `points`), `barHeights(values: number[], goal: number, height) -> {bars: number[], goalY: number}` (scale max = max(goal, max value) × 1.1). Pure, no DOM.
  - `progress.js`: check-in card from `GET /api/checkins?today=` (`due` → "Weekly check-in due" + Start check-in button linking to `/checkin.html`; else "Next check-in in N days"); weight chart for the last 84 days in the user's unit with latest value and change since first entry, "+ Log weight" dialog (date defaults to today, unit-aware range validation with inline errors as on the login page); calories vs goal bars for the last 7 days; timeline of check-ins with front/side/back thumbnails; select two dates → Compare dialog showing the chosen pose side by side; footer note "Visible only to you".
  - Empty states: no weights → "Log your first weight to see the chart"; no check-ins → "Your check-in photos will appear here".

- [ ] **Step 1: Failing tests:** `charts.test.js` (two-point line spans the width; bars scale so the goal line sits at 1/1.1 of the height when goal is the max); `test_daily_totals.py` (zero-fill, span 32 → 400, sums per day).
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** all unit tests; scripted check that `/progress.html`, `/progress.js`, `/charts.js` serve 200 and `/api/meals/daily-totals` works with a real token.
- [ ] **Step 5: Commit** `feat(web): progress page with weight and calorie charts and check-in timeline`.

### Task 11: Check-in flow, reminders opt-in and service worker

**Files:**
- Create: `backend/static/checkin.html`, `backend/static/checkin.js`, `backend/static/sw.js`, `backend/static/push.js`
- Modify: `backend/static/nav.js`, `backend/static/styles.css`, `backend/app/main.py` (serve `sw.js` with `Service-Worker-Allowed: /` if needed — it is at the root, so default scope `/` works)
- Test: `backend/tests/push.test.js`

**Interfaces:**
- Consumes: Task 5 routes, Task 6 push routes, Task 9 `images.js`/`units.js`, Figma 04b.
- Produces:
  - `checkin.js`: steps Weight → Front → Side → Back → Done, one per screen, progress dots, Back button; weight step unit-aware and skippable; photo steps use `<input type="file" accept="image/*" capture="environment">`, resize 1600 px / 0.8, then upload-url → PUT → record; a failed photo shows "Not uploaded – retry" and does not block Next; tip "Same spot, same light, every week". The check-in row is created when leaving the Weight step.
  - Done screen: "Check-in saved". First time only (`client_settings.reminders_enabled` false and `Notification.permission === 'default'`): "Remind me next week?" with Yes / Not now.
  - `push.js`: `urlBase64ToUint8Array(s: string) -> Uint8Array` (pure, exported for tests); `enableReminders() -> Promise<'enabled'|'blocked'|'unsupported'>` (register `/sw.js`, request permission, subscribe with the VAPID key from `/api/push/public-key`, `POST /api/push/subscribe`); `disableReminders()` (unsubscribe + `DELETE /api/push/subscribe`).
  - `sw.js`: on `push` show a notification with the payload title and icon-less body "Tap to start your check-in"; on `notificationclick` focus an open tab or open `payload.url`.
  - Settings panel reminders switch now visible; when permission is `denied` it shows "Notifications are blocked. In Chrome: ⋮ → Settings → Site settings → Notifications".

- [ ] **Step 1: Failing test:** `push.test.js`: `urlBase64ToUint8Array("AQID")` → `[1,2,3]`; handles `-`/`_` and missing padding.
- [ ] **Step 2: Run** — expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** all suites (unit, integration, JS). Scripted check: `/checkin.html`, `/sw.js`, `/push.js` serve 200; full API check-in with one photo as a real local user.
- [ ] **Step 5: Commit** `feat(web): weekly check-in flow and push reminders`.

### Task 12: Docs and manual checks

**Files:**
- Modify: `backend/README.md`, `docs/superpowers/specs/2026-10-31-m2-client-tracking-design.md` (Status line only)
- [ ] README: M2 features, new env vars, `gen_vapid.py`, cron on Vercel, manual phone checklist (real notification on Android via a hosted preview or `chrome://inspect` port forwarding; photo resize quality; lb entry).
- [ ] Spec status → "implemented (M2)".
- [ ] Run every suite one last time; commit `docs: M2 setup and manual checks`.
