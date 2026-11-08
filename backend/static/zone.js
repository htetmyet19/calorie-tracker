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

// Colour at a point on the ring, by that point's share of the goal (0.5 = half the goal).
// Same colours as the zones (styles.css --zone-*), blended between stops.
const ZONE_RGB = { green: [111, 208, 138], yellow: [232, 193, 90], red: [239, 122, 108] };
const RING_STOPS = {
  default: [[0, "green"], [0.5, "green"], [0.85, "yellow"], [1.0, "yellow"], [1.05, "red"]],
  gain: [[0, "green"], [0.8, "green"], [1.1, "yellow"], [1.2, "yellow"], [1.25, "red"]],
};

function ringColor(share, goalType) {
  const stops = RING_STOPS[goalType === "gain" ? "gain" : "default"];
  let c = ZONE_RGB[stops[stops.length - 1][1]];
  for (let i = 1; i < stops.length; i++) {
    const [s0, n0] = stops[i - 1], [s1, n1] = stops[i];
    if (share <= s1) {
      const t = s1 > s0 ? Math.max(0, (share - s0) / (s1 - s0)) : 1;
      c = ZONE_RGB[n0].map((v, k) => Math.round(v + (ZONE_RGB[n1][k] - v) * t));
      break;
    }
  }
  return `rgb(${c.join(", ")})`;
}

if (typeof module !== "undefined") module.exports = { calorieZone, ringColor, ZONE_RGB };
