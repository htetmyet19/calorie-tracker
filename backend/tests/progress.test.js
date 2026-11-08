// Run from backend/: node --test "tests/*.test.js"
// progress.js uses the browser globals from units.js and dom.js; provide them first.
const test = require("node:test");
const assert = require("node:assert/strict");
Object.assign(globalThis, require("../static/units.js"), require("../static/dom.js"));
const P = require("../static/progress.js");
const { isoDate, addDays } = require("../static/dom.js");

test("isoDate is the local calendar date, not UTC", () => {
  // 00:30 local on 1 Nov: toISOString would give 31 Oct in any zone east of UTC.
  assert.equal(isoDate(new Date(2026, 10, 1, 0, 30)), "2026-11-01");
  assert.equal(addDays("2026-11-01", -1), "2026-10-31");
  assert.equal(addDays("2026-10-31", -83), "2026-08-09");
});

test("check-in card text", () => {
  assert.equal(P.checkinText({ due: true, next_due_on: "2026-10-31" }, "2026-10-31"), "Weekly check-in due");
  assert.equal(P.checkinText({ due: false, next_due_on: "2026-11-04" }, "2026-10-31"), "Next check-in in 4 days");
  assert.equal(P.checkinText({ due: false, next_due_on: "2026-11-01" }, "2026-10-31"), "Next check-in in 1 day");
});

const W = [
  { logged_on: "2026-08-10", weight_kg: 72.4 },
  { logged_on: "2026-09-01", weight_kg: 71.0 },
  { logged_on: "2026-10-31", weight_kg: 70.1 },
];

test("weight summary: latest value and change since the first entry, in the unit", () => {
  assert.deepEqual(P.weightSummary(W, "kg"), { latest: "70.1 kg", change: "−2.3 kg since 10 Aug" });
  const lb = P.weightSummary(W, "lb");
  assert.equal(lb.latest, "154.5 lb");
  assert.equal(lb.change, "−5.1 lb since 10 Aug"); // 159.6 - 154.5, from the shown values
  assert.equal(P.weightSummary([{ logged_on: "2026-10-01", weight_kg: 70 }, { logged_on: "2026-10-02", weight_kg: 70.5 }], "kg").change,
    "+0.5 kg since 1 Oct");
  assert.equal(P.weightSummary([{ logged_on: "2026-10-01", weight_kg: 70 }, { logged_on: "2026-10-02", weight_kg: 70 }], "kg").change,
    "No change since 1 Oct");
  assert.equal(P.weightSummary([W[0]], "kg").change, "First entry");
  assert.equal(P.weightSummary([], "kg"), null);
});

test("chart labels summarise the data for screen readers", () => {
  assert.equal(P.weightLabel(W, "kg"), "Weight over 12 weeks: from 72.4 kg to 70.1 kg");
  assert.equal(P.weightLabel([W[2]], "lb"), "Weight over 12 weeks: one entry, 154.5 lb");
  const days = [
    { date: "2026-10-30", total_calories: 1800.4 },
    { date: "2026-10-31", total_calories: 2300 },
  ];
  assert.equal(P.caloriesLabel(days, 2000),
    "Calories over the last 2 days against a goal of 2,000 kcal: 30 Oct 1,800, 31 Oct 2,300 (over)");
});

test("weight input validation uses the unit's range", () => {
  assert.equal(P.weightError("", "kg"), "Enter your weight.");
  assert.equal(P.weightError("29.9", "kg"), "Enter a weight between 30 and 300 kg.");
  assert.equal(P.weightError("300", "kg"), "");
  assert.equal(P.weightError("66.1", "lb"), "Enter a weight between 66.2 and 661.3 lb.");
  assert.equal(P.weightError("661.3", "lb"), "");
  assert.equal(P.weightError("abc", "kg"), "Enter your weight.");
});

test("date validation: required, not in the future", () => {
  assert.equal(P.dateError("", "2026-10-31"), "Choose a date.");
  assert.equal(P.dateError("2026-11-01", "2026-10-31"), "The date can't be in the future.");
  assert.equal(P.dateError("2026-10-31", "2026-10-31"), "");
});

test("compare picks a pose per check-in or says it is missing", () => {
  const c = { checked_on: "2026-10-24", photos: [{ id: 1, pose: "front", url: "https://x/f" }] };
  assert.equal(P.photoFor(c, "front").url, "https://x/f");
  assert.equal(P.photoFor(c, "side"), null);
  assert.equal(P.missingPhotoText("side", "2026-10-24"), "No side photo on 24 Oct");
});

test("photo viewer title names the pose and date", () => {
  assert.equal(P.photoViewTitle("side", "2026-10-31"), "Side photo, 31 Oct");
});

test("deleting a photo asks the agreed question", () => {
  assert.equal(P.DELETE_PHOTO_CONFIRM, "Delete this photo? This can't be undone.");
});

test("photoDeleteError: 204 and 404 (already gone) succeed, anything else explains", () => {
  assert.equal(P.photoDeleteError(204), "");
  assert.equal(P.photoDeleteError(404), "");
  for (const s of [null, 500, 503, 409]) {
    assert.equal(P.photoDeleteError(s), "Couldn't delete the photo. Check your connection and try again.", String(s));
  }
});

test("a skipped photo can be added later: button label and error text", () => {
  assert.equal(P.addPhotoLabel("front", "2026-11-01"), "Add front photo for 1 Nov");
  assert.equal(P.addPhotoError("unreadable", "side", "2026-11-01"),
    "Couldn't read that side photo for 1 Nov. Choose another one.");
  assert.equal(P.addPhotoError("failed", "back", "2026-11-01"),
    "Couldn't add the back photo for 1 Nov. Check your connection and try again.");
});
