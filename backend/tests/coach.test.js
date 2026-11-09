// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { coachMessage, COACH_LINES, typingMs, bubbleStartsOpen, coachPlaylist, ACTIONS } = require("../static/coach.js");

// A day with an even day of month shows variant A first.
const base = { total: 1240, goal: 1800, goalType: "lose", mealCount: 2, hour: 14, checkinDue: false, dayOfMonth: 8, flip: false };
const say = (over) => coachMessage({ ...base, ...over });

test("check-in day comes first, with a link to start it", () => {
  const m = say({ checkinDue: true, mealCount: 0, total: 0 });
  assert.equal(m.mood, "wave");
  assert.equal(m.text, "It's check-in day! Let's see how your week went.");
  assert.deepEqual(m.action, { label: "Start check-in", href: "/checkin.html" });
});

test("no meals yet: sleepy before 11, a nudge after", () => {
  const morning = say({ mealCount: 0, total: 0, hour: 10 });
  assert.deepEqual([morning.mood, morning.text], ["sleepy", "Morning! Snap your breakfast when you're ready."]);
  const later = say({ mealCount: 0, total: 0, hour: 11 });
  assert.deepEqual([later.mood, later.text], ["open", "Nothing logged yet today. Snap your next meal and I'll keep count."]);
  assert.equal(later.action, null);
});

test("over the goal is calm, never sad", () => {
  const m = say({ total: 2050 });
  assert.deepEqual([m.mood, m.text], ["calm", "A bit over today, and that's fine. One day doesn't change the trend."]);
});

test("near the goal: a light-food tip, or reassurance when gaining", () => {
  assert.deepEqual([say({ total: 1620 }).mood, say({ total: 1620 }).text],
    ["open", "Close to your goal. Something light if you're still hungry."]);
  assert.equal(say({ total: 1620, flip: true }).text, "180 kcal left. Fruit or yogurt fits nicely.");
  assert.equal(say({ total: 2100, goalType: "gain" }).text, "Above your goal today. That's fine while you're gaining.");
});

test("on track: kcal left, worded for the goal", () => {
  const m = say({});
  assert.deepEqual([m.mood, m.text], ["happy", "560 kcal left. Nice pace!"]);
  assert.equal(say({ goalType: "gain" }).text, "560 kcal to go. Keep fuelling!");
  assert.equal(say({ goalType: "gain", total: 1900 }).text, "Goal reached. Nice work fuelling today.");
  assert.equal(say({ goal: 3000, total: 500 }).text, "2,500 kcal left. Nice pace!");
});

test("the day picks the first variant and a tap flips to the other", () => {
  assert.equal(say({ dayOfMonth: 9 }).text, "On track, with 560 kcal to go.");
  assert.equal(say({ dayOfMonth: 9, flip: true }).text, "560 kcal left. Nice pace!");
  assert.equal(say({ flip: true }).text, "On track, with 560 kcal to go.");
});

test("every situation has two lines", () => {
  for (const [key, lines] of Object.entries(COACH_LINES)) assert.equal(lines.length, 2, key);
});

test("typing dots show longer for longer lines, within 0.5 to 1.1 s, and not at all with reduced motion", () => {
  assert.equal(typingMs("Hi", false), 500);
  assert.equal(typingMs("x".repeat(40), false), 700);
  assert.equal(typingMs("x".repeat(200), false), 1100);
  assert.equal(typingMs("x".repeat(40), true), 0);
});

test("the bubble opens for a new line, but a line folded away today stays folded", () => {
  const folded = { date: "2026-11-08", text: "560 kcal left. Nice pace!" };
  assert.equal(bubbleStartsOpen("560 kcal left. Nice pace!", folded, "2026-11-08"), false);
  assert.equal(bubbleStartsOpen("180 kcal left. Fruit or yogurt fits nicely.", folded, "2026-11-08"), true);
  assert.equal(bubbleStartsOpen("560 kcal left. Nice pace!", folded, "2026-11-09"), true);
  assert.equal(bubbleStartsOpen("560 kcal left. Nice pace!", null, "2026-11-08"), true);
});

test("Ollie goes through a mix of moves that fits the day", () => {
  assert.deepEqual(coachPlaylist("happy", 14), ["run", "stretch", "jacks", "yoga", "pushup"], "on track, daytime");
  assert.deepEqual(coachPlaylist("happy", 20), ["yoga", "stretch"], "on-track evening winds down");
  assert.deepEqual(coachPlaylist("calm", 14), ["yoga", "stretch"], "over the goal: calm, never a telling-off");
  assert.deepEqual(coachPlaylist("open", 14), ["stretch", "run", "yoga", "jacks"]);
  assert.deepEqual(coachPlaylist("wave", 23), ["wave", "stretch", "wave", "jacks"], "check-in day, even late");
  assert.deepEqual(coachPlaylist("sleepy", 9), ["sleep"], "morning with nothing logged");
  assert.deepEqual(coachPlaylist("happy", 23), ["sleep"], "late at night he only sleeps");
  assert.deepEqual(coachPlaylist("calm", 4), ["sleep"]);
});

test("no daytime mix is mostly running, and every move in a mix can be drawn", () => {
  for (const mood of ["happy", "open", "calm", "wave"]) {
    const list = coachPlaylist(mood, 14);
    assert.ok(list.filter((a) => a === "run").length <= 1, mood);
    for (const a of list) assert.ok(ACTIONS.includes(a), a);
  }
  assert.ok(ACTIONS.includes("cheer") && ACTIONS.includes("eat"));
});
