# M1 Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every user logs in (Google or email/password), chooses a role once, and gets their own private calorie tracker stored in Supabase Postgres, with access enforced in both FastAPI and Row Level Security.

**Architecture:** The browser authenticates with Supabase Auth (`supabase-js` from a CDN) and sends the access token to FastAPI on every `/api/*` call. FastAPI verifies the token, applies `app/access.py`, and talks to Postgres through Supabase's REST API (PostgREST) **using the user's own token**, so RLS applies to every query. The service-role key is used only by the one-off SQLite import script.

**Tech Stack:** FastAPI 0.143, httpx 0.28 (existing), PyJWT[crypto] 2.10.1, pytest 8.3.4, Supabase (Auth, Postgres, PostgREST; CLI for local stack), `@supabase/supabase-js@2.45.4` via cdn.jsdelivr.net, plain HTML/JS.

**Spec:** `docs/superpowers/specs/2026-10-31-trainer-platform-design.md` (Sections 4, 5, 9, 10, 11-M1, 12)

## Global Constraints

- Hosted Supabase project region: **Singapore (`ap-southeast-1`)**.
- Roles: exactly `'client' | 'trainer' | 'admin'`. `admin` is never settable through the app; it is set by hand in SQL.
- Requests for another user's data return **404**, not 403.
- The service-role key is never sent to the browser and never used by request handlers in M1. Only the Supabase URL and publishable key reach the browser.
- Logs contain IDs and error types only, never meal contents or photos.
- English UI copy. Plain HTML/CSS/JS, no build step; match the existing `static/` style (`$()` helper, tokens in `styles.css`).
- M1 creates only the tables M1 uses: `profiles`, `coaching_links`, `meals`. The other spec tables arrive with their milestone, each with its RLS in the same migration.
- `/api/analyze` requires login (protects the Gemini quota).
- **Known break (accepted):** the Android app (`mobile/`) calls these endpoints without a token and will get 401 from the new backend. It keeps working only against an old single-user build until it gains login.
- Local venv is Python 3.10; `.python-version` says 3.12. Code must run on both (no 3.11+ syntax such as `except*` or `typing.Self`).

## Review Focus

1. **Open redirect after login:** `?next=https://evil.example` or `//evil.example` must be ignored (go to `/`). Test in Task 7.
2. **Logged in but no profile yet** (signed up, never chose a role) calling `/api/meals` must get **409 `{"detail":"choose_role"}`** and the page must send them to `/welcome.html`, not a 500. Test in Task 6.
3. **Role tampering:** `POST /api/me/role` with `"admin"`, or a second call trying to switch role, must fail (400 / 409), and a direct PostgREST `PATCH profiles set role` must be refused by the database. Tests in Tasks 2 and 6.
4. **Bad tokens:** expired, wrong signature, wrong audience, `alg: none`, or missing `Bearer` → 401. Tests in Task 3.
5. **Impossible dates:** `GET /api/meals?date=2026-02-30` matches the old regex but must return **400**, not 500 from Postgres. Test in Task 6. Supabase unreachable must return **503** with a plain message (Task 6).

---

### Task 0: Repository and test tooling

**Files:**
- Create: `.gitignore` (repo root), `backend/pytest.ini`, `backend/requirements-dev.txt`, `backend/tests/__init__.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1:** `git init` at `/home/htetmyet/projects/calorie-tracker` (only if the user has agreed). Root `.gitignore` must contain: `.env`, `.env.*`, `**/.venv/`, `**/__pycache__/`, `backend/data/`, `**/.vercel/`, `mobile/.gradle/`, `mobile/build/`, `mobile/app/build/`, `mobile/local.properties`, `backend/supabase/.temp/`.
- [ ] **Step 2:** Run `git status --porcelain | grep -E "\.env|calories\.db|local\.properties"`. Expected: no output.
- [ ] **Step 3:** Add `PyJWT[crypto]==2.10.1` to `requirements.txt`. Create `requirements-dev.txt` with `-r requirements.txt` and `pytest==8.3.4`. Install: `.venv/bin/pip install -r requirements-dev.txt`.
- [ ] **Step 4:** `pytest.ini`: `testpaths = tests`, marker `integration: needs the local Supabase stack (supabase start)`, `addopts = -m "not integration"`.
- [ ] **Step 5:** Run `.venv/bin/pytest` → "no tests ran" (exit 5 is fine); run `node --test "tests/*.test.js"` → 6 pass.
- [ ] **Step 6:** Commit: `chore: add git, pytest and JWT dependencies`.

### Task 1: Supabase environments and config

**Files:**
- Create: `backend/supabase/` (via `supabase init`), `backend/.env.example`, `backend/tests/test_config.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces in `app/config.py`: `SUPABASE_URL: str`, `SUPABASE_PUBLISHABLE_KEY: str`, `SUPABASE_JWT_SECRET: str` (local HS256 only; empty in production), `SUPABASE_SERVICE_ROLE_KEY: str` (import script only), `SUPABASE_TIMEOUT: float = 10`.

- [ ] **Step 1 (user action):** In Docker Desktop → Settings → Resources → WSL integration, enable this distro. Verify in WSL: `docker info --format '{{.ServerVersion}}'` prints a version.
- [ ] **Step 2:** `cd backend && npx supabase@2 init` then `npx supabase@2 start`. Record the printed API URL, publishable (anon) key, service-role key and JWT secret in `backend/.env` (never committed). `.env.example` lists the variable names with empty values.
- [ ] **Step 3 (user confirms cost first):** Create the hosted project in region `ap-southeast-1` (Supabase dashboard or MCP `create_project`). Store its URL and keys in Vercel env vars (Production + Preview), not in files.
- [ ] **Step 4 (user action):** Enable Google provider: Google Cloud OAuth client (Web), authorised redirect `https://<project-ref>.supabase.co/auth/v1/callback`; in Supabase Auth → URL configuration add `http://localhost:8000/**` and the Vercel domain. Locally, add the same in `supabase/config.toml` `[auth.external.google]` with `env(...)` secrets.
- [ ] **Step 5:** Test `test_config.py::test_supabase_settings_load` sets env vars via `monkeypatch`, reloads `app.config`, asserts the four values and `SUPABASE_TIMEOUT == 10.0`. Run → FAIL, implement, run → PASS.
- [ ] **Step 6:** Commit: `feat: Supabase config and local stack`.

### Task 2: Schema and Row Level Security

**Files:**
- Create: `backend/supabase/migrations/20261031000000_m1_foundations.sql`, `backend/tests/integration/__init__.py`, `backend/tests/integration/conftest.py`, `backend/tests/integration/test_rls.py`

**Interfaces:**
- Produces tables `profiles`, `coaching_links`, `meals` and SQL function `public.is_active_trainer_of(client uuid) returns boolean`.
- Produces test fixtures in `tests/integration/conftest.py`: `make_user(role: str | None) -> TestUser` (dataclass `id: str, token: str`), creating the auth user via `POST {SUPABASE_URL}/auth/v1/admin/users` (service key, `email_confirm: true`), signing in with `POST /auth/v1/token?grant_type=password`, and inserting the profile with the service key when `role` is given; `rest(token) -> httpx.Client` with base `{SUPABASE_URL}/rest/v1`, headers `apikey` + `Authorization: Bearer <token>`; `link(client, trainer, status)` inserts a `coaching_links` row with the service key.

- [ ] **Step 1: Write the failing tests** in `test_rls.py` (all `@pytest.mark.integration`):

```python
def test_client_reads_only_own_meals(make_user, rest): ...        # B's GET meals?user_id=eq.<A> -> []
def test_active_trainer_reads_client_meals(make_user, rest, link): ...   # status 'active' -> 1 row
@pytest.mark.parametrize("status", ["requested", "declined", "ended"])
def test_inactive_link_hides_meals(make_user, rest, link, status): ...   # -> []
def test_admin_cannot_read_client_meals(make_user, rest): ...           # admin token -> []
def test_trainer_cannot_write_client_meals(make_user, rest, link): ...  # POST meal with client's user_id -> 401/403
def test_cannot_self_assign_admin(make_user, rest): ...                 # role=None user POST profiles role 'admin' -> 403
def test_cannot_change_role(make_user, rest): ...                       # PATCH own profile role -> 401/403, row unchanged
def test_one_open_link_per_client(make_user, link): ...                 # second 'requested' row -> 409 (unique violation)
```

- [ ] **Step 2:** Run `npx supabase@2 db reset && .venv/bin/pytest -m integration tests/integration/test_rls.py -v` → FAIL (tables missing).
- [ ] **Step 3: Write the migration.** Exact rules:

```sql
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('client','trainer','admin')),
  display_name text not null default '' check (char_length(display_name) <= 80),
  created_at timestamptz not null default now()
);
create table public.coaching_links (
  id bigint generated always as identity primary key,
  client_id uuid not null references public.profiles(id) on delete cascade,
  trainer_id uuid not null references public.profiles(id) on delete cascade,
  status text not null check (status in ('requested','active','declined','ended')),
  requested_at timestamptz not null default now(),
  responded_at timestamptz, ended_at timestamptz, ended_by uuid
);
create unique index one_open_link_per_client on public.coaching_links(client_id)
  where status in ('requested','active');
create table public.meals (
  id bigint generated always as identity primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  eaten_at timestamp not null,          -- user's local time, as today
  meal_type text not null check (meal_type in ('breakfast','lunch','dinner','snack')),
  items jsonb not null,
  total_calories real not null
);
create index meals_user_eaten on public.meals(user_id, eaten_at);

create function public.is_active_trainer_of(client uuid) returns boolean
  language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.coaching_links
    where client_id = client and trainer_id = auth.uid() and status = 'active') $$;

alter table public.profiles enable row level security;
alter table public.coaching_links enable row level security;
alter table public.meals enable row level security;

create policy profiles_select on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_active_trainer_of(id)
         or exists (select 1 from public.coaching_links l where l.trainer_id = auth.uid()
                    and l.client_id = profiles.id and l.status = 'requested'));
create policy profiles_insert on public.profiles for insert to authenticated
  with check (id = auth.uid() and role in ('client','trainer'));
revoke update on public.profiles from authenticated;
grant update (display_name) on public.profiles to authenticated;
create policy profiles_update on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

create policy links_select on public.coaching_links for select to authenticated
  using (client_id = auth.uid() or trainer_id = auth.uid());
-- no write policies in M1 (requests arrive in M3)

create policy meals_select on public.meals for select to authenticated
  using (user_id = auth.uid() or public.is_active_trainer_of(user_id));
create policy meals_insert on public.meals for insert to authenticated with check (user_id = auth.uid());
create policy meals_delete on public.meals for delete to authenticated using (user_id = auth.uid());
-- no update policy: meals are not edited in place today
```

- [ ] **Step 4:** Run `npx supabase@2 db reset && .venv/bin/pytest -m integration tests/integration/test_rls.py -v` → all PASS.
- [ ] **Step 5:** Commit: `feat: M1 schema with row level security`.

### Task 3: Token verification

**Files:**
- Create: `backend/app/auth.py`, `backend/tests/test_auth.py`

**Interfaces:**
- Produces: `class User(BaseModel): id: str; token: str` · `class AuthError(Exception)` · `verify_token(token: str) -> str` (returns `sub`) · FastAPI dependency `current_user(authorization: str | None = Header(None)) -> User` raising `HTTPException(401, "not_logged_in")`.

- [ ] **Step 1: Write the failing tests** (tokens minted in the test with `jwt.encode(..., "test-secret-at-least-32-characters!!", "HS256")`, `monkeypatch` `config.SUPABASE_JWT_SECRET`):

```python
def test_valid_token_returns_sub(): assert verify_token(tok(sub="u1")) == "u1"
def test_expired_token_rejected(): ...           # exp in the past -> AuthError
def test_wrong_audience_rejected(): ...           # aud="anon" -> AuthError
def test_wrong_signature_rejected(): ...          # signed with another secret -> AuthError
def test_alg_none_rejected(): ...                 # jwt.encode(..., None, "none") -> AuthError
def test_current_user_requires_bearer(client): ...# no header / "Token x" -> 401 {"detail":"not_logged_in"}
```

- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_auth.py -v` → FAIL.
- [ ] **Step 3:** Implement. Accept only `aud == "authenticated"`, require `exp` and `sub`. If the token header `alg` is `HS256` **and** `config.SUPABASE_JWT_SECRET` is set, verify with the secret; if `alg` is `ES256` or `RS256`, verify with `jwt.PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")` (one module-level client, cached keys); any other alg → `AuthError`.
- [ ] **Step 4:** Run → PASS. Commit: `feat: verify Supabase access tokens`.

### Task 4: Access policy

**Files:**
- Create: `backend/app/access.py`, `backend/tests/test_access.py`

**Interfaces:**
- Produces: `Role = Literal["client","trainer","admin"]` · `LinkStatus = Literal["requested","active","declined","ended"] | None` · `@dataclass(frozen=True) class Viewer: id: str; role: Role` · `can_read_client_data(viewer: Viewer, client_id: str, link_status: LinkStatus) -> bool` · `can_write_own(viewer: Viewer, owner_id: str) -> bool`. `link_status` is the status of the link between `client_id` and `viewer.id` (viewer as trainer), or `None`.

- M1 routes only touch the caller's own data, so the first route consumer is M4 (trainer views). It is built and fully tested now so the rules exist before any cross-user route does.

- [ ] **Step 1: Write the failing tests:** a single parametrized `test_read_matrix` over viewer ∈ {owner, trainer, admin, stranger} × link ∈ {None, requested, active, declined, ended}. Expected `True` only for (owner, any) and (trainer, active). Plus `test_write_only_owner` (owner True; trainer with active link False; admin False).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (pure functions, no I/O). **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat: access policy for client data`.

### Task 5: Supabase data layer

**Files:**
- Create: `backend/app/store.py`, `backend/tests/integration/test_store.py`
- Delete after Task 8: `backend/app/db.py`

**Interfaces:**
- Consumes: `User` (Task 3), `MealIn`, `MealOut` (existing `app/schemas.py`).
- Produces: `class StoreUnavailable(Exception)` (network error or 5xx from Supabase), `class ProfileExists(Exception)`, and `class Store` constructed as `Store(user: User)`, with methods:
  - `get_profile() -> dict | None`
  - `create_profile(role: str, display_name: str) -> dict` (raises `ProfileExists` on 409)
  - `add_meal(meal: MealIn) -> MealOut`
  - `meals_on(date: datetime.date) -> list[MealOut]` (`eaten_at >= date` and `< date + 1 day`, ordered by `eaten_at`)
  - `delete_meal(meal_id: int) -> bool` (False when no row was deleted, which includes other users' meals)
  - FastAPI dependency `get_store(user: User = Depends(current_user)) -> Store`.
  Requests go to `{SUPABASE_URL}/rest/v1/...` with headers `apikey: SUPABASE_PUBLISHABLE_KEY`, `Authorization: Bearer <user.token>`, `Prefer: return=representation` on writes, timeout `SUPABASE_TIMEOUT`. `eaten_at` is sent and returned as `'YYYY-MM-DDTHH:MM'` (keep the existing API shape).

- [ ] **Step 1: Write the failing integration tests:** `test_add_and_list_meal_roundtrip` (same fields back, `eaten_at == "2026-10-31T08:15"`), `test_meals_on_excludes_other_days`, `test_delete_other_users_meal_returns_false`, `test_create_profile_twice_raises_profile_exists`, `test_unreachable_supabase_raises_store_unavailable` (monkeypatch `SUPABASE_URL="http://127.0.0.1:9"`).
- [ ] **Step 2:** Run `.venv/bin/pytest -m integration tests/integration/test_store.py -v` → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit: `feat: Supabase-backed store running as the user`.

### Task 6: Authenticated API

**Files:**
- Modify: `backend/app/main.py`, `backend/app/schemas.py`
- Create: `backend/tests/test_api.py` (uses `app.dependency_overrides` with a fake `Store` and a fixed `User`; no network)

**Interfaces:**
- Consumes: `current_user` (Task 3), `Store`, `get_store`, `StoreUnavailable`, `ProfileExists` (Task 5).
- Produces endpoints:
  - `GET /api/public-config` (no auth) → `{"supabase_url", "supabase_publishable_key"}`
  - `GET /api/me` → `ProfileOut {id, role, display_name}` or **404 `{"detail":"no_profile"}`**
  - `POST /api/me/role` body `RoleIn {role: Literal["client","trainer"], display_name: str (1–80 chars)}` → 201 `ProfileOut`; 409 if a profile exists; 422 for `"admin"` (Pydantic literal)
  - `POST /api/analyze`, `GET/POST /api/meals`, `DELETE /api/meals/{id}` now require auth; meal routes return **409 `{"detail":"choose_role"}`** when `get_profile()` is None. `GET /api/health` stays public.
  - `StoreUnavailable` → 503 `"The database is unreachable. Try again in a minute."` (exception handler).

- [ ] **Step 1: Write the failing tests:**

```python
def test_meals_require_login(anon_client): assert anon_client.get("/api/meals?date=2026-10-31").status_code == 401
def test_analyze_requires_login(anon_client): ...                      # 401
def test_health_stays_public(anon_client): ...                         # 200
def test_no_profile_gets_choose_role(client_without_profile): ...      # 409, detail "choose_role"
def test_role_admin_rejected(client_without_profile): ...              # POST role "admin" -> 422
def test_role_second_time_conflicts(client): ...                       # 409
def test_impossible_date_is_400(client): ...                           # date=2026-02-30 -> 400
def test_delete_missing_meal_is_404(client): ...                       # fake store returns False -> 404
def test_store_unavailable_is_503(client_store_down): ...              # 503 with the message above
def test_daylog_totals_unchanged(client): ...                          # existing totals logic still sums items
```

- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_api.py -v` → FAIL. **Step 3:** Implement; parse `date` with `datetime.date.fromisoformat` inside try/except → 400 `"date must be a real YYYY-MM-DD date"`. **Step 4:** Run full unit suite `.venv/bin/pytest` → PASS.
- [ ] **Step 5:** Commit: `feat: require login for meals and analysis`.

### Task 7: Login, role choice and authenticated frontend

**Files:**
- Create: `backend/static/login.html`, `backend/static/welcome.html`, `backend/static/auth.js`, `backend/tests/auth.test.js`
- Modify: `backend/static/app.js` (the four `fetch` calls at lines ~244, 259, 294, 400), `backend/static/index.html` (load scripts; add "Log out" in the masthead), `backend/static/styles.css`

**Interfaces:**
- Produces in `auth.js` (classic script, CommonJS export guard like `energy.js`):
  - `safeNext(raw: string | null) -> string`: returns `raw` only if it starts with `/` and not `//` or `/\`; otherwise `"/"`.
  - `initAuth() -> Promise<SupabaseClient>`: fetches `/api/public-config`, creates the client from `https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js`.
  - `api(path, options) -> Promise<Response>`: adds `Authorization: Bearer <access_token>`; on 401 → `location = "/login.html?next=" + encodeURIComponent(location.pathname + location.search)`; on 409 with `detail === "choose_role"` → `location = "/welcome.html"`.
  - `logout() -> Promise<void>`.
- `login.html`: "Continue with Google" (`signInWithOAuth`, `redirectTo` = origin + `safeNext(next)`), email + password Log in, "Create an account" (`signUp`), errors shown in a `role="status"` element. Matches wireframe 01.
- `welcome.html`: display name field + two cards from wireframe 02 → `POST /api/me/role`. Trainer choice shows: "Thanks. Trainer profiles open soon; we'll review yours before you're listed." then continues to `/` (trainers can track their own meals in M1).

- [ ] **Step 1: Write the failing test** `tests/auth.test.js`:

```js
test("safeNext keeps same-site paths", () => assert.equal(safeNext("/?d=1"), "/?d=1"));
test("safeNext blocks other sites", () => {
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", null, ""])
    assert.equal(safeNext(bad), "/");
});
```

- [ ] **Step 2:** Run `node --test "tests/*.test.js"` → FAIL. **Step 3:** Implement `auth.js`, the two pages, and switch `app.js` to `api()`. On load, `index.html` calls `initAuth()`; no session → login page; then `GET /api/me` (404 → welcome).
- [ ] **Step 4:** Run `node --test "tests/*.test.js"` → all PASS (8 energy+auth tests).
- [ ] **Step 5: Manual check against the local stack** (`npx supabase@2 start`, `.venv/bin/uvicorn app.main:app --reload`): sign up with email → welcome → choose Client → log a meal → log out → log in → meal still there; second account cannot see it. If Chromium deps are installed, script this with Playwright instead.
- [ ] **Step 6:** Commit: `feat: login, role choice and authenticated web app`.

### Task 8: Import existing SQLite meals and retire SQLite

**Files:**
- Create: `backend/scripts/import_sqlite.py`, `backend/tests/integration/test_import.py`
- Delete: `backend/app/db.py`; remove `DB_PATH` from `config.py` and `db.init_db()` from `main.py`'s lifespan
- Modify: `backend/README.md` (setup: Supabase env vars, `supabase start`, Google OAuth, running tests; note the Android break)

**Interfaces:**
- Produces CLI: `python scripts/import_sqlite.py --db data/calories.db --owner <auth user uuid> [--force]`. Uses the service-role key. Refuses (exit 1, message) if the owner has no profile, or already has meals unless `--force`. Prints `Imported N meals`.

- [ ] **Step 1: Write the failing integration test** `test_import_copies_all_meals`: builds a temp SQLite with 3 meals in the current schema, runs `main(["--db", tmp, "--owner", uid])`, asserts 3 meals with matching `eaten_at`, `meal_type`, `total_calories`; second run without `--force` exits 1 and leaves 3 meals.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run full suites: `.venv/bin/pytest`, `.venv/bin/pytest -m integration`, `node --test "tests/*.test.js"` → all PASS.
- [ ] **Step 5:** Run the import for real against the hosted project once the user has an admin account: sign up, then in SQL `update profiles set role = 'admin' where id = '<uuid>'` (run as the database owner), then the script.
- [ ] **Step 6:** Push migrations to the hosted project (`npx supabase@2 link` + `db push`), deploy a Vercel **preview**, and repeat the Task 7 manual check there. Production deploy only after the user says so.
- [ ] **Step 7:** Commit: `feat: import SQLite meals into Supabase; remove SQLite`.
