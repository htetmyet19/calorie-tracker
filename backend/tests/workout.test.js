// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
Object.assign(globalThis, require("../static/dom.js"));
const W = require("../static/workout.js");

test("exercise line: reps, timed and warm-up", () => {
  assert.equal(W.itemText({ sets: 3, reps: 12, seconds: null, rest_sec: 60 }), "3 × 12 · rest 60 s");
  assert.equal(W.itemText({ sets: 3, reps: null, seconds: 40, rest_sec: 45 }), "3 × 40 s · rest 45 s");
  assert.equal(W.itemText({ sets: 1, reps: null, seconds: null, rest_sec: 0, warm_up: true }), "Warm-up · 5 min");
});

test("week text counts each day once", () => {
  const done = [{ day_index: 0, done_on: "2026-11-09" }, { day_index: 0, done_on: "2026-11-10" },
    { day_index: 2, done_on: "2026-11-11" }];
  assert.equal(W.weekText(done, 3), "This week: 2 of 3 done");
  assert.equal(W.weekText([], 4), "This week: 0 of 4 done");
});

test("a day stays done for the rest of the week, with the date it was done", () => {
  const done = [{ day_index: 1, done_on: "2026-11-09" }, { day_index: 1, done_on: "2026-11-11" }];
  assert.equal(W.doneDate(done, 1), "2026-11-11");   // latest tick, so undo removes that one
  assert.equal(W.doneDate(done, 0), null);
  assert.equal(W.doneLabel("2026-11-11", "2026-11-11"), "✓ Done today");
  assert.equal(W.doneLabel("2026-11-09", "2026-11-11"), "✓ Done Mon");
});

test("embed URL only for real YouTube IDs, privacy-enhanced host", () => {
  assert.equal(W.embedUrl("aBcDeFgHiJk"), "https://www.youtube-nocookie.com/embed/aBcDeFgHiJk?rel=0");
  for (const bad of ["javascript:x", "", "short", "aBcDeFgHiJk/../x", null, "aBcDeFgHiJ?"]) {
    assert.equal(W.embedUrl(bad), null, String(bad));
  }
});

test("builder defaults: last routine's inputs, else beginner basics", () => {
  assert.deepEqual(W.builderDefaults(null), { days_per_week: 3, level: "beginner", equipment: "none", session_min: 30 });
  const last = { days_per_week: 5, level: "advanced", equipment: "gym", session_min: 60, goal: "gain" };
  assert.deepEqual(W.builderDefaults(last), { days_per_week: 5, level: "advanced", equipment: "gym", session_min: 60 });
});

test("copy fixed by the spec", () => {
  assert.equal(W.SAFETY_STOP, "Please check with a doctor or physiotherapist before starting a routine.");
  assert.equal(W.UNAVAILABLE, "This video is no longer available");
  assert.equal(W.REPLACE_CONFIRM, "This replaces your current routine.");
});

test("the bottom bar links to the Workout page", () => {
  const nav = fs.readFileSync(path.join(__dirname, "..", "static", "nav.js"), "utf8");
  assert.match(nav, /id: "workout", href: "\/workout\.html", label: "Workout"/);
});

test("the first day not done this week starts open; none when all are done", () => {
  const days = [{ index: 0 }, { index: 1 }, { index: 2 }];
  assert.equal(W.firstOpenDay(days, []), 0);
  assert.equal(W.firstOpenDay(days, [{ day_index: 0, done_on: "2026-11-09" }]), 1);
  assert.equal(W.firstOpenDay(days, [{ day_index: 0, done_on: "2026-11-09" }, { day_index: 2, done_on: "2026-11-09" }]), 1);
  assert.equal(W.firstOpenDay(days, [0, 1, 2].map((i) => ({ day_index: i, done_on: "2026-11-09" }))), null);
  assert.equal(W.firstOpenDay([], []), null);
});

test("each day folds to a row: a button with an open/folded state that shows or hides the details", () => {
  const js = fs.readFileSync(path.join(__dirname, "..", "static", "workout.js"), "utf8");
  const card = js.slice(js.indexOf("function dayCard"), js.indexOf("function exerciseRow"));
  assert.match(card, /el\("button", \{ type: "button", className: "day-toggle"/, "the row is a real button");
  assert.match(card, /setAttribute\("aria-expanded"/, "it says whether the day is open");
  assert.match(card, /setAttribute\("aria-controls"/, "it points at the details it opens");
  assert.match(card, /className: "day-body"/, "the details sit in their own part");
  assert.match(card, /\.hidden = !open/, "folded days hide their details");
  assert.match(js, /openDays/, "open days are remembered while the page is open");
  const css = fs.readFileSync(path.join(__dirname, "..", "static", "styles.css"), "utf8");
  assert.match(css, /\.day-toggle\[aria-expanded="true"\] \.day-chev\s*\{[^}]*rotate/, "the arrow turns when open");
  assert.match(css, /prefers-reduced-motion: reduce\)\s*\{[^}]*\.day-chev/, "reduced motion: no turn animation");
});
