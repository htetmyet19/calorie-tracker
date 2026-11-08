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

const { ringColor, ZONE_RGB } = require("../static/zone.js");
const rgb = (c) => `rgb(${c.join(", ")})`;

test("ring colour is green early, yellow near the goal, red past it", () => {
  assert.equal(ringColor(0, "lose"), rgb(ZONE_RGB.green));
  assert.equal(ringColor(0.5, "lose"), rgb(ZONE_RGB.green));
  assert.equal(ringColor(0.85, "lose"), rgb(ZONE_RGB.yellow));
  assert.equal(ringColor(1.0, "maintain"), rgb(ZONE_RGB.yellow));
  assert.equal(ringColor(1.05, "lose"), rgb(ZONE_RGB.red));
  assert.equal(ringColor(1.6, "lose"), rgb(ZONE_RGB.red));
});

test("between stops the colour blends", () => {
  const mid = ringColor(0.675, "lose");          // halfway from 50% to 85%
  const expect = ZONE_RGB.green.map((g, i) => Math.round((g + ZONE_RGB.yellow[i]) / 2));
  assert.equal(mid, rgb(expect));
});

test("gain goals blend later: green to 80%, yellow by 110%, red past 125%", () => {
  assert.equal(ringColor(0.8, "gain"), rgb(ZONE_RGB.green));
  assert.equal(ringColor(1.1, "gain"), rgb(ZONE_RGB.yellow));
  assert.equal(ringColor(1.2, "gain"), rgb(ZONE_RGB.yellow));
  assert.equal(ringColor(1.25, "gain"), rgb(ZONE_RGB.red));
});
