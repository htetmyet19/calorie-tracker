// Weight units. Pure functions, no DOM, so Node can test them (tests/units.test.js).
// Weights are stored in kg with 2 decimals, which is enough for every lb value
// typed with one decimal to show again unchanged.

const KG_PER_LB = 0.45359237;
const WEIGHT_RANGE = { kg: { min: 30, max: 300 }, lb: { min: 66, max: 661 } };

const roundTo = (x, dp) => {
  const f = 10 ** dp;
  return Math.round((x + Number.EPSILON) * f) / f;
};

function toKg(value, unit) {
  return roundTo(unit === "lb" ? value * KG_PER_LB : value, 2);
}

function fromKg(kg, unit) {
  return roundTo(unit === "lb" ? kg / KG_PER_LB : kg, 1);
}

function formatWeight(kg, unit) {
  return `${fromKg(kg, unit).toFixed(1)} ${unit}`;
}

function weightRange(unit) {
  return { ...WEIGHT_RANGE[unit === "lb" ? "lb" : "kg"] };
}

if (typeof module !== "undefined") {
  module.exports = { KG_PER_LB, toKg, fromKg, formatWeight, weightRange };
}
