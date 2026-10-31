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
| `SUPABASE_SERVICE_ROLE_KEY` | Bypasses Row Level Security. Used only by the import script and test setup, both run locally; keep it secret and do **not** add it to the Vercel environment (no request handler uses it) |
| `SUPABASE_JWT_SECRET` | Only if the project still signs tokens with the legacy HS256 secret; leave empty for asymmetric keys |
| `SUPABASE_TIMEOUT` | Seconds to wait on Supabase calls (default `10`) |

**Google sign-in is not set up yet.** It is a pending step: create a Google OAuth client and enable the provider in the
Supabase dashboard (Authentication > Providers), and for the local stack in `supabase/config.toml`.

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

## Daily job and push

Once a day (02:30 UTC, 09:00 in Myanmar) Vercel Cron calls `GET /api/cron/daily`. The job sends weekly check-in
reminders by web push: at most two per due check-in, the second three days after the first. "Today" is computed in
`Asia/Yangon`. It stops starting new work after 50 s and leaves the rest for the next day.

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

Run it by hand against a local stack: `curl -H "Authorization: Bearer $CRON_SECRET" http://localhost:8000/api/cron/daily`.

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
