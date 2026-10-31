// Daily energy estimates for the goal calculator. Pure functions, no DOM, so Node can test them.

const GOAL_FLOOR = 1200;   // common safety floor for a self-set intake
const GOAL_DELTA = { lose: -500, maintain: 0, gain: 300 };
// Mifflin-St Jeor sex constant; "unspecified" takes the midpoint.
const SEX_CONSTANT = { male: 5, female: -161, unspecified: -78 };

function bmi(weightKg, heightCm) {
  const m = heightCm / 100;
  return weightKg / (m * m);
}

// WHO cut-offs for Asian populations (Lancet 2004): health risk rises at lower BMI
// than the general 25/30 thresholds, which matters for users in Myanmar.
function bmiCategory(value) {
  if (value < 18.5) return "Underweight";
  if (value < 23) return "Healthy weight";
  if (value < 27.5) return "Overweight";
  return "Obesity";
}

function bmr({ weightKg, heightCm, age, sex }) {
  return 10 * weightKg + 6.25 * heightCm - 5 * age + SEX_CONSTANT[sex];
}

function tdee(profile) {
  return bmr(profile) * profile.activity;
}

// Rounded to 50 to match the goal input's step.
function suggestedGoal(profile) {
  const kcal = Math.round((tdee(profile) + GOAL_DELTA[profile.goal]) / 50) * 50;
  return kcal < GOAL_FLOOR ? { kcal: GOAL_FLOOR, floored: true } : { kcal, floored: false };
}

// Each kg changes the estimate by only ~15 kcal, and weight swings 0.5-1.5 kg a
// day, so the goal is only revisited after a real change.
const GOAL_REFRESH_KG = 2;

// settings: the saved settings (goal_weight_kg is the weight the goal was worked
// out from; weight_kg the latest). Returns { changeKg, kcal } when the calculator
// now suggests a different goal, else null. A goal set by someone else (a
// trainer) or typed in by hand (no goal_weight_kg) is never revisited.
function goalRefresh(s, userId) {
  if (s.goal_kcal == null || s.goal_weight_kg == null || s.weight_kg == null) return null;
  if (s.goal_set_by && s.goal_set_by !== userId) return null;
  if ([s.height_cm, s.age, s.sex, s.activity, s.weight_goal].some((v) => v == null)) return null;
  const changeKg = Math.round((s.weight_kg - s.goal_weight_kg) * 10) / 10;
  if (Math.abs(changeKg) < GOAL_REFRESH_KG) return null;
  const { kcal } = suggestedGoal({ heightCm: s.height_cm, weightKg: s.weight_kg, age: s.age,
    sex: s.sex, activity: s.activity, goal: s.weight_goal });
  return kcal === s.goal_kcal ? null : { changeKg, kcal };
}

if (typeof module !== "undefined") {
  module.exports = { bmi, bmiCategory, bmr, tdee, suggestedGoal, GOAL_FLOOR, goalRefresh, GOAL_REFRESH_KG };
}
