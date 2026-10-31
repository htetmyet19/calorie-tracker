// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { settingsBody } = require("../static/nav.js");

const LOADED = {
  height_cm: 170, weight_kg: 70.5, age: 30, sex: "female", activity: 1.375,
  weight_goal: "lose", goal_kcal: 1800, weight_unit: "lb", reminders_enabled: true,
  goal_set_by: "trainer-1",
};

test("a partial save sends every field, so PUT never resets the others", () => {
  assert.deepEqual(settingsBody(LOADED, { weight_unit: "kg" }), {
    height_cm: 170, weight_kg: 70.5, age: 30, sex: "female", activity: 1.375,
    weight_goal: "lose", goal_kcal: 1800, weight_unit: "kg", reminders_enabled: true,
  });
});

test("goal_set_by is server-owned and never sent", () => {
  assert.equal("goal_set_by" in settingsBody(LOADED, { goal_kcal: 2000 }), false);
});

test("missing loaded settings fall back to the server defaults", () => {
  assert.deepEqual(settingsBody(null, { goal_kcal: 2000 }), {
    height_cm: null, weight_kg: null, age: null, sex: null, activity: null,
    weight_goal: null, goal_kcal: 2000, weight_unit: "kg", reminders_enabled: false,
  });
});

const { legacySettings } = require("../static/nav.js");

const PROFILE = JSON.stringify({ heightCm: 170, weightKg: 70.5, age: 30, sex: "female",
  activity: 1.375, goal: "lose" });

test("old browser settings map onto the settings fields", () => {
  assert.deepEqual(legacySettings(PROFILE, "1800", {}), {
    height_cm: 170, weight_kg: 70.5, age: 30, sex: "female", activity: 1.375,
    weight_goal: "lose", goal_kcal: 1800,
  });
});

test("nothing stored means nothing to move", () => {
  assert.equal(legacySettings(null, null, {}), null);
});

test("goal alone moves alone", () => {
  assert.deepEqual(legacySettings(null, "2150", {}), { goal_kcal: 2150 });
});

test("a weight already on the server is newer than the browser's copy", () => {
  assert.equal("weight_kg" in legacySettings(PROFILE, null, { weight_kg: 72 }), false);
});

test("values the server would reject are dropped, not sent", () => {
  const junk = JSON.stringify({ heightCm: 500, weightKg: "x", age: 12, sex: "other",
    activity: 1.3, goal: "lose" });
  assert.deepEqual(legacySettings(junk, "99999", {}), { weight_goal: "lose" });
  assert.deepEqual(legacySettings("{not json", "abc", {}), {});
});
