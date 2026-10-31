// Weight units. Pure functions, no DOM, so Node can test them (tests/units.test.js).
// Weights are stored in kg with 2 decimals, which is enough for every lb value
// typed with one decimal to show again unchanged.

const KG_PER_LB = 0.45359237;
// lb limits are the lb values whose kg stays inside 30-300 kg after rounding:
// 66.1 lb is 29.98 kg and 661.4 lb is 300.01 kg.
const WEIGHT_RANGE = { kg: { min: 30, max: 300 }, lb: { min: 66.2, max: 661.3 } };

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

// A stored weight as a value for a number input in this unit, clamped into
// weightRange so the form stays valid (300 kg would otherwise show as 661.4 lb).
function inputWeight(kg, unit) {
  const { min, max } = weightRange(unit);
  return Math.min(max, Math.max(min, fromKg(kg, unit)));
}

// The message for a typed weight, or "" when it is valid (Progress and Check-in).
function weightError(raw, unit) {
  const v = Number(raw);
  if (String(raw).trim() === "" || !Number.isFinite(v)) return "Enter your weight.";
  const { min, max } = weightRange(unit);
  if (v < min || v > max) return `Enter a weight between ${min} and ${max} ${unit}.`;
  return "";
}

if (typeof module !== "undefined") {
  module.exports = { KG_PER_LB, toKg, fromKg, formatWeight, weightRange, inputWeight, weightError };
}
