// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { KG_PER_LB, toKg, fromKg, formatWeight, weightRange } = require("../static/units.js");

test("one pound is exactly 0.45359237 kg", () => {
  assert.equal(KG_PER_LB, 0.45359237);
});

test("toKg rounds to 2 dp; fromKg rounds to 1 dp", () => {
  assert.equal(toKg(150, "lb"), 68.04);
  assert.equal(fromKg(68.04, "lb"), 150);
  assert.equal(toKg(70.55, "kg"), 70.55);
  assert.equal(fromKg(70.55, "kg"), 70.6);
});

test("every lb value 66.0-661.0 survives a save and reload unchanged", () => {
  // Tenths as integers so the loop itself adds no float noise.
  const bad = [];
  for (let tenths = 660; tenths <= 6610; tenths++) {
    const v = tenths / 10;
    const back = fromKg(toKg(v, "lb"), "lb");
    if (Math.round(back * 10) !== tenths) bad.push([v, back]);
  }
  assert.deepEqual(bad, []);
});

test("every kg value 30.0-300.0 survives a save and reload unchanged", () => {
  for (let tenths = 300; tenths <= 3000; tenths++) {
    assert.equal(Math.round(fromKg(toKg(tenths / 10, "kg"), "kg") * 10), tenths);
  }
});

test("formatWeight shows one decimal and the unit", () => {
  assert.equal(formatWeight(68, "kg"), "68.0 kg");
  assert.equal(formatWeight(68.04, "lb"), "150.0 lb");
});

test("weight ranges per unit", () => {
  assert.deepEqual(weightRange("kg"), { min: 30, max: 300 });
  assert.deepEqual(weightRange("lb"), { min: 66, max: 661 });
});
