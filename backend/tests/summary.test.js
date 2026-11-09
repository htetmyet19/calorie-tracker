// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { mealSummary } = require("../static/summary.js");

const meal = (meal_type, total_calories) => ({ meal_type, total_calories });

test("no meals: nothing to summarise", () => {
  assert.deepEqual(mealSummary([]), { count: 0, kcal: 0, types: [], text: "" });
});

test("one meal reads as '1 meal'", () => {
  assert.deepEqual(mealSummary([meal("lunch", 520.4)]), { count: 1, kcal: 520, types: ["lunch"], text: "1 meal · 520 kcal" });
});

test("several meals: count, total in en-IN style, each type once in breakfast-lunch-dinner-snack order", () => {
  const s = mealSummary([meal("snack", 120), meal("dinner", 640), meal("breakfast", 300), meal("snack", 150), meal("lunch", 520)]);
  assert.equal(s.count, 5);
  assert.equal(s.kcal, 1730);
  assert.deepEqual(s.types, ["breakfast", "lunch", "dinner", "snack"]);
  assert.equal(s.text, "5 meals · 1,730 kcal");
});

test("large totals use Indian digit grouping like the ring", () => {
  assert.equal(mealSummary([meal("dinner", 123456)]).text, "1 meal · 1,23,456 kcal");
});
