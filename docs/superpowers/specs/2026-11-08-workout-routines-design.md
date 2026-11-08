# Workout routines: design

Date: 2026-11-08
Status: approved in conversation, awaiting written-spec review
Supersedes: the trainer and training-video parts of `2026-10-31-trainer-platform-design.md` (M3). Human trainers are dropped; this feature is client + app only.

## 1. Goal

A client who wants to train, say, 3 days a week but doesn't know which exercises to do gets a weekly routine built for their body goal, made only from a curated library of YouTube exercise-demo videos, and can tick off each session.

### Success criteria for v1
- A signed-in client answers a safety question and four inputs and gets a valid routine in under ~20 s, every time (the AI may fail; the rules-only fallback may not).
- Every exercise in every routine respects the client's level, equipment and time budget. Proven by unit tests over all input combinations.
- A client can play each exercise's demo, mark a day done, undo it, and see "N of M done this week".
- No client can read another client's routines or ticks, proven at the API and database (RLS) layers.

### Trial measures (2–3 users, so directional only)
1. **Done rate** = sessions ticked ÷ sessions planned, per client per week. Target ≥ 50% in weeks 1–2.
2. **AI vs rules**: done rate split by `routines.source`, plus the owner's side-by-side review of ~10 routines generated for the same inputs. If AI routines are not clearly better, keep rules-only and report it.
3. **Fallback rate**: share of `POST /api/routines` that fell back to rules. Above ~20% means the prompt or model needs work.

### Non-goals for v1
Weekly adaptation of the routine, an admin screen, injury-specific routines, human trainers, logging weights lifted, follow-along workout videos, our own video hosting.

## 2. Decisions taken in conversation

| Topic | Decision |
|---|---|
| Who builds routines | The app (rules + AI). No human trainers. |
| Video source | Curated YouTube videos, played with the privacy-enhanced embed (`youtube-nocookie.com`). |
| Video type | Exercise demos: one exercise per video, 1–3 min, showing how to do it. |
| Client inputs | Days per week (2–6), experience (beginner / intermediate / advanced), equipment (none / dumbbells / gym), minutes per session (20 / 30 / 45 / 60). Goal comes from Settings. |
| Injuries | One yes/no safety question. "Yes" stops the flow with advice to see a doctor or physiotherapist. The answer is never stored. |
| After the routine | Client follows it, ticks "Done" per day, can ask for a new routine any time. |
| How it's built | Rules make a safe frame, the AI fills it from a shortlist, the server validates, rules-only is the fallback. |
| Adding videos | A data file in the repo + a sync script. No admin screen. |

## 3. Data

### 3.1 `exercise_videos`: the library

| Column | Type | Notes |
|---|---|---|
| `id` | bigint identity PK | |
| `youtube_id` | text unique not null | 11-char ID from the video URL |
| `title` | text not null | Exercise name shown to the client, e.g. "Push-up" |
| `channel` | text not null | Credit to the creator |
| `category` | text not null | `warm_up`, `push`, `pull`, `legs`, `core`, `cardio`, `mobility` |
| `level` | text not null | `beginner`, `intermediate`, `advanced` |
| `equipment` | text not null | `none`, `dumbbells`, `gym` |
| `duration_sec` | int not null | Length of the demo video |
| `active` | bool not null default true | false hides it from new routines; rows are never deleted |

Matching is cumulative: a client at level L may get videos at level ≤ L; a client with equipment E may get videos needing ≤ E (`none` < `dumbbells` < `gym`).

RLS: `select` for `authenticated` on all rows, active or not (the library isn't private, and old routines must still show an inactive video's title, marked "no longer available"). New routines only draw on active rows. No insert/update/delete policies: only the sync script (service role) writes.

**Source of truth:** `backend/data/exercise_videos.json`, one object per video with the columns above minus `id`. `backend/scripts/sync_videos.py`:
1. validates every entry (allowed labels, 11-char ID, no duplicate IDs);
2. checks each video is live via YouTube oEmbed (`https://www.youtube.com/oembed?url=…&format=json`, no key; 401/404 = dead or private);
3. reports coverage gaps: for each category × level × equipment, how many active videos the rules can draw on;
4. with `--apply`, upserts by `youtube_id` and sets `active = false` for rows missing from the file or dead.

Curation is a human task: the owner watches and approves every video. No video ID is ever generated or guessed by the AI or the code.

### 3.2 `routines`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint identity PK | |
| `user_id` | uuid not null → profiles | |
| `created_at` | timestamptz default now() | Used by the rate limit |
| `days_per_week`, `level`, `equipment`, `session_min` | as the inputs | What the client asked for |
| `goal` | text not null | `lose` / `maintain` / `gain` snapshot (Settings goal, `maintain` if none) |
| `source` | text not null | `ai` or `rules` |
| `fallback_reason` | text null | Why the AI result was not used (logged and kept for the fallback rate) |
| `plan` | jsonb not null | See below |
| `active` | bool not null default true | Partial unique index: one active routine per user |

`plan`:
```json
{"days": [
  {"index": 0, "type": "push", "title": "Push", "why": "Chest and shoulder work, with a short finisher for fat loss.",
   "est_min": 34,
   "items": [{"video_id": 12, "sets": 3, "reps": 12, "seconds": null, "rest_sec": 60}]}
]}
```
Each item has exactly one of `reps` or `seconds`. `est_min` is computed by the server, not the AI.

### 3.3 `workout_sessions`: the ticks

`id`, `user_id`, `routine_id` → routines (cascade), `day_index` int, `done_on` date, `created_at`. Unique `(routine_id, day_index, done_on)`.

### 3.4 `routine_builds`: the daily limit

`id`, `user_id`, `created_at`. The API inserts one row after the frame is built and before the AI call, so builds whose save fails still count. A `before insert` trigger takes a per-user advisory lock, refuses the 6th row in 24 hours (`routine_limit`, P0001) and stamps `created_at`. Clients may insert only `user_id`, read their own rows, and never update or delete them. On `routines`, owners may update only `active` and may not delete.

RLS on `routines` and `workout_sessions`: owner-only select/insert/update/delete, same pattern as meals and check-ins (`user_id = auth.uid()`), with the `routine_id` owner checked on insert.

## 4. Building a routine

### 4.1 Step 1: rules make the frame (`app/routine_rules.py`, pure)

**Split** (day types):

| Days | Beginner | Intermediate / Advanced |
|---|---|---|
| 2 | full A, full B | upper, lower |
| 3 | full ×3 | push, pull, legs |
| 4 | upper, lower, upper, lower | upper, lower, upper, lower |
| 5 | → 4-day plan, with a note | push, pull, legs, upper, lower |
| 6 | → 4-day plan, with a note | push, pull, legs ×2 |

Beginner note for 5–6 days: "Beginners recover better with rest days, so this plan has 4. You can add a walk on the other days."

**Day type → categories** (every day also starts with one `warm_up`):
- full: legs, push, pull, core
- upper: push, pull, core
- lower: legs, core
- push: push, core · pull: pull, core · legs: legs, core

**Goal defaults** (also the rules-only prescription):

| Goal | Sets × reps | Rest | Finisher |
|---|---|---|---|
| lose | 3 × 12–15 (use 12) | 45 s | one `cardio` video, 3 × 40 s, if the budget allows |
| maintain | 3 × 10 | 60 s | none |
| gain | 4 × 8 | 90 s | none |

Core and cardio items use `seconds` (30–45 s) instead of reps.

**Time model:** warm-up counts 5 min. An item costs `sets × (45 s + rest_sec)` (for timed items, `sets × (seconds + rest_sec)`). Exercises per day = as many as fit in `session_min − 5` with the goal defaults, minimum 2, maximum 7.

**Shortlist per day:** active videos in that day's categories matching level and equipment. Lower levels and lesser equipment are already included by the cumulative matching above. If a category still has no videos, widen in this order: (1) drop `core` from the day; (2) for `full` days, allow a second `legs` or `push` exercise in place of the missing category. If the day still cannot reach 2 exercises, the build fails with 409 and the message "Not enough exercises for these choices yet. Try other equipment."

**Rules-only plan** (the fallback and the baseline): fill each day by cycling through its categories, taking the lowest-`id` unused video per category so the same inputs always give the same plan; no video repeats within a day; consecutive days of the same type rotate to the next unused videos where possible. `why` is a fixed sentence per goal and day type.

### 4.2 Step 2: the AI fills the frame (`app/routine_ai.py`)

Text-only call through the existing provider setting (`LLM_PROVIDER` = gemini or ollama), reusing the client set-up, model fallbacks and timeouts in `gemini_client.py` / `ollama_client.py`. Input: the client's inputs and goal, and per day: type, exercise count range, time budget, and the shortlist (`video_id`, title, category, level). Output JSON per day: ordered items (`video_id`, `sets`, `reps` or `seconds`, `rest_sec`) and `why`. Gemini uses structured output with a response schema; Ollama uses `format: json`.

### 4.3 Step 3: the server validates (`app/routine_rules.validate_plan`, pure)

Reject the AI plan (and use rules-only, recording `fallback_reason`) if any of:
- JSON doesn't parse or doesn't match the schema; wrong number of days;
- a `video_id` is not on that day's shortlist, or repeats within a day;
- a day has fewer than 2 or more than 7 items (excluding warm-up);
- `sets` outside 1–5, `reps` outside 5–20, `seconds` outside 20–60, `rest_sec` outside 30–120, or both/neither of reps and seconds;
- a day's computed time exceeds `session_min × 1.1`;
- `why` is empty, over 140 characters, or contains a URL;
- the call errors or the whole AI step exceeds 20 s.

The warm-up item is always inserted by the server, not the AI.

## 5. API

All routes need a signed-in user with a profile (`require_profile`), as elsewhere.

- `POST /api/routines` body `{days_per_week: 2–6, level, equipment, session_min: 20|30|45|60}` → 201 with the routine (plan expanded with each video's `youtube_id`, `title`, `channel`, `category`). Deactivates the previous active routine. 409 when the library can't fill it. 429 "You've made 5 routines today. Try again tomorrow." when the user already started 5 builds in the last 24 h (see 3.4). 409 "Another routine was just built. Reload to see it." if a simultaneous build wins twice.
- `GET /api/routines/active?today=YYYY-MM-DD` → `{routine, done: [{day_index, done_on}], week_start}` for the Monday-based week containing `today`, or `{routine: null}`. Videos that are now inactive come back with `available: false`.
- `PUT /api/routines/{id}/days/{day_index}/done/{date}` → 204 (idempotent; date not in the future, at most one day ahead of UTC like check-ins).
- `DELETE` same path → 204 (idempotent; 204 if already absent).
- 404 for another user's routine or an out-of-range `day_index`.

## 6. Screens (`static/workout.html`, `workout.js`)

- Third bottom-bar tab **Workout** (after Today and Progress) in `nav.js`.
- **No routine:** intro card + "Build my routine".
- **Builder:** step 1 the safety question (Yes → message: "Please check with a doctor or physiotherapist before starting a routine." and stop; nothing is sent). Step 2 the four inputs as tap-to-choose rows, pre-filled from the last routine. Submit shows "Building your routine…" and disables the button.
- **Routine:** "This week: N of M done", then one card per day: title, `~est_min min`, the `why` line, the exercise list (`▶ Title  3 × 12 · rest 60 s`), and "Mark Day N done" / "✓ Done today" (tap again to undo). "New routine" asks to confirm replacement, then opens the builder.
- **Video:** tapping ▶ opens a dialog with a `youtube-nocookie.com/embed/<id>` iframe created on open and removed on close (nothing loads from YouTube until a tap). Channel credit under the player. Inactive videos show "This video is no longer available".
- Week counting uses the browser's local date, like Today.

## 7. Errors

| Case | Behaviour |
|---|---|
| AI error, timeout, invalid plan | Rules-only routine, `source = rules`, `fallback_reason` stored and logged. Client sees a normal routine. |
| Library can't fill a day | 409 with the "Not enough exercises…" message; client keeps their old routine. |
| Rate limit | 429 with the message above. |
| Video removed from YouTube | Sync script deactivates it; routine shows "no longer available" for that item. |
| Network failure in the browser | "Couldn't … Check your connection and try again.", as on other pages. |

## 8. Testing

- **Rules (pytest):** every combination of days × level × equipment × minutes × goal against a fixture library produces a frame and a rules-only plan that pass `validate_plan`; filters never violated; beginners never get 5–6 days; budget respected; 409 path when the fixture lacks a category.
- **Validation (pytest):** one test per rejection rule in 4.3, each confirming the fallback and its `fallback_reason`.
- **AI client:** mocked provider returning valid, invalid, slow and failing answers.
- **API (pytest + live integration):** create / active / tick / untick; idempotency; rate limit; 404 across users; RLS test that user B can't select user A's routines or ticks.
- **Library data:** a test validates `exercise_videos.json` labels and IDs; the sync script's oEmbed check runs by hand before `--apply`.
- **Frontend (node --test):** week counting, labels, builder state; headless-browser check with the API mocked, as for the Progress fix.

## 9. Rollout

1. Migration for the three tables + RLS.
2. Owner curates the first library (target 40–60 videos covering every category for none/dumbbells at beginner and intermediate) into `exercise_videos.json`; sync script checks and applies.
3. Backend + page behind no flag (trial is 2–3 users); deploy with the owner's go-ahead.
4. After 2 weeks, read the trial measures in Section 1.

## 10. Risks

- **Library coverage** decides quality more than the AI does. The sync script's gap report is the guard.
- **YouTube dependence:** videos can vanish or show ads; the sync script and `available: false` limit the damage.
- **Exercise safety:** demos come from established channels chosen by the owner; the app gives no medical advice and stops at the safety question.
- **Free-tier AI quota:** the 5-per-day limit and the rules fallback keep the feature working when the quota runs out.
