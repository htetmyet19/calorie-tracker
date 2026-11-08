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

test("done today is per day and per date", () => {
  const done = [{ day_index: 1, done_on: "2026-11-09" }];
  assert.equal(W.doneToday(done, 1, "2026-11-09"), true);
  assert.equal(W.doneToday(done, 0, "2026-11-09"), false);
  assert.equal(W.doneToday(done, 1, "2026-11-10"), false);
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
