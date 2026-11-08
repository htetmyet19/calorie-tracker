// Coach Ollie: one short line about today, chosen by fixed rules (no AI).
// Pure, so Node can test it (tests/coach.test.js). Spec: docs/superpowers/specs/2026-11-08-otter-coach-design.md

// Two lines per situation; {left} is the kcal left to the goal.
const COACH_LINES = {
  checkin: ["It's check-in day! Let's see how your week went.", "Weekly check-in time: a quick weigh-in and a few photos."],
  morning: ["Morning! Snap your breakfast when you're ready.", "New day, fresh start. Log your first meal when you eat."],
  noMeals: ["Nothing logged yet today. Snap your next meal and I'll keep count.", "Your next meal is a good place to start logging today."],
  over: ["A bit over today, and that's fine. One day doesn't change the trend.", "Over your goal today. No stress: tomorrow's a fresh start."],
  near: ["Close to your goal. Something light if you're still hungry.", "{left} kcal left. Fruit or yogurt fits nicely."],
  nearGain: ["Above your goal today. That's fine while you're gaining.", "A little over your goal. Nice work fuelling today."],
  reachedGain: ["Goal reached. Nice work fuelling today.", "You hit your goal today. Keep it up."],
  trackGain: ["{left} kcal to go. Keep fuelling!", "{left} kcal left to reach your goal. You've got this."],
  track: ["{left} kcal left. Nice pace!", "On track, with {left} kcal to go."],
};
const CHECKIN_ACTION = { label: "Start check-in", href: "/checkin.html" };
const MORNING_ENDS = 11; // before 11:00 an empty day is "morning"

const zoneOf = typeof calorieZone === "function" ? calorieZone : require("./zone.js").calorieZone;

// facts: { total, goal, goalType, mealCount, hour, checkinDue, dayOfMonth, flip }
// → { mood: "wave"|"sleepy"|"open"|"calm"|"happy", text, action: null | { label, href } }
function coachMessage(f) {
  const gain = f.goalType === "gain";
  let key, mood, action = null;
  if (f.checkinDue) { key = "checkin"; mood = "wave"; action = CHECKIN_ACTION; }
  else if (!(f.mealCount > 0)) {
    if (f.hour < MORNING_ENDS) { key = "morning"; mood = "sleepy"; } else { key = "noMeals"; mood = "open"; }
  } else {
    const zone = zoneOf(f.total, f.goal, f.goalType).zone;
    if (zone === "red") { key = "over"; mood = "calm"; }
    else if (zone === "yellow") { key = gain ? "nearGain" : "near"; mood = "open"; }
    else { key = gain ? (f.total >= f.goal ? "reachedGain" : "trackGain") : "track"; mood = "happy"; }
  }
  const variant = ((f.dayOfMonth || 0) + (f.flip ? 1 : 0)) % 2;
  const left = Math.max(0, Math.round(f.goal - f.total)).toLocaleString("en-IN");
  return { mood, text: COACH_LINES[key][variant].replace("{left}", left), action };
}

if (typeof module !== "undefined") module.exports = { coachMessage, COACH_LINES };
