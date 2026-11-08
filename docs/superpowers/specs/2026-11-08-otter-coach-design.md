# Otter coach on the Today page — design

Date: 2026-11-08
Status: draft for review
Mockup: https://claude.ai/artifact/LAcpePLSmn9Lv6uxtimidt (approved)

## Goal

A small coach character, **Coach Ollie** (an original otter), sits in a card under the calorie
ring on the Today page and shows one short message at a time about the user's day. It makes the
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

## The card

- Placement: between the calorie ring and **Snap a meal**, as in the mockup.
- Fits the phone: no sideways scrolling at any phone width (320 px and up), and on a 390×844
  screen the ring, Ollie's card and **Snap a meal** are all visible without scrolling. The ring
  shrinks on short screens to make room; the meals list below may still scroll.
- Contents: the otter (inline SVG, five moods: happy, open, calm, sleepy, wave), the label
  "Coach Ollie", the speech bubble, an optional action link, and an **×** button.
- The otter is a `<button>` labelled "Tap Ollie for another message". The bubble text is real
  text in a `role="status"` element so screen readers announce changes.
- **×** ("Hide coach for today") hides the card until the next calendar day. Stored in
  `localStorage` as the hidden date; a failed storage read just shows the card.
- Settings panel gains a **Show coach** switch (default on), stored per device in
  `localStorage`. Per device keeps v1 free of a database change; if users want it to follow
  their account, it can move to `/api/settings` later.
- Motion (all off under `prefers-reduced-motion: reduce`, where the line shows at once):
  - Ollie blinks every few seconds (open, wave and calm eyes).
  - By mood: happy hops, sleepy sways with the "z" floating up, calm breathes, open and wave
    bob, and the paw waves in the wave mood.
  - A tap squishes and bounces Ollie and spins the whistle once.
  - A new line: the bubble pops in from Ollie's side, "…" typing dots show for
    `typingMs(text)` (300 ms + 10 ms per character, between 0.5 and 1.1 s), then the text and
    any action fade in. The live region gets the text only when it appears.
- The card refreshes whenever the day re-renders (after load, saving or deleting a meal, goal
  change). The check-in "due" fact is fetched once per page load; if that request fails, rule 1
  is skipped.

## Units

- `static/coach.js` (new, pure, Node-testable like `zone.js`):
  `coachMessage({ total, goal, goalType, mealCount, hour, checkinDue, dayOfMonth, flip })`
  → `{ mood, text, action }` where `action` is `null` or `{ label, href }`.
  Copy lives here as constants.
- `static/index.html`: the card markup with the otter SVG; `coach.js?v=2` loads before `app.js`.
- `static/app.js`: gathers the facts, renders the card, wires the tap, ×, and the
  hidden/off checks.
- `static/nav.js`: the Show coach switch.
- `static/styles.css`: card, bubble, moods (shown/hidden SVG parts by `data-mood`), motion.

## Testing

- `tests/coach.test.js`: every rule row above, rule order (check-in beats no-meals beats zones),
  gain vs lose wording, `{left}` formatting, variant by day and by tap.
- `tests/pages.test.js`: the card exists in `index.html` with the button label, status bubble
  and hide button; `coach.js` is loaded before `app.js`.
- Manual check at phone size on the local app: each mood renders, × hides until tomorrow, the
  switch turns it off, nothing shows on past days.
