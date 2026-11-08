# Meal advice: design

Date: 2026-11-08
Status: approved in conversation, awaiting written-spec review

## 1. Goal

After the AI estimates a meal photo, the client gets a short recommendation on how the meal fits their day, with one practical tip. It is written by the AI from facts the server computes, checked before it is shown, and never tells anyone not to eat.

### Success criteria for v1
- On the meal result screen, the client answers "Have you eaten this yet?" and sees a 1–3 sentence recommendation within ~10 s, every time (the AI may fail; the rules fallback may not).
- No message ever shown contains a blocked phrase (§4.3), a link, or a kcal number that disagrees with the server's facts. Proven by unit tests over the checker and the fallback templates.
- Saving a meal works exactly as before whether or not advice was requested, loaded, or failed.
- No meal advice text or verdict is stored. Only a request count (for the limit) and an AI-vs-fallback log line.

### Trial measures (directional; 2–3 users)
1. **Pass rate**: share of AI answers that pass the checks. Target > 90%. Logged per request as `meal_advice source=ai|rules reason=<r>`.
2. **Owner's read of ~20 real sample messages** across verdicts, goals and eaten / not yet, before release (§8).

### Non-goals for v1
Push notifications, advice history, advice on meals already saved, advice in Burmese, personalised medical or weight-loss advice.

## 2. Decisions taken in conversation

| Topic | Decision |
|---|---|
| Where | A card on the meal result screen, under the item list. Not a push notification. |
| Timing | The card asks "Have you eaten this yet?" — *Not yet* (tip about this plate) or *Already eaten* (tip about the rest of the day). |
| Who writes it | The AI (option 2), from server-computed facts and a server-computed verdict. |
| Never | "Don't eat", "skip", shaming, medical or weight-loss claims. |
| Fallback | A plain rules message from the same facts when the AI fails, is slow, or fails a check. |
| Storage | Advice is shown, not stored. |

## 3. Facts and verdict (`app/meal_advice.py`, pure)

`meal_facts(items, eaten, eaten_today_kcal, goal_kcal, goal_type) -> Facts`

| Fact | Meaning |
|---|---|
| `items` | name, portion, calories, protein_g, carbs_g, fat_g (as sent, after the client's edits) |
| `meal_kcal` | rounded sum of item calories |
| `eaten_before` | today's saved meals' calories, rounded (the meal being judged is not saved yet) |
| `goal` | `goal_kcal` from settings, else 2000 |
| `goal_type` | `weight_goal` from settings, else `maintain` |
| `left_before` | `goal − eaten_before` (may be ≤ 0) |
| `left_after` | `left_before − meal_kcal` |
| `over_by` | `max(0, −left_after)` |
| `biggest_item` | the item with the most calories, and `half_saves` = round(its calories / 2) |
| `protein_g` | rounded sum of item protein |
| `eaten` | bool |

**Verdict** (exactly one):
- `goes_over` if `left_after < 0`;
- `uses_most` if `left_before > 0` and `meal_kcal > 0.8 × left_before`;
- `fits_well` otherwise.

The verdict is a neutral label for the AI; the wording adapts to `goal_type` (going over for a `gain` goal is not framed as a problem).

## 4. Writing the advice

### 4.1 Prompt (`build_prompt(facts) -> str`)
Role: a supportive nutrition coach. Gives all facts and the verdict, says which kind of tip (`eaten=false` → about this plate: portion, swap, add protein; `eaten=true` → about the rest of today: lighter next meal, protein, water). Rules: 1–3 short sentences, plain language, use only the given numbers, at most one tip, never tell the person not to eat or to skip food, no shaming or guilt, no medical, weight-loss or "burn it off" claims, no links. Reply is plain text.

### 4.2 Call
`async ask_model(prompt) -> str`: text-only call through `LLM_PROVIDER` (Gemini: `_get_client()`/`_models()`, temperature 0.5, models tried in order; Ollama: `/api/chat`, `think: false`). `get_advice(facts)` wraps it in `asyncio.wait_for(..., 10)`.

### 4.3 Checks (`check_advice(text, facts) -> str`, raises `AdviceRejected(reason)`)
Applied to the stripped text, in order:
1. `empty` — empty after stripping;
2. `too_long` — over 320 characters;
3. `link` — contains `http`, `www.` or `.com`;
4. `blocked` — matches (case-insensitive, word-bounded) any of: `don't eat`, `do not eat`, `dont eat`, `skip`, `avoid eating`, `starv*`, `fast`, `fasting`, `burn (it|this|that) off`, `guilt*`, `bad food`, `cheat`, `punish*`, `purge`, `throw up`, `ashamed`, `shame*`;
5. `wrong_number` — any number immediately followed by `kcal` or `calories` (allowing a space, thousands separators) that is not within ±10 kcal or ±3% of one of: `meal_kcal`, `eaten_before`, `eaten_before + meal_kcal`, `goal`, `abs(left_before)`, `abs(left_after)`, `over_by`, any item's calories, `half_saves`.

### 4.3a Amendments after review (2026-11-08)
- **Normalisation before matching:** reject (`odd_characters`) invisible format characters (Unicode Cf), letters outside the Latin script and non-ASCII digits; apply NFKC; map ‘ ’ ʼ ′ to `'`; collapse whitespace.
- **Block-list additions:** stop eating, hold off, go without, eat nothing, no more food, nothing else/more, fast/fasts/fasted, burn … off, walk/work/run/sweat it off, lose weight, weight loss, naughty, sinful, pass on, leave the/your/it…, just have/drink water, disgust*, gross, lazy, finished/done eating, that's it for food, call it a day on food.
- `restrictive_tip`: eat-less wording (half, smaller, cut back/down, eat less, less of, save some…) is rejected when the verdict is `fits_well` or the goal is `gain`; "lighter" is also rejected for `gain`.
- `too_comfortable`: "comfortabl…" is rejected when the meal is over 40% of the daily goal.
- `wrong_direction`: "over/above/exceed/past/beyond … goal" is rejected unless the verdict is `goes_over`; "N kcal left/remaining" or "leaves N" is rejected when today is over.
- **Numbers:** forms `kcal(s)`, `calorie(s)`, `cal(s)`, `kilocalorie(s)`, hyphenated (`1,800-calorie`), decimals and a `k` multiplier are all checked; allowed numbers add `total_after` and drop negative `left_before`/`left_after`.
- **Food names** are single-line with control characters removed (`AdviceItem`), quoted in the prompt, and the prompt says names are data, not instructions.
- **Prompt:** at most two numbers, each with its true meaning in natural words, no percentages or goal type, 2–3 sentences under 240 characters; the tip depends on verdict and goal (no eat-less tips for `fits_well` or `gain`; after eating, water only as a last resort).

### 4.4 Fallback (`fallback_text(facts) -> str`)
Fixed templates (numbers formatted with thousands separators); every template passes `check_advice`:

| Verdict | Not yet | Already eaten |
|---|---|---|
| fits_well | "About {meal} kcal. That leaves {left_after} kcal of your {goal} kcal goal today." | same |
| uses_most | "About {meal} kcal, most of the {left_before} kcal you have left today. A smaller portion of the {biggest} would leave more room for later." | "About {meal} kcal, most of the {left_before} kcal you had left today. A lighter next meal will keep you on track." |
| goes_over | "About {meal} kcal, which would put today {over} kcal over your {goal} kcal goal. A smaller portion of the {biggest} saves about {half} kcal." | "About {meal} kcal, which puts today {over} kcal over your {goal} kcal goal. One day over is fine; tomorrow is a fresh start." |
| goes_over when goal_type is `gain` (replaces the goes_over row) | "About {meal} kcal, which puts today {over} kcal above your {goal} kcal goal. That's fine while you're building." | same |

**Amended:** when `left_before < 0` (already past the goal before this meal): "Today was already past your {goal} kcal goal; this adds about {meal} kcal." (plus " That's fine while you're building." for `gain`). `uses_most` for `gain`: "…you have/had left today. A protein-rich snack later would round out the day." The not-yet `goes_over` portion tip is omitted when `half_saves` < 25 kcal.

### 4.5 `get_advice(facts) -> (text, source, reason)`
AI text if it passes the checks (`source="ai"`, `reason=None`); otherwise the fallback with `source="rules"` and `reason` ∈ `timeout`, `provider_error`, `limit`, or a check reason. Log line `meal_advice source=… reason=…`; the prompt and reply are never logged.

## 5. API

`POST /api/meals/advice` (`require_profile`), body:
```json
{"items": [FoodItem, ...1–20], "eaten": true, "date": "YYYY-MM-DD"}
```
- `date` is the browser's local date (400 if not a real date, or more than one day ahead of UTC). Today's total = sum of `store.meals_on(date)` totals.
- Goal and goal type from `store.get_settings()`, defaults 2000 / maintain.
- Limit: `store.record_advice()` inserts into `advice_requests`; a trigger refuses the 31st in 24 hours (`advice_limit`). Over the limit the endpoint still answers 200 with the fallback (`reason="limit"`) and does not call the AI.
- Response `{text, verdict, source}`. 422 for invalid items (same `FoodItem` schema as meals).

## 6. Data

Migration `20261108000001_meal_advice.sql`: table `advice_requests (id identity, user_id → profiles cascade, created_at timestamptz default now())`, index `(user_id, created_at desc)`, RLS select/insert own, `grant insert (user_id)` only, no update/delete. `before insert` trigger `enforce_advice_limit()` — security definer, `search_path = ''`, per-user advisory lock, refuses the 31st row in 24 h with `raise exception 'advice_limit' using errcode = 'P0001'`, stamps `created_at`. Same pattern as `routine_builds`.

## 7. Screen (`static/index.html`, `static/app.js`)

- Under the analysed item list: a card "Have you eaten this yet?" with *Not yet* / *Already eaten* (tap-to-choose like the meal-type picker), a live region for the text, and a small note: "Estimates are approximate. If food or eating feels stressful, talk to a doctor or someone you trust."
- Tapping a choice disables both briefly, shows "Thinking…", then the text. Choosing the other option asks again.
- Editing, adding or removing items clears the shown advice and the choice.
- Error: "Couldn't get a suggestion. You can still save the meal." The Save button is never disabled by the card.
- Advice text is rendered with `textContent`.

## 8. Testing

- **Facts and verdict (pytest):** each boundary (exactly 80%, exactly 0 left, already over before the meal, empty day), defaults when settings are missing.
- **Checker (pytest):** one test per rejection reason; allowed numbers within ±10 / ±3%; "breakfast" is not caught by `fast`; every fallback template for every verdict × eaten × goal type passes `check_advice`.
- **get_advice (pytest):** valid AI text used; blocked / wrong number / timeout / provider error / limit → fallback with the right reason.
- **API (pytest, fake store):** happy path, defaults, date checks, 422 on bad items, limit → fallback and no AI call, nothing stored besides the count.
- **Integration:** `advice_requests` limit trigger and no-tamper rules against local Supabase.
- **Frontend:** Node tests for the card helpers; headless browser check (choose, thinking, text, edit clears, error message, Save still works).
- **Manual:** ~20 real meals through Gemini locally, messages listed for the owner to read before release.

## 9. Risks

- **Tone drift:** the AI may still write something unhelpful that passes the block-list. The owner's sample read and the pass-rate log are the guard; the block-list can grow.
- **Estimate error:** advice is only as good as the photo estimate, which is unmeasured on Burmese dishes. The card note says estimates are approximate.
- **Quota:** 30 requests per user per day, fallback beyond that.
- **Disordered eating:** mitigated by the tone rules, block-list, no stored history, and the support note; not a clinical safeguard.
