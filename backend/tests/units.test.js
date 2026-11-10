// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { KG_PER_LB, toKg, fromKg, formatWeight, weightRange, inputWeight } = require("../static/units.js");

test("one pound is exactly 0.45359237 kg", () => {
  assert.equal(KG_PER_LB, 0.45359237);
});

test("toKg rounds to 2 dp; fromKg keeps 2 dp in kg and 1 dp in lb", () => {
  assert.equal(toKg(150, "lb"), 68.04);
  assert.equal(fromKg(68.04, "lb"), 150);
  assert.equal(toKg(84.66, "kg"), 84.66);
  assert.equal(fromKg(84.66, "kg"), 84.66);
  assert.equal(fromKg(70.55, "kg"), 70.55);
});

test("every kg value 30.00-300.00 survives a save and reload unchanged", () => {
  const bad = [];
  for (let hundredths = 3000; hundredths <= 30000; hundredths++) {
    const v = hundredths / 100;
    const back = fromKg(toKg(v, "kg"), "kg");
    if (Math.round(back * 100) !== hundredths) bad.push([v, back]);
  }
  assert.deepEqual(bad, []);
});

test("every lb value 66.2-661.3 survives a save and reload unchanged", () => {
  // Tenths as integers so the loop itself adds no float noise.
  const bad = [];
  for (let tenths = 662; tenths <= 6613; tenths++) {
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

test("formatWeight shows kg to 2 dp when needed (at least 1) and lb to 1 dp", () => {
  assert.equal(formatWeight(68, "kg"), "68.0 kg");
  assert.equal(formatWeight(70.5, "kg"), "70.5 kg");
  assert.equal(formatWeight(84.66, "kg"), "84.66 kg");
  assert.equal(formatWeight(68.04, "lb"), "150.0 lb");
});

test("weight ranges per unit", () => {
  assert.deepEqual(weightRange("kg"), { min: 30, max: 300, step: 0.01 });
  assert.deepEqual(weightRange("lb"), { min: 66.2, max: 661.3, step: 0.1 });
});

test("every lb value in range converts inside the server's 30-300 kg", () => {
  for (let tenths = 662; tenths <= 6613; tenths++) {
    const kg = toKg(tenths / 10, "lb");
    assert.ok(kg >= 30 && kg <= 300, `${tenths / 10} lb -> ${kg} kg`);
  }
  assert.ok(toKg(66.1, "lb") < 30 && toKg(661.4, "lb") > 300); // why the range is 66.2-661.3
});

test("inputWeight clamps a stored weight into the input's range", () => {
  assert.equal(inputWeight(300, "lb"), 661.3);   // 661.4 lb would fail the input's max
  assert.equal(inputWeight(30, "lb"), 66.2);     // 66.1 lb would fail the input's min
  assert.equal(inputWeight(68.04, "lb"), 150);
  assert.equal(inputWeight(300, "kg"), 300);
  assert.equal(inputWeight(70.55, "kg"), 70.55);
  assert.equal(inputWeight(84.66, "kg"), 84.66);
});
