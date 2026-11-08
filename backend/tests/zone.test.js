// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { calorieZone } = require("../static/zone.js");

const z = (total, goal = 2000, type = "lose") => calorieZone(total, goal, type).zone;

test("nothing eaten yet has no zone", () => {
  assert.deepEqual(calorieZone(0, 2000, "lose"), { zone: "empty", label: "" });
});

test("green below 85%, yellow from 85% up to the goal, red over it", () => {
  assert.equal(z(1699), "green");
  assert.equal(z(1700), "yellow");     // exactly 85%
  assert.equal(z(2000), "yellow");     // exactly at the goal
  assert.equal(z(2001), "red");
  assert.equal(z(1700, 2000, "maintain"), "yellow");
});

test("gain goals: green up to 110%, yellow to 125%, red beyond", () => {
  assert.equal(z(2200, 2000, "gain"), "green");   // exactly 110%
  assert.equal(z(2201, 2000, "gain"), "yellow");
  assert.equal(z(2500, 2000, "gain"), "yellow");  // exactly 125%
  assert.equal(z(2501, 2000, "gain"), "red");
});

test("each zone is named in words, not only by colour", () => {
  assert.equal(calorieZone(1000, 2000, "lose").label, "On track");
  assert.equal(calorieZone(1800, 2000, "lose").label, "Near your goal");
  assert.equal(calorieZone(2100, 2000, "lose").label, "Over your goal");
  assert.equal(calorieZone(2300, 2000, "gain").label, "Above your goal");
  assert.equal(calorieZone(2600, 2000, "gain").label, "Well above your goal");
});

test("a missing or unknown goal type behaves like lose/maintain", () => {
  assert.equal(z(1800, 2000, undefined), "yellow");
  assert.equal(z(1800, 2000, null), "yellow");
});
