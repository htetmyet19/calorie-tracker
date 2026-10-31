# Trainer platform: design

Date: 2026-10-31
Status: approved in conversation, awaiting written-spec review
Wireframes: https://www.figma.com/design/KK4rKfkgUHfKn8lYraFpPJ (screens 01–10)

## 1. Goal

Turn the single-user calorie tracker into a platform where **clients** log meals and progress and **trainers** coach them: view their meals and progress, leave guidance, set their calorie goal, and share training videos. Launch market: **Myanmar**, real users.

### Success criteria for v1
- A client can sign up, log meals with photos, log weight and progress photos, find an approved trainer and connect.
- A trainer can be approved, accept clients, see each client's meals, photos and progress, comment, set the goal, and assign videos.
- No user can read data they are not entitled to (Section 5), proven by tests at both the API and database layers.
- Food recognition is measured on 20–30 Burmese meals with known calories before launch, and the error is reported.

### Non-goals for v1
- Burmese UI (English only; text kept simple so translation can be added later).
- Android app changes (it stays single-user; web is mobile-first instead).
- Live chat, payments, multiple trainers per client, Facebook login, phone/SMS login.
- Real-time push; pub/sub (see Section 8).

## 2. Context and constraints

- Existing stack: FastAPI + plain HTML/CSS/JS (no build step), SQLite, deployed on Vercel. Meal analysis via Gemini (or local Ollama).
- Vercel functions reject request bodies over ~4.5 MB, and their filesystem is not persistent, so SQLite cannot stay.
- Users are mostly on Android phones with slow, expensive, sometimes interrupted mobile data.
- Legal: Myanmar's 2017 *Law Protecting the Privacy and Security of Citizens* and the 2025 *Cyber Security Law* may apply. **Details unverified; must be checked with local counsel before launch.** Design response: collect minimum data (no national ID, exact location or phone number), explicit client consent to trainer access, full account deletion.
- Not yet measured: Gemini accuracy on Burmese dishes (mohinga, laphet thoke, rice with several curries).

## 3. Decisions

| Topic | Decision |
|---|---|
| Roles | client, trainer, admin |
| Trainer discovery | Public directory (logged-in users only); trainers listed only after admin approval of their profile and certificate |
| Linking | Client requests → trainer accepts/declines. One active trainer per client. Client can disconnect at any time |
| Platform | Web only, mobile-first (360 px), trainer screens also usable on desktop |
| Language | English |
| Auth | Supabase Auth: Google sign-in + email/password |
| Data/storage | Supabase Postgres + Storage, Singapore region |
| Video | Cloudflare Stream (adaptive bitrate, signed playback, resumable direct upload) |
| Photos | Meal photos stored (~100 KB); body progress photos stored with strict access |
| Admin and client data | Admin cannot read any client health data |

## 4. Data model (Postgres)

```
profiles            id (= auth.users.id), role ('client'|'trainer'|'admin'),
                    display_name, created_at

client_settings     user_id PK, height_cm, weight_kg, age, sex, activity,
                    weight_goal, goal_kcal, goal_set_by (user id), updated_at

trainer_profiles    user_id PK, bio, specialties text[], city, online bool, price_note,
                    certification_file, status ('pending'|'approved'|'rejected'),
                    rejection_reason, reviewed_at, reviewed_by

coaching_links      id, client_id, trainer_id,
                    status ('requested'|'active'|'declined'|'ended'),
                    requested_at, responded_at, ended_at, ended_by
                    UNIQUE (client_id) WHERE status IN ('requested','active')

meals               id, user_id, eaten_at, meal_type, items jsonb, total_calories, photo_path

weight_logs         id, user_id, logged_on date, weight_kg
                    UNIQUE (user_id, logged_on)

progress_photos     id, user_id, taken_on, pose ('front'|'side'|'back'), photo_path, created_at

guidance            id, client_id, author_id, meal_id (nullable), body, created_at, read_at

training_videos     id, trainer_id, title, notes, stream_uid, status ('uploading'|'ready'|'error'),
                    size_mb, duration_s, created_at

video_assignments   video_id, client_id, assigned_at, watched_at
                    PRIMARY KEY (video_id, client_id)

deletion_failures   id, kind ('storage'|'stream'), ref, attempts, last_error, created_at
```

Storage buckets (all private): `meal-photos`, `progress-photos`, `trainer-certs`.

Rules:
- Link rows are never deleted; ending a link sets `status = 'ended'`, keeping a record of who had access and when.
- A trainer may set `client_settings.goal_kcal`; `goal_set_by` records who did, and the client sees "Goal set by <trainer>" and can change it back.
- `profiles.role = 'admin'` is set only by hand in the database; no sign-up path leads to it.
- Existing SQLite meals are imported once into the admin's account, then SQLite is retired.

## 5. Access rules

"Trainer (active)" means a `coaching_links` row with `status = 'active'` for that client and trainer at request time.

| Data | Client (owner) | Trainer (active) | Trainer (requested) | Admin | Anyone else |
|---|---|---|---|---|---|
| Meals + meal photos | read/write | read | none | none | none |
| client_settings | read/write | read; may set goal_kcal | goal_kcal only | none | none |
| Weight logs | read/write | read | none | none | none |
| Progress photos | read/write/delete | read | none | none | none |
| Guidance | read; mark read | write; read own | none | none | none |
| Trainer profile | read approved | own: read/write | — | read all; approve/reject | read approved (logged in) |
| Certificate file | none | own only | — | read | none |
| Videos | watch if assigned **and** link active | own: upload/assign/delete | none | none | none |

Enforcement:
1. **FastAPI:** verify the Supabase token on every request; every route calls `app/access.py` (e.g. `can_read_client_data(user, client_id)`) before touching data.
2. **Postgres Row Level Security:** FastAPI runs queries as the logged-in user (role `authenticated` with the user's claims), so the database applies the same rules. The service-role key is used only for admin-only operations and never reaches the browser.
3. **Files:** served only through signed URLs valid for 5 minutes, issued after the access check. Video playback uses Cloudflare signed tokens issued the same way.
4. Requests for another user's data return **404**, not 403.
5. Access ends immediately on disconnect; nothing is cached across requests.

## 6. Screens and flows

See the Figma wireframes for layout.

- **01 Login:** Google first, then email/password.
- **02 First login:** choose "Track my meals" or "I'm a trainer". Trainers fill in profile + certificate → "Waiting for review".
- **03 Client Today:** latest unread trainer note, calorie ring, "Log a meal", meals list. Meal photos are resized in the browser to ~1600 px before analysis and stored at ~100 KB.
- **04 Client Progress:** weight chart, calories vs goal, progress photo timeline with side-by-side comparison, "Visible to you and <trainer> only".
- **05 Find a trainer:** search + filters (specialty, city, online), profile preview stating exactly what the trainer will see, Request.
- **06 My trainer:** notes, assigned videos (with size at low quality), Disconnect.
- **07 Trainer Clients:** pending requests (Accept/Decline), then clients sorted by attention (not logging, over goal, new photos), then on-track clients.
- **08 Trainer client detail:** tabs Meals / Progress / Goal / Videos; comment on a meal.
- **09 Trainer upload video:** resumable direct upload to Cloudflare, title, assign to one/some/all clients.
- **10 Admin review:** pending trainer, certificate via short-lived link, approve / reject with reason.

The existing goal calculator (shipped 2026-10-31, `static/energy.js`) moves its saved details from `localStorage` to `client_settings`.

## 7. Uploads

| What | Path | Why |
|---|---|---|
| Meal photo | Browser resizes → FastAPI `/api/analyze` (< 4.5 MB) → stored in `meal-photos` | Vercel body limit; analysis needs the server |
| Progress photo | FastAPI issues a signed upload URL → browser uploads directly to Supabase Storage | Keeps large files off Vercel |
| Certificate | Same as progress photo, bucket `trainer-certs` | Same |
| Video | FastAPI creates a Cloudflare Stream direct-upload URL → browser uploads with tus (resumable) → Cloudflare webhook sets `status = 'ready'` or `'error'` | Files of hundreds of MB; unreliable connections |

## 8. Updates and notifications

No pub/sub. Unread counts (notes, requests, new photos/videos) are computed by query on page load and refreshed every 60 seconds. Revisit only if live chat is added (prefer Server-Sent Events or a managed realtime service).

## 9. Error handling

- Expired session → redirect to login, then return to the original page.
- Meal saves even if its photo upload fails; the meal shows "Photo not uploaded – retry".
- Video processing failure shows "Processing failed – re-upload" to the trainer.
- Cloudflare webhooks are verified by signature; unverified calls are rejected.
- A second open request by the same client is rejected by the unique index with a clear message.
- Account deletion removes database rows, storage objects and (for trainers) Stream videos; any failed external deletion is recorded in `deletion_failures` and retried.
- Logs contain IDs and error types only, never health data, meal contents or photos.

## 10. Testing

- `tests/test_access.py`: every cell of the Section 5 table × link states (none, requested, active, declined, ended).
- RLS tests: key cases run as SQL as different users against a local Supabase (Supabase CLI), proving the database refuses even without FastAPI checks.
- API tests (pytest + httpx, local Supabase), including: after disconnect, the trainer's requests for meals, photos and videos return 404.
- Existing `node --test` suite for `energy.js` keeps passing.
- Food-recognition evaluation: 20–30 Burmese meal photos with known calories; report mean absolute percentage error before launch.
- Browser end-to-end tests require Chromium's system libraries in WSL (`sudo npx playwright install-deps chromium`).

## 11. Build order

| # | Milestone | Done when |
|---|---|---|
| M1 | Supabase project, schema + RLS, login, role choice, token verification, `access.py`, SQLite import | Logged-in users each have their own working tracker |
| M2 | Per-user meals with photos, server-side calculator settings, weight logs, progress photos | Client Today and Progress work |
| M3 | Trainer profiles, certificate upload, admin review, directory, request/accept/decline/disconnect | Client connects to an approved trainer |
| M4 | Trainer client list, client detail, guidance, goal setting, unread counts | Trainer can coach a client |
| M5 | Cloudflare Stream upload, webhook, assignment, signed playback, watched status | Trainer assigns a video; client watches it |

After M5: usability test with 2 trainers and 3 clients in Myanmar using the Section 6 tasks.

## 12. Operations

- Supabase paid tier before real users (no project pausing, backups); check current pricing.
- Secrets (Supabase service-role key, Gemini key, Cloudflare API token, webhook secret) live only in Vercel environment variables.
- Only the Supabase publishable key is sent to the browser.

## 13. Open items

- Legal review of Myanmar privacy and cyber-security obligations (before launch).
- Whether to switch the BMI categories to the WHO Asian cut-offs (23 / 27.5); small separate change.
- Possible existing bug: `/api/analyze` allows 10 MB uploads but Vercel rejects bodies over ~4.5 MB (untested). Fixed by the browser resize in M2.
