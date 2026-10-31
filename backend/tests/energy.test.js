// Run from backend/: node --test tests/
const test = require("node:test");
const assert = require("node:assert/strict");
const { bmi, bmiCategory, bmr, tdee, suggestedGoal, GOAL_FLOOR } = require("../static/energy.js");

const male = { heightCm: 175, weightKg: 70, age: 30, sex: "male" };

test("bmi is kg / m^2", () => {
  assert.equal(Math.round(bmi(70, 175) * 10) / 10, 22.9);
});

test("bmi categories use WHO adult cut-offs", () => {
  assert.equal(bmiCategory(18.4), "Underweight");
  assert.equal(bmiCategory(18.5), "Healthy weight");
  assert.equal(bmiCategory(24.9), "Healthy weight");
  assert.equal(bmiCategory(25), "Overweight");
  assert.equal(bmiCategory(30), "Obesity");
});

test("bmr follows Mifflin-St Jeor", () => {
  assert.equal(bmr(male), 1648.75);
  assert.equal(bmr({ ...male, sex: "female" }), 1482.75);
  assert.equal(bmr({ ...male, sex: "unspecified" }), 1565.75); // midpoint of +5 and -161
});

test("tdee multiplies bmr by the activity factor", () => {
  assert.equal(tdee({ ...male, activity: 1.55 }), 1648.75 * 1.55);
});

test("suggested goal applies the weight goal and rounds to 50", () => {
  const p = { ...male, activity: 1.55 };
  assert.deepEqual(suggestedGoal({ ...p, goal: "lose" }), { kcal: 2050, floored: false });
  assert.deepEqual(suggestedGoal({ ...p, goal: "maintain" }), { kcal: 2550, floored: false });
  assert.deepEqual(suggestedGoal({ ...p, goal: "gain" }), { kcal: 2850, floored: false });
});

test("suggested goal never goes below the floor", () => {
  const small = { heightCm: 150, weightKg: 45, age: 70, sex: "female", activity: 1.2, goal: "lose" };
  assert.deepEqual(suggestedGoal(small), { kcal: GOAL_FLOOR, floored: true });
});
