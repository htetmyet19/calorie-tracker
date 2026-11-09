// One-line summary of a day's meals for the phone "Meals" button. Pure, so Node can test it
// (tests/summary.test.js).

const SUMMARY_ORDER = ["breakfast", "lunch", "dinner", "snack"];

// meals: [{ meal_type, total_calories }] -> { count, kcal, types (each logged type once, in
// day order), text ("5 meals · 1,730 kcal", "" when there are none) }
function mealSummary(meals) {
  const count = meals.length;
  const kcal = Math.round(meals.reduce((s, m) => s + (m.total_calories || 0), 0));
  const types = SUMMARY_ORDER.filter((t) => meals.some((m) => m.meal_type === t));
  const text = count ? `${count} ${count === 1 ? "meal" : "meals"} · ${kcal.toLocaleString("en-IN")} kcal` : "";
  return { count, kcal, types, text };
}

if (typeof module !== "undefined") module.exports = { mealSummary };
