# Otter coach on the Today page — design

Date: 2026-11-08
Status: draft for review
Mockup: https://claude.ai/artifact/LAcpePLSmn9Lv6uxtimidt (approved)

## Goal

A small coach character, **Coach Ollie** (an original otter), floats in the bottom-right corner of
the Today page and shows one short message at a time about the user's day. It makes the
numbers on the page easier to act on, in a friendly voice, without nagging or shaming.

Success: users read the bubble (taps on Ollie, few "hide for today" taps) and log meals on more
days per week than before. Neither is measured automatically in v1; it is judged from use.

## Out of scope (v1)

- AI-written lines and free chat. Every line is fixed copy chosen by rules.
- Workout reminders (the routine data exists; a later rule can add one).
- Any comment on body photos or weight.
- Past days: the card shows only when the Today page is on today's date.

## What Ollie says

A pure function picks the message from facts the page already has. Rules are checked in this
order; the first match wins.

| # | When | Mood | Lines (variant A / variant B) |
|---|---|---|---|
| 1 | A weekly check-in is due (`GET /api/checkins` → `due: true`) | wave | "It's check-in day! Let's see how your week went." / "Weekly check-in time: a quick weigh-in and a few photos." — plus a **Start check-in** link to `/checkin.html` |
| 2 | No meals logged today, before 11:00 local time | sleepy | "Morning! Snap your breakfast when you're ready." / "New day, fresh start. Log your first meal when you eat." |
| 3 | No meals logged today, 11:00 or later | open | "Nothing logged yet today. Snap your next meal and I'll keep count." / "Your next meal is a good place to start logging today." |
| 4 | Zone red | calm | "A bit over today, and that's fine. One day doesn't change the trend." / "Over your goal today. No stress: tomorrow's a fresh start." |
| 5 | Zone yellow, lose/maintain goal | open | "Close to your goal. Something light if you're still hungry." / "{left} kcal left. Fruit or yogurt fits nicely." |
| 6 | Zone yellow, gain goal | open | "Above your goal today. That's fine while you're gaining." / "A little over your goal. Nice work fuelling today." |
| 7 | Zone green, gain goal, at or over the goal | happy | "Goal reached. Nice work fuelling today." / "You hit your goal today. Keep it up." |
| 8 | Zone green, gain goal | happy | "{left} kcal to go. Keep fuelling!" / "{left} kcal left to reach your goal. You've got this." |
| 9 | Zone green, lose/maintain goal | happy | "{left} kcal left. Nice pace!" / "On track, with {left} kcal to go." |

- Zones are the existing `calorieZone(total, goal, goalType)` from `zone.js`. `{left}` is
  `goal − total`, rounded and formatted like the ring (`en-IN`).
- Red never shows a sad or angry otter: its mood is "calm".
- Which variant shows first is fixed per day (day of month: even → A, odd → B), so a reload
  doesn't flicker. Tapping Ollie switches to the other variant.

## Ollie in the corner (revised 2026-11-08, replaces the card under the ring)

Mockup: the "Ollie in the corner (3D look)" screen at the link above (approved).

- Ollie floats bottom-right, just above the tab bar (`position: fixed`). The bubble pops out to
  his left: the name, the line, an optional action link, and a **×** that folds it away.
- The bubble opens for each new line. **×** folds it; that exact line stays folded for the rest of
  the day, across reloads (`localStorage` `coach-folded` = `{ date, text }`, see
  `bubbleStartsOpen`). Folded, Ollie stays on his own; tapping him opens the line again.
  Tapping him while open shows the other line. "Hide for today" is gone: folding replaces it.
- Ollie is a `<button>` labelled "Coach Ollie: tap for another message" (open) or "Coach Ollie:
  show message" (folded). The line is real text in a `role="status"` element.
- Settings has a **Show coach** switch (default on), stored per device in `localStorage`.
- 3D look: shaded fur, cream and paws (radial gradients lit from the top left), a shiny nose,
  eyes and metal whistle, and a slow turn left and right in 3D. No background box: a thin dark
  outline and a soft shadow keep him readable over the meals list.
- The card refreshes whenever the day re-renders. The check-in "due" fact is fetched once per
  page load; if that request fails, rule 1 is skipped. Ollie shows only on today.

## Full-body Ollie and his moves (revised 2026-11-09)

Mockup: the "Ollie's moves (full body)" screen at the link above (approved). Ollie is drawn
whole (head, body, arms, legs, tail) as parts that animate separately; the svg's `data-action`
picks the move. Arms and legs have elbows and knees (shoulder → elbow → paw, hip → knee → foot),
so he jogs with knees up and arms pumping, his elbows bend in push-ups with his paws on the
floor, he holds the sushi in both paws, waves from the elbow and curves an arm over his head
when stretching. His tail wags, jumps squash on landing, and switching moves gives a soft pop. Cute touches: hearts float up while he eats, a sweat drop while he works out,
sparkles when he cheers. Reduced motion holds him still in the current pose.

He goes through a mix of moves that fits the day (revised 2026-11-09: one main move made him
run most of an on-track day). `coachPlaylist(mood, hour)` gives the mix; app.js shows each move for
8–12 s and starts at a random point. The mix doesn't advance in the background or with reduced
motion (he holds one pose then).

| Situation | Mix |
|---|---|
| Check-in day (beats everything) | wave, stretch, wave, jumping jacks |
| 22:00–05:00, or a morning with nothing logged | sleep |
| Over the goal (calm, never a telling-off) | yoga, stretch |
| On track, daytime | run, stretch, jumping jacks, yoga, push-ups |
| On track, from 19:00 | yoga, stretch |
| Near the goal, or nothing logged yet after 11:00 | stretch, run, yoga, jumping jacks |

Played over the mix: `eat` (a salmon nigiri, puffed cheeks, hearts) for 12 s after a meal is
saved, and `cheer` (arms up, hops, sparkles) for 1.4 s on each tap.

## Today fits the phone screen

Below 900 px wide the Today page is one screen with no page scroll: it fills the height between
the top and the tab bar, and only the meals list scrolls, in its own box (with room at the bottom
so the last meal scrolls out from under Ollie). To make room on phones:

- The ring is at most 30% of the screen height (25% when the screen is under 720 px tall), and
  the text inside it scales with the ring.
- The breakfast / lunch / dinner legend is hidden: the meals list shows the same split.
- The protein / carbs / fat boxes are tighter.
- If something extra (the goal card) makes the top too tall, the page area scrolls as a fallback
  instead of clipping.

Wide screens keep the two-column layout.

## Units

- `static/coach.js` (new, pure, Node-testable like `zone.js`):
  `coachMessage({ total, goal, goalType, mealCount, hour, checkinDue, dayOfMonth, flip })`
  → `{ mood, text, action }` where `action` is `null` or `{ label, href }`.
  Copy lives here as constants.
- `static/coach.js` also has `typingMs`, `bubbleStartsOpen`, `coachPlaylist` and
  `ACTIONS`.
- `static/index.html`: the corner markup with the full-body otter SVG; `coach.js?v=2` loads
  before `app.js`.
- `static/app.js`: gathers the facts, renders the card, wires the tap, ×, and the
  hidden/off checks.
- `static/nav.js`: the Show coach switch.
- `static/styles.css`: the corner, the bubble, and each move (`.ollie[data-action=…]`).

## Testing

- `tests/coach.test.js`: every rule row above, rule order (check-in beats no-meals beats zones),
  gain vs lose wording, `{left}` formatting, variant by day and by tap.
- `tests/coach.test.js` also covers the main move for each mood and hour, and the random extras.
- `tests/pages.test.js`: the corner markup (button label, status bubble, fold button), script
  order, the phone layout, and a pose and style rule for every move in `ACTIONS`.
- Manual check at phone size on the local app: each mood renders, × hides until tomorrow, the
  switch turns it off, nothing shows on past days.
