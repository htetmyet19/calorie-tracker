// Calorie ring zone: green while there's room, yellow near the goal, red over it.
// Pure, so Node can test it (tests/zone.test.js).

// Upper bound of each zone as a share of the goal (inclusive); red beyond the last.
const ZONE_LIMITS = {
  default: { green: 0.85, yellow: 1.0 },  // lose / maintain: green is strictly below 85%
  gain: { green: 1.10, yellow: 1.25 },    // going a little over helps a gain goal
};

const ZONE_LABELS = {
  default: { green: "On track", yellow: "Near your goal", red: "Over your goal" },
  gain: { green: "On track", yellow: "Above your goal", red: "Well above your goal" },
};

function calorieZone(total, goal, goalType) {
  if (!(total > 0) || !(goal > 0)) return { zone: "empty", label: "" };
  const kind = goalType === "gain" ? "gain" : "default";
  const share = total / goal;
  const lim = ZONE_LIMITS[kind];
  let zone;
  if (kind === "gain") zone = share <= lim.green ? "green" : share <= lim.yellow ? "yellow" : "red";
  else zone = share < lim.green ? "green" : share <= lim.yellow ? "yellow" : "red";
  return { zone, label: ZONE_LABELS[kind][zone] };
}

if (typeof module !== "undefined") module.exports = { calorieZone };
