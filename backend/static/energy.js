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

if (typeof module !== "undefined") {
  module.exports = { bmi, bmiCategory, bmr, tdee, suggestedGoal, GOAL_FLOOR };
}
