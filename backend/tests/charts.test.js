// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { linePoints, barHeights } = require("../static/charts.js");

const pts = (s) => s.split(" ").map((p) => p.split(",").map(Number));

test("a two-point line spans the width inside the padding", () => {
  const out = pts(linePoints([{ date: "2026-08-10", value: 72 }, { date: "2026-10-31", value: 70 }], 300, 120, 10));
  assert.equal(out.length, 2);
  assert.equal(out[0][0], 10);
  assert.equal(out[1][0], 290);
  // Higher value sits higher (smaller y); both stay inside the padding.
  assert.ok(out[0][1] < out[1][1]);
  for (const [, y] of out) assert.ok(y >= 10 && y <= 110);
});

test("points are placed by date, not by index", () => {
  const out = pts(linePoints([
    { date: "2026-10-01", value: 70 }, { date: "2026-10-02", value: 71 }, { date: "2026-10-11", value: 72 },
  ], 110, 50, 5));
  assert.deepEqual(out.map((p) => p[0]), [5, 15, 105]);
});

test("a single point or a flat line sits mid-height, single point centred", () => {
  const one = pts(linePoints([{ date: "2026-10-31", value: 70 }], 200, 100, 10));
  assert.deepEqual(one, [[100, 50]]);
  const flat = pts(linePoints([{ date: "2026-10-01", value: 70 }, { date: "2026-10-05", value: 70 }], 200, 100, 10));
  assert.deepEqual(flat.map((p) => p[1]), [50, 50]);
});

test("no values give an empty string", () => {
  assert.equal(linePoints([], 200, 100, 10), "");
});

test("bars scale to max(goal, max value) x 1.1: goal line at 1/1.1 of the height when goal is the max", () => {
  const { bars, goalY } = barHeights([1000, 2000, 0], 2000, 110);
  assert.equal(goalY, 10); // 110 - 110 / 1.1
  assert.deepEqual(bars, [50, 100, 0]);
});

test("a day over goal sets the scale and pushes the goal line down", () => {
  const { bars, goalY } = barHeights([3000, 1500], 2000, 330);
  assert.equal(bars[0], 300);
  assert.equal(goalY, 330 - 200);
});

test("no goal and no meals still give a finite scale", () => {
  const { bars, goalY } = barHeights([0, 0], 0, 100);
  assert.deepEqual(bars, [0, 0]);
  assert.ok(Number.isFinite(goalY));
});
