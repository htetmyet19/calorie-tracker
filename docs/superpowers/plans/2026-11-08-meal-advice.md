# Meal Advice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a meal is estimated, the client answers "Have you eaten this yet?" and sees a short, checked, AI-written recommendation on how the meal fits their day.

**Architecture:** `app/meal_advice.py` computes facts and a verdict (pure), builds the prompt, checks the AI's text (pure) and falls back to fixed templates; `POST /api/meals/advice` gathers today's total and settings, counts the request in `advice_requests` (DB trigger limit) and returns `{text, verdict, source}`; `static/advice.js` renders the card on the result screen. Nothing about the advice is stored.

**Tech Stack:** FastAPI, Pydantic v2, httpx, Supabase Postgres (PostgREST, RLS, plpgsql trigger), google-genai / Ollama, plain JS, pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-08-meal-advice-design.md`

## Global Constraints

- Run from `backend/`: `.venv/bin/pytest`, `.venv/bin/pytest -m integration` (local Supabase is running), `node --test "tests/*.test.js"`.
- Verdicts exactly `fits_well`, `uses_most`, `goes_over`; `uses_most` threshold `meal_kcal > 0.8 × left_before` with `left_before > 0`.
- Defaults: goal 2000 kcal, goal type `maintain`.
- AI timeout 10 s; text limit 320 characters; limit 30 requests per user per rolling 24 h; over the limit → fallback, HTTP 200, reason `limit`, no AI call.
- Number tolerance: ±10 kcal or ±3%.
- Copy fixed by the spec: card question "Have you eaten this yet?", buttons "Not yet" / "Already eaten", note "Estimates are approximate. If food or eating feels stressful, talk to a doctor or someone you trust.", error "Couldn't get a suggestion. You can still save the meal.", and the fallback templates in spec §4.4 verbatim.
- Never store advice text or verdict. Never log the prompt or reply. Log line format `meal_advice source=<s> reason=<r>`.
- Commits: conventional messages, no Claude co-author or "Generated with" lines.

## Review Focus

1. **A meal of 0 kcal or only an edited-to-zero item list** (all calories 0): advice must still return a valid fallback, not divide by zero or crash. → Task 1 `test_zero_kcal_meal`.
2. **Day already over goal before this meal** (`left_before ≤ 0`): verdict `goes_over`, and the fallback's numbers pass the checker. → Task 1 `test_already_over_before_meal` and Task 2 `test_every_fallback_passes_checks`.
3. **AI writes numbers with separators or "calories"** ("1,050 calories"): accepted when right, rejected when wrong. → Task 2 `test_number_formats`.
4. **Client edits items after getting advice:** the old text disappears so it never describes a different meal. → Task 5 browser check step and `test_card_state_resets`.
5. **Advice request fails or is slow:** Save stays enabled and works. → Task 5 browser check step.

---

### Task 1: Facts and verdict

**Files:**
- Create: `backend/app/meal_advice.py`
- Test: `backend/tests/test_meal_advice.py`

**Interfaces:**
- Produces:
  - `@dataclass Facts(items: list[dict], eaten: bool, meal_kcal: int, eaten_before: int, goal: int, goal_type: str, left_before: int, left_after: int, over_by: int, biggest: str, half_saves: int, protein_g: int, verdict: str)`
  - `meal_facts(items: list[dict], eaten: bool, eaten_today_kcal: float, goal_kcal: int | None, goal_type: str | None) -> Facts` — rounding to int with `round()`; `biggest` = name of the item with most calories (first on ties; `""` for an empty list), `half_saves = round(its calories / 2)`.

- [ ] **Step 1: Failing tests** — `test_fits_well`, `test_uses_most_boundary` (left_before 1000: meal 800 → `fits_well`, 801 → `uses_most`), `test_goes_over` (over_by correct), `test_zero_left_after_is_not_over` (left_after 0 → not `goes_over`), `test_already_over_before_meal` (eaten_before 2100, goal 2000 → `goes_over`, over_by = 100 + meal), `test_defaults` (None, None → 2000, `maintain`), `test_zero_kcal_meal` (items all 0 → `fits_well`, half_saves 0), `test_biggest_item`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_meal_advice.py -q` → ImportError.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(advice): meal facts and verdict`

### Task 2: Checker and fallback templates

**Files:**
- Modify: `backend/app/meal_advice.py`
- Test: `backend/tests/test_meal_advice_check.py`

**Interfaces:**
- Consumes: `Facts`, `meal_facts` (Task 1).
- Produces:
  - `class AdviceRejected(Exception)` with `.reason` in `empty|too_long|link|blocked|wrong_number`.
  - `check_advice(text: str, facts: Facts) -> str` — returns the stripped text.
  - `fallback_text(facts: Facts) -> str` — spec §4.4 templates verbatim, numbers as `f"{n:,}"`.
  - `BLOCKED: tuple[str, ...]` regex patterns from spec §4.3.

Number rule: find `(\d[\d,]*)\s*(kcal|calories)\b` case-insensitive; strip commas; allowed set per spec §4.3; tolerance `max(10, 0.03 × target)`.

- [ ] **Step 1: Failing tests** — one `test_rejects_<reason>` per reason (blocked cases: "don't eat", "Do not eat", "skip the rice", "starving", "try fasting", "burn it off", "feel guilty", "cheat meal", "shame"); `test_breakfast_is_not_fast`; `test_number_formats` ("1,050 calories" accepted when meal_kcal 1050, "1,200 kcal" rejected when no fact is near); `test_tolerance` (±10 and ±3% accepted, outside rejected); `test_numbers_without_unit_ignored` ("2 eggs", "30 g protein"); `test_every_fallback_passes_checks` (verdict × eaten × goal_type, including already-over and zero-kcal facts); `test_fallback_copy` (exact strings for `goes_over` eaten / not eaten, maintain and gain).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_meal_advice.py tests/test_meal_advice_check.py -q` → PASS.
- [ ] **Step 5: Commit** — `feat(advice): check AI advice and fixed fallback messages`

### Task 3: Prompt and AI call with fallback

**Files:**
- Modify: `backend/app/meal_advice.py`
- Test: `backend/tests/test_meal_advice_ai.py`

**Interfaces:**
- Consumes: Tasks 1–2; `gemini_client._get_client`, `gemini_client._models`; `config.LLM_PROVIDER`, `config.OLLAMA_URL`, `config.OLLAMA_MODEL`.
- Produces:
  - `ADVICE_TIMEOUT_SEC = 10`
  - `build_prompt(facts: Facts) -> str` (content per spec §4.1)
  - `async ask_model(prompt: str) -> str` (Gemini temperature 0.5, `response_mime_type="text/plain"`; Ollama `/api/chat`, `think: False`, `stream: False`)
  - `async get_advice(facts: Facts, allow_ai: bool = True) -> tuple[str, str, str | None]` — `(text, source, reason)`; `allow_ai=False` → fallback with reason `limit` and no model call.

- [ ] **Step 1: Failing tests** (monkeypatch `meal_advice.ask_model`): `test_good_ai_text_used`, `test_blocked_text_falls_back` (reason `blocked`), `test_wrong_number_falls_back`, `test_timeout_falls_back` (`ADVICE_TIMEOUT_SEC = 0.01`), `test_provider_error_falls_back`, `test_limit_skips_ai` (fake records no call), `test_prompt_has_facts_and_rules` (contains meal_kcal, goal, verdict, "eaten" wording for each case, the never-tell-not-to-eat rule), `test_log_line_without_text` (caplog has `meal_advice source=rules reason=blocked`, not the reply).
- [ ] **Step 2: Run** → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `feat(advice): AI writes the advice, fixed message on any failure`

### Task 4: Limit table, store and route

**Files:**
- Create: `backend/supabase/migrations/20261108000001_meal_advice.sql`
- Modify: `backend/app/store.py`, `backend/app/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_meal_advice_api.py`, `backend/tests/test_store_routines.py` (one store request test), `backend/tests/integration/test_rls_advice.py`

**Interfaces:**
- Consumes: Tasks 1–3; `store.meals_on(date)`, `store.get_settings()`; `parse_day`, `utc_today` in `main.py`.
- Produces: `Store.record_advice() -> bool` (True when counted, False when the trigger refuses with `advice_limit`); schemas `AdviceIn(items: list[FoodItem] = Field(min_length=1, max_length=20), eaten: bool, date: str)`, `AdviceOut(text: str, verdict: str, source: str)`; route `POST /api/meals/advice` (`async def`, store calls via `run_in_threadpool`).
- Migration: spec §6, same shape as `routine_builds` in `20261108000000_workout_routines.sql`, function `enforce_advice_limit()`, limit 30.

- [ ] **Step 1: Failing tests** — API with a fake store and `ask_model` monkeypatched: `test_advice_happy_path` (uses today's meals total and settings), `test_advice_defaults_without_settings`, `test_advice_date_checks` (bad date 400, two days ahead 400), `test_advice_bad_items_422` (empty list, 21 items), `test_over_limit_returns_fallback_without_ai`; store: `test_record_advice_limit` (MockTransport 201 → True; 400 `advice_limit` → False); integration: `test_advice_limit_and_no_tampering` (30 inserts ok, 31st 400 `advice_limit`; no update/delete; no backdated insert).
- [ ] **Step 2: Run** unit tests → fail; apply migration `npx supabase@2 migration up --local`; run integration test → fail before the migration exists / pass after.
- [ ] **Step 3: Implement** migration, store method, schemas, route.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` and `.venv/bin/pytest -m integration -q` → all PASS.
- [ ] **Step 5: Commit** — `feat(advice): advice endpoint with a per-user daily limit`

### Task 5: The card on the result screen

**Files:**
- Create: `backend/static/advice.js`
- Modify: `backend/static/index.html` (card under `#warnings`, script tag before `app.js`), `backend/static/app.js` (call `resetAdvice()` from `renderItems()`, item field changes, `resetLogger()`; pass items getter), `backend/static/styles.css`
- Test: `backend/tests/advice.test.js`

**Interfaces:**
- Consumes: `POST /api/meals/advice`; `api`, `isoDate`, `el`, `$` from `dom.js`/`auth.js`.
- Produces (pure, exported for Node): `ADVICE_NOTE`, `ADVICE_ERROR`, `adviceBody(items, eaten, today) -> {items, eaten, date}` (items stripped to `FoodItem` fields), `cardState()` / reducer `nextCardState(state, event)` with events `choose(eaten)`, `loaded(text)`, `failed`, `reset` → `{choice, status: "idle"|"loading"|"shown"|"error", text}`.
- Browser part: `initAdviceCard(getItems)`, `resetAdvice()`. Stale responses (a reset or another choice since the request) are ignored.

- [ ] **Step 1: Failing Node tests** — `test_body_strips_fields`, `test_card_state_resets` (shown → reset → idle with no text), `test_stale_choice_ignored`, copy constants.
- [ ] **Step 2: Run** `node --test "tests/*.test.js"` → fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** Node and pytest suites → PASS.
- [ ] **Step 5: Browser check** (real local app at :8000 with a throwaway user, `ask_model` real Gemini): estimate a meal from a test photo or inject items, choose each option, see text; edit an item → advice cleared; with the advice route forced to fail (route mocked in Playwright) → error copy and Save still saves; 390 px, no overflow, no page errors.
- [ ] **Step 6: Commit** — `feat(web): meal advice card on the result screen`

### Task 6: Sample read and docs

**Files:**
- Modify: `README.md` (Features: a line on meal advice and its guardrails)
- Create (scratchpad, not committed): sample report of ~20 real Gemini messages

- [ ] **Step 1:** Generate ~20 advice texts through the local route with varied facts (3 verdicts × eaten / not yet × lose / maintain / gain, plus already-over and Burmese dishes such as mohinga, laphet thoke, rice with curries). Record text, source, reason.
- [ ] **Step 2:** Update README; run full suites → PASS.
- [ ] **Step 3: Commit** — `docs: meal advice in README`
