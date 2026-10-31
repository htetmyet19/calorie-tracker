// Run from backend/: node --test tests/
const test = require("node:test");
const assert = require("node:assert/strict");
const { bmi, bmiCategory, bmr, tdee, suggestedGoal, GOAL_FLOOR } = require("../static/energy.js");

const male = { heightCm: 175, weightKg: 70, age: 30, sex: "male" };

test("bmi is kg / m^2", () => {
  assert.equal(Math.round(bmi(70, 175) * 10) / 10, 22.9);
});

test("bmi categories use WHO cut-offs for Asian populations", () => {
  assert.equal(bmiCategory(18.4), "Underweight");
  assert.equal(bmiCategory(18.5), "Healthy weight");
  assert.equal(bmiCategory(22.9), "Healthy weight");
  assert.equal(bmiCategory(23), "Overweight");
  assert.equal(bmiCategory(27.4), "Overweight");
  assert.equal(bmiCategory(27.5), "Obesity");
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

const { goalRefresh, GOAL_REFRESH_KG } = require("../static/energy.js");

// Goal set at 74 kg: suggestedGoal gives 1,800 kcal for this profile.
const SET = { height_cm: 170, age: 30, sex: "female", activity: 1.55, weight_goal: "lose",
  goal_kcal: 1800, goal_weight_kg: 74, weight_kg: 74, goal_set_by: "me" };

test("goal refresh triggers at 2 kg", () => assert.equal(GOAL_REFRESH_KG, 2));

test("goal refresh suggests a new goal after a 2 kg+ change", () => {
  assert.deepEqual(goalRefresh({ ...SET, weight_kg: 71 }, "me"), { changeKg: -3, kcal: 1750 });
});

test("goal refresh counts exactly 2 kg despite float rounding", () => {
  // 72.4 - 70.4 is 1.99999... in floating point
  assert.deepEqual(goalRefresh({ ...SET, goal_weight_kg: 72.4, weight_kg: 70.4 }, "me"),
    { changeKg: -2, kcal: 1750 });
});

test("goal refresh stays quiet under 2 kg", () => {
  assert.equal(goalRefresh({ ...SET, weight_kg: 72.1 }, "me"), null);
});

test("goal refresh stays quiet when the new suggestion equals the goal", () => {
  assert.equal(goalRefresh({ ...SET, weight_kg: 72 }, "me"), null); // still rounds to 1,800
});

test("goal refresh never touches a trainer's goal", () => {
  assert.equal(goalRefresh({ ...SET, weight_kg: 71, goal_set_by: "trainer-1" }, "me"), null);
  assert.deepEqual(goalRefresh({ ...SET, weight_kg: 71, goal_set_by: null }, "me"),
    { changeKg: -3, kcal: 1750 });
});

test("goal refresh needs the goal's weight and every calculator detail", () => {
  assert.equal(goalRefresh({ ...SET, weight_kg: 71, goal_weight_kg: null }, "me"), null);
  assert.equal(goalRefresh({ ...SET, weight_kg: 71, age: null }, "me"), null);
  assert.equal(goalRefresh({ ...SET, weight_kg: null }, "me"), null);
  assert.equal(goalRefresh({ ...SET, weight_kg: 71, goal_kcal: null }, "me"), null);
});

test("goal refresh also follows a weight gain", () => {
  assert.deepEqual(goalRefresh({ ...SET, weight_kg: 77 }, "me"), { changeKg: 3, kcal: 1850 });
});
