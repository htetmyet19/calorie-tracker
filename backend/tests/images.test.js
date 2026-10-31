// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { fitWithin } = require("../static/images.js");

test("fitWithin scales the longest side down to maxSide", () => {
  assert.deepEqual(fitWithin(4000, 3000, 1600), { width: 1600, height: 1200 });
  assert.deepEqual(fitWithin(3000, 4000, 800), { width: 600, height: 800 });
});

test("fitWithin never upscales", () => {
  assert.deepEqual(fitWithin(500, 400, 1600), { width: 500, height: 400 });
  assert.deepEqual(fitWithin(1600, 900, 1600), { width: 1600, height: 900 });
});

test("fitWithin returns whole pixels, at least 1", () => {
  assert.deepEqual(fitWithin(4032, 3023, 800), { width: 800, height: 600 });
  assert.deepEqual(fitWithin(10000, 3, 800), { width: 800, height: 1 });
});
