// Weight units. Pure functions, no DOM, so Node can test them (tests/units.test.js).
// Weights are stored in kg with 2 decimals (numeric(6,2)). kg is typed and shown
// to 2 decimals so a value like 84.66 kg is kept exactly; lb is typed to 1 decimal,
// which 2-decimal kg is enough to show again unchanged.

const KG_PER_LB = 0.45359237;
// lb limits are the lb values whose kg stays inside 30-300 kg after rounding:
// 66.1 lb is 29.98 kg and 661.4 lb is 300.01 kg.
// step is the input's step: a finer value fails checkValidity() (stepMismatch).
const WEIGHT_RANGE = {
  kg: { min: 30, max: 300, step: 0.01 },
  lb: { min: 66.2, max: 661.3, step: 0.1 },
};
const DECIMALS = { kg: 2, lb: 1 };

const roundTo = (x, dp) => {
  const f = 10 ** dp;
  return Math.round((x + Number.EPSILON) * f) / f;
};

function toKg(value, unit) {
  return roundTo(unit === "lb" ? value * KG_PER_LB : value, 2);
}

function fromKg(kg, unit) {
  return unit === "lb" ? roundTo(kg / KG_PER_LB, DECIMALS.lb) : roundTo(kg, DECIMALS.kg);
}

// At least one decimal ("68.0 kg"); kg gets a second only when it has one ("84.66 kg").
function formatWeight(kg, unit) {
  const v = fromKg(kg, unit);
  const dp = unit === "lb" ? 1 : (Math.round(v * 100) % 10 === 0 ? 1 : 2);
  return `${v.toFixed(dp)} ${unit}`;
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
