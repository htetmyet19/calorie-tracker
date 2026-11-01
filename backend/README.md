# Calorie Tracker (web)

Upload a meal photo → a vision model (local Ollama by default, or Gemini) identifies the foods and estimates portions/calories → review, edit, and save to a daily log.

## Run

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt   # app + test tools; requirements.txt alone is enough to run
npx supabase@2 start        # local Supabase stack (needs Docker); applies supabase/migrations
.venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000. `GET /api/health` tells you whether the model is reachable.

Meals and profiles live in Supabase Postgres, per user. Copy `.env.example` to `.env` and fill in the Supabase values
(`npx supabase@2 status` prints the local ones).

### Supabase settings (`.env`)

| Variable | |
|---|---|
| `SUPABASE_URL` | Project URL (local: `http://127.0.0.1:54321`) |
| `SUPABASE_PUBLISHABLE_KEY` | Publishable (anon) key; also served to the web page via `/api/public-config` |
| `SUPABASE_SERVICE_ROLE_KEY` | Bypasses Row Level Security. Used by the import script, test setup and the daily job (`app/cron.py`, the only app module allowed to read it). It must be set on Vercel for the cron job; keep it secret |
| `SUPABASE_JWT_SECRET` | Only if the project still signs tokens with the legacy HS256 secret; leave empty for asymmetric keys |
| `SUPABASE_TIMEOUT` | Seconds to wait on Supabase calls (default `10`) |

**Google sign-in** is enabled on the hosted project (Authentication > Providers > Google, with a Google OAuth client).
For the local stack, configure it in `supabase/config.toml`.

### Hosted Supabase setup

Before real users sign up on the deployed app, in the Supabase dashboard (Authentication > URL Configuration):

- [ ] **Site URL** = the Vercel production domain, e.g. `https://<domain>` (it defaults to `http://localhost:3000`).
- [ ] **Redirect URLs** allow-list: `https://<domain>/**`, plus the Vercel preview domains
      (e.g. `https://*-<team-slug>.vercel.app/**`) if you log in on previews. Login and sign-up send people back to
      the page they came from, which must match this list.
- [ ] **Confirm email** stays on (Authentication > Providers > Email).
- [ ] The built-in email sender is rate-limited and meant for testing
      ([current limits](https://supabase.com/docs/guides/auth/rate-limits)); set up
      [custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp) before real users sign up.

Apply the schema to a hosted project once, after `supabase link`:

```bash
npx supabase@2 link --project-ref <ref>
npx supabase@2 db push
```

M2 adds four migrations on top of the M1 one: `20261101000000_m2_client_tracking.sql`,
`20261101000001_m2_photo_path_owner.sql`, `20261101000002_m2_checkin_owner.sql` and
`20261101000003_m2_photo_removed.sql`.

### Tests

```bash
cd backend
.venv/bin/pytest                      # unit tests, no stack needed
.venv/bin/pytest -m integration       # needs the local Supabase stack running
node --test "tests/*.test.js"         # frontend helper tests
```

### Importing the old SQLite meals

Earlier versions stored meals in `data/calories.db`. To copy them to a Supabase user (the user must have signed in
and chosen a role, so a profile exists):

```bash
.venv/bin/python scripts/import_sqlite.py --db data/calories.db --owner <auth user uuid> [--force]
```

It uses the service-role key, imports everything in one request, and prints `Imported N meals`. It refuses if the
owner already has meals unless you pass `--force`. `--force` only appends: it never deletes or de-duplicates, so
re-running an import with it adds every meal a second time. The SQLite file is left untouched.

### Model settings (`.env`)

| Variable | Default | |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` or `gemini` |
| `OLLAMA_URL` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `gemma4:26b` | Must support vision (`ollama show <model>` lists "vision") |
| `OLLAMA_TIMEOUT` | `300` | Seconds; the first request also loads the model |
| `GEMINI_API_KEY` | | Only for `gemini`, from https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-flash-latest` | `.venv/bin/python scripts/list_models.py` lists options |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-flash-lite-latest` | Tried in order if the main model is overloaded (503), out of quota (429) or retired (404) |
| `GEMINI_RETRIES` | `2` | Retries per model on 500/503/504, with 1s, 2s backoff |

### Ollama on Windows, backend in WSL

Ollama for Windows listens on `127.0.0.1` only, which WSL's default NAT networking can't reach.
Turn on mirrored networking (Windows 11 22H2+) so `localhost` in WSL reaches Windows: add to
`%UserProfile%\.wslconfig`, then run `wsl --shutdown` in PowerShell:
```ini
[wsl2]
networkingMode=mirrored
```
(The alternative, setting `OLLAMA_HOST=0.0.0.0` on Windows and pointing `OLLAMA_URL` at the Windows IP,
also exposes Ollama to your whole network.)

## Client tracking (M2)

- Pages: `/` (Today, with the meal log), `/progress.html` (weight and calorie charts, check-in timeline, Compare),
  `/checkin.html` (weekly check-in with optional photos) and the Settings panel (units, reminders, push).
- Weight can be entered in kg or lb. The accepted lb range is 66.2-661.3 (30-300 kg).
- Meal photos are deleted after 90 days. The meal stays and shows "Photo removed after 90 days". Progress photos are
  kept until you delete them. Uploads with no matching row are swept after 24 h.
- Changed from M1: calculator details are saved to the account only when you press "Use this goal" (Cancel discards
  them). Values an older version kept in the browser are moved to the account once.

## Daily job and push

Once a day (02:30 UTC, 09:00 in Myanmar) Vercel Cron calls `GET /api/cron/daily`. The job sends weekly check-in
reminders by web push: at most two per due check-in, the second three days after the first. "Today" is computed in
`Asia/Yangon` (a fixed UTC+06:30 offset). It stops starting new work after 50 s and leaves the rest for the next day,
so the function needs a time limit of at least 60 s: `backend/vercel.json` sets `maxDuration: 60` for `app/main.py`
(the FastAPI entry Vercel detects); Fluid compute's default limit is also enough. If any of the three `VAPID_*`
variables is empty, the job skips reminders and reports `"push": "not_configured"`.

1. Generate a VAPID key pair (prints two lines, writes nothing):
   ```bash
   .venv/bin/python scripts/gen_vapid.py
   ```
   Paste the output into `backend/.env` for local use and into the Vercel project's environment variables.
   Also set `VAPID_SUBJECT` to a `mailto:` address you control.
2. Set `CRON_SECRET` on Vercel to a long random string (for example `openssl rand -hex 32`). Vercel Cron sends it as
   `Authorization: Bearer <CRON_SECRET>`; the endpoint answers 401 to anything else, and always when it is unset.
3. Set `SUPABASE_SERVICE_ROLE_KEY` on Vercel. It bypasses Row Level Security and is read only by `app/cron.py`
   (a unit test enforces this); keep it out of client code, logs and screenshots.
4. Keep the same `VAPID_PRIVATE_KEY` for good: changing it invalidates every existing push subscription.

Schedule: `backend/vercel.json` has `{"path": "/api/cron/daily", "schedule": "30 2 * * *"}` (UTC). Env var names
needed on Vercel: `CRON_SECRET`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `SUPABASE_SERVICE_ROLE_KEY`.

Run it by hand against a local server (`.env` must have `SUPABASE_SERVICE_ROLE_KEY`; use any placeholder as the secret
and set the same value as `CRON_SECRET` in `.env`):

```bash
curl -H "Authorization: Bearer <your-CRON_SECRET>" http://localhost:8000/api/cron/daily
```

## Manual phone checks

Automated tests cannot cover these. Push needs HTTPS: use a Vercel preview, or on Android Chrome use
`chrome://inspect` port forwarding to `localhost:8000`.

- [ ] Allow notifications in Settings and receive a real push on Android Chrome; tapping it opens Progress.
- [ ] Camera capture: photos keep the right orientation (EXIF) and HEIC files from iPhones are handled.
- [ ] A saved meal shows its photo thumbnail; a failed upload shows "Photo not uploaded – retry" and retry works.
- [ ] Enter weight in lb, save, reload: the value round-trips.
- [ ] 360 px wide layout in light and dark on Today, Progress and Check-in.
- [ ] Check-in with a skipped photo saves and appears in the timeline.
- [ ] Compare on Progress shows two check-ins side by side.
- [ ] Install: Android Chrome shows "Install" in Settings, the app opens full-screen from its home-screen icon;
      on iPhone, Share > Add to Home Screen does the same. Nothing sits under the notch or the home bar.
- [ ] iPhone, installed app: turning on reminders works and a check-in push arrives (iOS 16.4+ only sends web push
      to home-screen apps). Google sign-in inside the installed iPhone app ends logged in to the app, not Safari.

Known follow-ups: timeline thumbnails are the full stored photos (data cost; store small thumbnails later), and the
checks above are still pending on a real device.

## How it works

| File | Role |
|---|---|
| `app/analysis.py` | Resizes the image, picks the provider, sanity-checks the returned numbers |
| `app/ollama_client.py`, `app/gemini_client.py` | Send the image and prompt, ask for JSON matching `MealAnalysis` |
| `app/schemas.py` | Pydantic models, also used as the model's response schema |
| `app/auth.py` | Verifies the Supabase JWT on each request and returns the current user |
| `app/access.py` | Role and coaching-link rules (who may see whose data) |
| `app/store.py` | Per-user profile and meal storage in Supabase Postgres, called with the user's own JWT so Row Level Security applies |
| `app/main.py` | FastAPI routes: `/api/me`, `POST /api/analyze`, `GET/POST /api/meals`, `DELETE /api/meals/{id}` |
| `supabase/migrations/` | Postgres schema and RLS policies |
| `scripts/import_sqlite.py` | One-off import of the old SQLite meals |
| `app/cron.py`, `app/reminders.py` | Daily job (service-key client) and the pure reminder rules |
| `static/` | Plain HTML/CSS/JS frontend |
| `static/manifest.webmanifest`, `static/icons/` | Installable app (PWA); `scripts/make_icons.py` redraws the icons |

## Using it from the Android app

> **The Android app no longer works against this backend.** The API now requires a Supabase login and the app in
> `../mobile` has none yet; it will not work until it gains login.

The app in `../mobile` talks to this server over your Wi-Fi; the model (or Gemini key) stays here.

1. Listen on all interfaces, not just localhost:
   ```bash
   .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. WSL2 hides the server behind NAT by default. Either:
   - **Mirrored networking (simplest, Windows 11 22H2+):** add to `%UserProfile%\.wslconfig`, then run `wsl --shutdown` in PowerShell:
     ```ini
     [wsl2]
     networkingMode=mirrored
     ```
   - **Or a port proxy** (PowerShell as admin; re-run when the WSL IP changes, find it with `hostname -I` in WSL):
     ```powershell
     netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=<WSL IP>
     ```
   Either way, allow inbound TCP 8000 in Windows Firewall (private network only):
   ```powershell
   New-NetFirewallRule -DisplayName "Calorie tracker 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow
   ```
3. Find your PC's Wi-Fi address (`ipconfig` in Windows, the "IPv4 Address" of the Wi-Fi adapter) and enter `http://<that IP>:8000` in the app's settings, then tap "Test connection".

Meal endpoints now require a Supabase login, but `/api/health` and the static page are still open, so only expose the server on a network you trust.
