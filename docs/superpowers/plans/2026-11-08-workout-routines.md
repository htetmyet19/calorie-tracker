# Workout Routines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client answers a safety question and four inputs and gets a weekly routine of YouTube exercise demos, built by rules + AI from a curated library, and ticks off sessions.

**Architecture:** Pure rules (`app/routine_rules.py`) build a safe frame and a rules-only plan and validate any plan; `app/routine_ai.py` asks the configured LLM to fill the frame and falls back to rules on any failure; `Store` persists routines and ticks through PostgREST under RLS; a new `workout.html` page shows and ticks the routine. The library lives in `backend/data/exercise_videos.json` and is pushed to the database by `scripts/sync_videos.py`.

**Tech Stack:** FastAPI, Pydantic v2, httpx, Supabase Postgres + RLS (PostgREST), google-genai / Ollama, plain HTML/CSS/JS, pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-08-workout-routines-design.md`

## Global Constraints

- Run everything from `backend/`: `.venv/bin/pytest`, `.venv/bin/pytest -m integration` (needs `npx supabase@2 start`), `node --test "tests/*.test.js"`.
- Labels, exactly: category `warm_up|push|pull|legs|core|cardio|mobility`; level `beginner|intermediate|advanced`; equipment `none|dumbbells|gym`; goal `lose|maintain|gain`; source `ai|rules`.
- Inputs: `days_per_week` 2–6; `session_min` one of 20, 30, 45, 60.
- Matching is cumulative: level ≤ client level; equipment ≤ client equipment (`none` < `dumbbells` < `gym`). New routines use only `active` videos.
- Plan bounds: sets 1–5, reps 5–20, seconds 20–60, rest_sec 30–120, exactly one of reps/seconds, 2–7 items per day excluding warm-up, `why` 1–140 chars and no URL, day time ≤ `session_min × 60 × 1.1` seconds including the 300 s warm-up.
- AI step total timeout: 20 s. Rate limit: 5 routines per user per rolling 24 h.
- The injury answer is never sent to the server or stored.
- Video embeds use `https://www.youtube-nocookie.com/embed/<id>`, created only when the client taps ▶.
- Copy fixed by the spec: "Please check with a doctor or physiotherapist before starting a routine."; "Not enough exercises for these choices yet. Try other equipment."; "You've made 5 routines today. Try again tomorrow."; "This video is no longer available"; beginner 5–6-day note: "Beginners recover better with rest days, so this plan has 4. You can add a walk on the other days."
- No YouTube ID is ever generated or guessed by code or AI; the library file ships empty (`[]`) and the owner fills it.
- Commits: conventional messages, no Claude co-author or "Generated with" lines (repo owner's rule).

## Review Focus

1. **Empty or thin library** (the first deploy ships `[]`): `POST /api/routines` must return 409 with the "Not enough exercises…" copy, never 500. → Task 6 `test_create_with_empty_library_is_409`.
2. **No settings row / no goal set**: routine is built with goal `maintain`. → Task 6 `test_goal_defaults_to_maintain`.
3. **Double-tap on Build** (two POSTs): exactly one active routine afterwards, both count toward the limit. → Task 6 `test_two_creates_leave_one_active`.
4. **Ticking an old (replaced) routine or a future date**: 404 for a non-active routine, 400 for a date more than one day ahead of UTC. → Task 6 `test_tick_inactive_routine_404`, `test_tick_future_date_400`.
5. **Week boundary**: Sunday belongs to the week that started the previous Monday. → Task 3 `test_week_start_sunday_and_monday`.

---

### Task 1: Database tables and RLS

**Files:**
- Create: `backend/supabase/migrations/20261108000000_workout_routines.sql`
- Test: `backend/tests/integration/test_rls_workouts.py`

**Interfaces:**
- Produces: tables `exercise_videos`, `routines`, `workout_sessions` with columns exactly as spec §3 (plus `routines.fallback_reason text null`). Partial unique index `routines_one_active on routines(user_id) where active`. Unique `(routine_id, day_index, done_on)` on `workout_sessions`. Check constraints for every label list and `days_per_week between 2 and 6`, `session_min in (20,30,45,60)`, `duration_sec > 0`, `day_index between 0 and 5`.

- [ ] **Step 1: Write the failing integration tests** (style of `tests/integration/test_rls_m2.py`, fixtures `make_user`, `rest`, `service`)

```python
def test_videos_readable_not_writable(make_user, rest, service): ...
    # service inserts one video; client a can GET it (inactive ones too); a's POST/PATCH/DELETE → 401/403 or no rows changed
def test_routines_owner_only(make_user, rest): ...
    # a inserts a routine (plan={"days": []}); b's GET with user_id=eq.a → []; b's POST with user_id=a → 401/403
def test_one_active_routine_per_user(make_user, rest): ...
    # second active insert for a → 409; after PATCH first active=false, insert → 201
def test_sessions_owner_and_routine_owner(make_user, rest): ...
    # a ticks own routine → 201; same tick again → 409; b ticking a's routine_id with user_id=b → 401/403
```

- [ ] **Step 2: Run, expect failure** — `.venv/bin/pytest -m integration tests/integration/test_rls_workouts.py -v` → FAIL (relation does not exist).

- [ ] **Step 3: Write the migration.** RLS policies follow `20261101000000_m2_client_tracking.sql` with `(select auth.uid())`, no trainer clauses:
  - `exercise_videos`: `select to authenticated using (true)`; no write policies.
  - `routines`: select/insert/update/delete where `user_id = (select auth.uid())`.
  - `workout_sessions`: select/delete owner; insert `with check (user_id = auth.uid() and exists (select 1 from routines r where r.id = routine_id and r.user_id = auth.uid()))`.
  - Index `workout_sessions(user_id, done_on)`.

- [ ] **Step 4: Apply and re-run** — `npx supabase@2 db reset` then the test command → PASS.

- [ ] **Step 5: Commit** — `feat(db): tables for exercise videos, routines and workout ticks`

---

### Task 2: Library file, validation and sync script

**Files:**
- Create: `backend/data/exercise_videos.json` (content: `[]`)
- Create: `backend/app/video_library.py`
- Create: `backend/scripts/sync_videos.py`
- Test: `backend/tests/test_video_library.py`

**Interfaces:**
- Produces:
  - `CATEGORIES, LEVELS, EQUIPMENT: tuple[str, ...]` (orders as in Global Constraints; LEVELS/EQUIPMENT ordered low→high).
  - `validate_entries(entries: list[dict]) -> list[str]` — human-readable errors, empty when valid.
  - `load_library(path: Path = DEFAULT_PATH) -> list[dict]` — raises `ValueError("\n".join(errors))` when invalid.
  - `coverage(entries: list[dict]) -> dict[tuple[str, str, str], int]` — key `(category, level, equipment)` over every combination, value = count of videos usable by a client at that level/equipment (cumulative).

- [ ] **Step 1: Write failing tests**

```python
def test_valid_entry_passes(): assert validate_entries([GOOD]) == []
def test_bad_labels_and_ids(): # bad category, level, equipment, youtube_id not 11 chars of [A-Za-z0-9_-], duration_sec <= 0, missing title/channel, duplicate youtube_id → one error each, message names the youtube_id
def test_repo_library_file_is_valid(): assert validate_entries(json.loads(DEFAULT_PATH.read_text())) == []
def test_coverage_is_cumulative(): # one beginner/none push video counts for (push, advanced, gym) and (push, beginner, none) but a gym video does not count for (push, beginner, none)
```
`GOOD = {"youtube_id": "aBcDeFgHiJk", "title": "Push-up", "channel": "Ch", "category": "push", "level": "beginner", "equipment": "none", "duration_sec": 90}`

- [ ] **Step 2: Run, expect failure** — `.venv/bin/pytest tests/test_video_library.py -v` → ImportError.
- [ ] **Step 3: Implement `app/video_library.py`.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Write `scripts/sync_videos.py`** (CLI, not unit-tested beyond its helpers):
  - loads + validates the file (exit 1 on errors);
  - `is_live(youtube_id, client) -> bool`: GET `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=<id>&format=json`; 200 → True; 401/403/404 → False; network error → abort with message (don't deactivate on a flaky network);
  - prints dead IDs and every coverage key with 0 videos for `equipment in (none, dumbbells)` and `level in (beginner, intermediate)`, categories other than `mobility`;
  - with `--apply`: service-role PostgREST (same headers as `tests/integration/conftest.py::service`) upsert `on_conflict=youtube_id` with `active=true` for live entries; PATCH `active=false` for DB rows whose `youtube_id` is missing from the file or dead.
- [ ] **Step 6: Smoke run** — `.venv/bin/python scripts/sync_videos.py` → prints "0 videos" and the gap list, exit 0.
- [ ] **Step 7: Commit** — `feat(workouts): exercise video library file, checks and sync script`

---

### Task 3: Rules — frame, rules-only plan, week start

**Files:**
- Create: `backend/app/routine_rules.py`
- Test: `backend/tests/test_routine_rules.py`

**Interfaces:**
- Consumes: `LEVELS`, `EQUIPMENT` from Task 2.
- Produces:
  - `@dataclass Inputs(days_per_week: int, level: str, equipment: str, session_min: int)`
  - `@dataclass Day(index: int, type: str, title: str, categories: list[str], warm_up: dict | None, shortlist: list[dict], max_items: int, budget_sec: int)`
  - `@dataclass Frame(inputs: Inputs, goal: str, days: list[Day], note: str | None)`
  - `class NotEnoughExercises(Exception)`
  - `split_for(days: int, level: str) -> tuple[list[str], str | None]` — day types + optional beginner note.
  - `goal_defaults(goal: str) -> dict` — `{"sets", "reps", "seconds", "rest_sec"}`.
  - `item_cost_sec(item: dict) -> int`
  - `build_frame(inputs: Inputs, goal: str, videos: list[dict]) -> Frame` — raises `NotEnoughExercises`.
  - `rules_plan(frame: Frame) -> dict` — plan JSON per spec §3.2 (without `est_min`; Task 4 finalizes).
  - `week_start(day: datetime.date) -> datetime.date` — Monday.

Pinned values:
- Split table and day-type → categories: spec §4.1. Titles: `full`→"Full body", `upper`→"Upper body", `lower`→"Lower body", `push`→"Push", `pull`→"Pull", `legs`→"Legs". Two-day beginner: types `full`, `full`, titles "Full body A", "Full body B".
- Goal defaults: lose `sets 3, reps 12, rest 45`; maintain `sets 3, reps 10, rest 60`; gain `sets 4, reps 8, rest 90`. Core and cardio items use `seconds 40`, `reps None`, same sets/rest.
- **Clarification of the spec for gain at 20 min:** if two default gain items exceed the budget, use `sets 3` for that routine (2 × 3 × 135 = 810 s ≤ 900 s).
- `item_cost_sec = sets × ((seconds or 45) + rest_sec)`. `budget_sec = (session_min − 5) × 60`. `max_items = clamp(budget_sec // default_item_cost, 2, 7)`.
- Shortlist per day: active videos in the day's categories passing level/equipment filters, ordered by `id`, capped at 20. `warm_up`: lowest-id matching `warm_up` video not used by an earlier day if possible, else lowest-id; `None` if the library has none.
- Rules-only fill: cycle over the day's categories that still have an unused video (so empty `core` is skipped and `full` days repeat `legs`/`push`), taking the lowest-id video not yet used on any day of the same type, else not used on this day; stop at `max_items` or when budget would be exceeded. Lose finisher: append one `cardio` item (`seconds 40`, 3 sets, rest 45) if one is available and fits the remaining budget. Fewer than 2 items on any day → `NotEnoughExercises`.
- `why` (rules): `lose` "A full session with a short finisher to help fat loss." when a finisher was added, else "Steady strength work to keep you moving toward your goal."; `maintain` "Balanced strength work to keep what you've built."; `gain` "Heavier sets with longer rest to build muscle."

- [ ] **Step 1: Write failing tests**

```python
def test_split_table(): # every (days, level) pair → types from spec table; beginner 5 and 6 → 4 types + exact note copy
def test_frame_respects_level_and_equipment(): # over all Inputs combos × goals with FIXTURE_LIBRARY: every shortlist/warm-up video has level <= input level and equipment <= input equipment, all active
def test_rules_plan_within_bounds(): # same combos: 2..max_items items/day, cost + 300 <= session_min*60*1.1, no repeat within a day, ranges from Global Constraints
def test_gain_20_min_uses_three_sets(): ...
def test_lose_adds_finisher_when_it_fits(): ...
def test_full_day_without_core_repeats_legs_or_push(): ...
def test_not_enough_exercises(): # library with only one push video → NotEnoughExercises for a push day
def test_rules_plan_is_deterministic(): # same inputs twice → equal plans
def test_week_start_sunday_and_monday(): # 2026-11-08 (Sun) → 2026-11-02; 2026-11-09 (Mon) → 2026-11-09
```
`FIXTURE_LIBRARY` (in the test file): for every category, level and equipment, three videos with distinct ids, all active, plus one inactive push video that must never appear.

- [ ] **Step 2: Run, expect failure** — `.venv/bin/pytest tests/test_routine_rules.py -v`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(workouts): rules that build a safe routine frame and plan`

---

### Task 4: Plan validation and finalizing

**Files:**
- Modify: `backend/app/routine_rules.py`
- Test: `backend/tests/test_routine_validate.py`

**Interfaces:**
- Produces:
  - `class PlanInvalid(Exception)` with `.reason: str` (short snake_case, stored as `fallback_reason`).
  - `validate_plan(raw: object, frame: Frame) -> dict` — returns the cleaned plan (days in frame order, each with `index`, `type`, `title` from the frame, `why`, `items` with keys `video_id, sets, reps, seconds, rest_sec`); raises `PlanInvalid`.
  - `finalize_plan(plan: dict, frame: Frame) -> dict` — prepends the warm-up item (`{"video_id", "sets": 1, "reps": None, "seconds": None, "rest_sec": 0, "warm_up": True}`) when the day has one, and sets `est_min = round((300 + sum(item_cost_sec of non-warm-up items)) / 60)`.

Reasons, one per rule in spec §4.3: `not_json_object`, `wrong_day_count`, `unknown_video`, `repeat_video`, `item_count`, `sets_range`, `reps_range`, `seconds_range`, `rest_range`, `reps_or_seconds`, `over_budget`, `why_invalid`. `bool` is not accepted as an int.

- [ ] **Step 1: Write failing tests** — `test_valid_plan_passes` (a `rules_plan` output passes unchanged in content), then one `test_rejects_<reason>` per reason asserting `exc.reason`, plus `test_finalize_adds_warm_up_and_est_min` (a 3-item maintain day → `est_min == round((300 + 3*315)/60) == 21`) and `test_finalize_without_warm_up_video`.
- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.** Validate `rules_plan` output with the same function in Task 3's bounds test too (add the assertion there).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_routine_rules.py tests/test_routine_validate.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat(workouts): validate AI plans against the frame`

---

### Task 5: AI fill with fallback

**Files:**
- Create: `backend/app/routine_ai.py`
- Test: `backend/tests/test_routine_ai.py`

**Interfaces:**
- Consumes: `Frame`, `rules_plan`, `validate_plan`, `PlanInvalid` (Tasks 3–4); `config.LLM_PROVIDER`; Gemini `_get_client()` and `_models()` from `app/gemini_client.py`; `config.OLLAMA_URL`, `config.OLLAMA_MODEL`.
- Produces:
  - `AI_TIMEOUT_SEC = 20`
  - `build_prompt(frame: Frame) -> str`
  - `async ask_model(prompt: str) -> str` — raw JSON text from the provider. Gemini: `client.aio.models.generate_content(model, contents=[prompt], config=GenerateContentConfig(response_mime_type="application/json", temperature=0.4))`, trying `_models()` in order on `errors.APIError`. Ollama: `POST /api/chat` with `format: "json"`, `think: False`, `stream: False`.
  - `async build_plan(frame: Frame) -> tuple[dict, str, str | None]` — `(plan, source, fallback_reason)`; wraps `ask_model` in `asyncio.wait_for(..., AI_TIMEOUT_SEC)`; on timeout → `"timeout"`, on any provider exception → `"provider_error"`, on `json.JSONDecodeError` → `"not_json"`, on `PlanInvalid` → its reason; fallback plan is `rules_plan(frame)`. Logs `routine_ai_fallback reason=<r>` at WARNING. Neither the prompt nor the reply is logged.

Prompt content (fixed facts, wording free): role "fitness coach choosing exercises from a fixed list"; the goal, level, equipment, minutes; for each day its index, title, `max_items`, `budget_sec`, the item-cost formula, and the shortlist as `id | title | category`; the exact JSON shape `{"days":[{"index":0,"why":"...","items":[{"video_id":1,"sets":3,"reps":10,"seconds":null,"rest_sec":60}]}]}`; the bounds from Global Constraints; "use only ids from that day's list"; "why: one plain sentence, no links, no medical claims". No warm-up in the AI output.

- [ ] **Step 1: Write failing tests** (monkeypatch `routine_ai.ask_model`):

```python
async def test_valid_ai_plan_is_used(): # ask_model returns json.dumps(rules_plan(frame) with different sets) → source "ai", reason None
async def test_invalid_ai_plan_falls_back(): # unknown video id → ("rules", "unknown_video"), plan == rules_plan(frame)
async def test_not_json_falls_back(): ...
async def test_provider_error_falls_back(): # raises RuntimeError
async def test_timeout_falls_back(monkeypatch): # AI_TIMEOUT_SEC = 0.01, ask_model sleeps 1 s → "timeout"
def test_prompt_lists_only_shortlist_ids(): # every id in prompt is in some day's shortlist; injury/medical wording absent from inputs
```
Use `pytest.mark.anyio` or `asyncio.run` consistently with `tests/test_gemini_client.py`.

- [ ] **Step 2: Run, expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(workouts): AI fills the routine frame, rules on any failure`

---

### Task 6: Store, schemas and API routes

**Files:**
- Modify: `backend/app/store.py` (new section `# ---- workout routines ----`)
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_routines.py`
- Modify: `backend/tests/integration/test_api_live.py` (one create → active → tick → untick round trip)

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces (`Store`):
  - `active_videos() -> list[dict]`; `videos_by_ids(ids: list[int]) -> dict[int, dict]` (active or not).
  - `routines_created_since(ts: datetime.datetime) -> int`
  - `create_routine(row: dict) -> dict` — PATCH the user's active routine to `active=false`, then POST `row` with `active=true`; returns the row.
  - `active_routine() -> dict | None`; `get_routine(routine_id: int) -> dict | None` (own only).
  - `sessions_between(routine_id: int, start: date, end: date) -> list[dict]` (`day_index`, `done_on`).
  - `mark_done(routine_id: int, day_index: int, day: date) -> None` — POST with `Prefer: resolution=ignore-duplicates,return=minimal`.
  - `unmark_done(routine_id: int, day_index: int, day: date) -> None`.
- Produces (`schemas.py`): `RoutineIn` (`days_per_week: int = Field(ge=2, le=6)`, `level: Literal[...]`, `equipment: Literal[...]`, `session_min: Literal[20, 30, 45, 60]`); `RoutineItemOut` (`video_id, youtube_id, title, channel, category, sets, reps, seconds, rest_sec, warm_up: bool = False, available: bool`); `RoutineDayOut` (`index, type, title, why, est_min, items`); `RoutineOut` (`id, created_at, days_per_week, level, equipment, session_min, goal, source, note: str | None, days`); `DoneOut` (`day_index, done_on`); `ActiveRoutineOut` (`routine: RoutineOut | None, done: list[DoneOut], week_start: str | None`).
- Produces (routes, spec §5): `POST /api/routines` (201), `GET /api/routines/active?today=`, `PUT|DELETE /api/routines/{routine_id}/days/{day_index}/done/{day}` (204). The beginner note is stored in `plan["note"]` and returned as `RoutineOut.note`.
- Route rules: `POST` is `async def`; every `Store` call goes through `run_in_threadpool`. Goal = `(settings or {}).get("weight_goal") or "maintain"`. Rate limit counted with `routines_created_since(now − 24 h)` ≥ 5 → 429. `NotEnoughExercises` → 409. Tick routes: routine must be the caller's **active** routine, else 404; `day_index` outside the plan → 404; `day` parsed with `parse_day`, future beyond `utc_today() + 1 day` → 400. Item `available` = the video's `active` flag.

- [ ] **Step 1: Write failing tests** with a `FakeRoutineStore` (pattern of `FakeCheckinStore` in `tests/test_checkins.py`) and `routine_ai.ask_model` monkeypatched to raise (so plans are rules-only and deterministic):

```python
def test_create_returns_expanded_routine(): # 201, days have titles, items have youtube_id/title, first item warm_up when library has one
def test_create_with_empty_library_is_409(): # detail == "Not enough exercises for these choices yet. Try other equipment."
def test_goal_defaults_to_maintain(): # get_settings → None; routine goal == "maintain", rest_sec == 60
def test_rate_limit_429(): # 5 created in last 24 h → 429 with the exact copy
def test_two_creates_leave_one_active(): ...
def test_validation_422(): # days_per_week 7, session_min 25, level "pro"
def test_active_none(): # {"routine": None, "done": [], "week_start": None}
def test_active_includes_this_weeks_done(): # ticks on Mon and previous Sun; today Wed → only Mon returned, week_start Monday
def test_inactive_video_marked_unavailable(): ...
def test_tick_and_untick_idempotent(): # PUT twice → 204, one tick; DELETE twice → 204
def test_tick_inactive_routine_404(): ...
def test_tick_bad_day_index_404(): ...
def test_tick_future_date_400(): ...
def test_beginner_six_days_gets_note(): # 4 days and note copy
```

- [ ] **Step 2: Run, expect failure** — `.venv/bin/pytest tests/test_routines.py -v`.
- [ ] **Step 3: Implement schemas, Store methods, routes.**
- [ ] **Step 4: Run** the unit suite `.venv/bin/pytest` → all PASS; then `.venv/bin/pytest -m integration tests/integration/test_api_live.py -v` (seed two videos per needed category with the `service` fixture) → PASS.
- [ ] **Step 5: Commit** — `feat(workouts): routes to build, view and tick routines`

---

### Task 7: Workout page

**Files:**
- Create: `backend/static/workout.html`, `backend/static/workout.js`
- Modify: `backend/static/nav.js` (third entry in `TABS`: `{ id: "workout", href: "/workout.html", label: "Workout", icon: <dumbbell path> }`)
- Modify: `backend/static/styles.css` (workout section, reusing `.card`, `.meal-type-options`, `.calc` dialog, `.btn*`)
- Test: `backend/tests/workout.test.js`; modify `backend/tests/nav.test.js` if it asserts the tab list.

**Interfaces:**
- Consumes: routes from Task 6; `dom.js`, `auth.js`, `nav.js` helpers as used by `progress.js`.
- Produces (pure, exported for Node like `progress.js`):
  - `itemText(item) -> string` — `"3 × 12 · rest 60 s"`; timed `"3 × 40 s · rest 45 s"`; warm-up `"Warm-up · 5 min"`.
  - `weekText(done, days) -> string` — `"This week: 1 of 3 done"` (distinct `day_index` values).
  - `doneToday(done, dayIndex, today) -> boolean`
  - `embedUrl(youtubeId) -> string | null` — `null` unless `/^[A-Za-z0-9_-]{11}$/`.
  - `builderDefaults(routine | null) -> {days_per_week, level, equipment, session_min}` — last routine's inputs, else `{3, "beginner", "none", 30}`.
  - Constants `SAFETY_STOP`, `RATE_LIMIT_FALLBACK` with the spec's copy.

Page states and copy: spec §6. Safety "Yes" never calls the API. "Building your routine…" disables the submit button until the response. "New routine" uses `confirm("This replaces your current routine.")`. Video dialog: iframe built on open with `allow="encrypted-media; picture-in-picture" allowfullscreen`, `title` = exercise title, removed on `close`; channel credit below; `available: false` items show the copy instead of ▶. Ticks call PUT/DELETE with the browser's local date (`isoDate(new Date())`) and refresh `GET /api/routines/active`. Auth/profile start-up identical to `progress.js::start`.

- [ ] **Step 1: Write failing Node tests** for each pure function, including `embedUrl("javascript:x") === null` and `weekText` counting a day ticked twice in the week once.
- [ ] **Step 2: Run, expect failure** — `node --test "tests/*.test.js"`.
- [ ] **Step 3: Implement page, script, styles, nav tab.**
- [ ] **Step 4: Run** Node tests → PASS; `.venv/bin/pytest` → PASS.
- [ ] **Step 5: Browser check** with the scratchpad Playwright approach used for the Progress fix (static server + mocked `/api/*`): safety Yes stops with the copy and sends no request; build → routine renders; ▶ opens an iframe whose `src` starts with `https://www.youtube-nocookie.com/embed/`, closing removes it; tick/untick updates "This week" text; 390 px width has no horizontal scroll; no page errors.
- [ ] **Step 6: Commit** — `feat(web): Workout tab to build and follow a routine`

---

### Task 8: Docs

**Files:**
- Modify: `README.md` (Features: "Workout routines"; Roadmap: replace M3 trainers with "Workout routines (AI + rules, YouTube demos)"; how to add videos: edit `backend/data/exercise_videos.json`, run `scripts/sync_videos.py`, then `--apply`).

- [ ] **Step 1: Update README.**
- [ ] **Step 2: Full check** — `.venv/bin/pytest && node --test "tests/*.test.js"` → all PASS.
- [ ] **Step 3: Commit** — `docs: workout routines in README`
