// Run from backend/: node --test "tests/*.test.js"
// checkin.js uses the browser globals from units.js and dom.js; provide them first.
const test = require("node:test");
const assert = require("node:assert/strict");
Object.assign(globalThis, require("../static/units.js"), require("../static/dom.js"));
const C = require("../static/checkin.js");

test("steps run Weight, Front, Side, Back, Done", () => {
  assert.deepEqual(C.STEPS, ["weight", "front", "side", "back", "done"]);
  assert.equal(C.stepLabel(0), "Step 1 of 5");
  assert.equal(C.stepLabel(4), "Step 5 of 5");
});

test("done summary: weight in the user's unit and the photo count", () => {
  assert.equal(C.doneSummary(72.4, "kg", 2), "Weight 72.4 kg · 2 of 3 photos");
  assert.equal(C.doneSummary(72.4, "lb", 3), "Weight 159.6 lb · 3 of 3 photos");
  assert.equal(C.doneSummary(null, "kg", 0), "0 of 3 photos");
  assert.equal(C.doneSummary(null, "kg", 1), "1 of 3 photos");
});

test("reminder offer only the first time, with push available and not yet asked", () => {
  const off = { reminders_enabled: false }, on = { reminders_enabled: true };
  assert.equal(C.offerReminders(off, "default", true), true);
  assert.equal(C.offerReminders(on, "default", true), false);
  assert.equal(C.offerReminders(off, "granted", true), false);
  assert.equal(C.offerReminders(off, "denied", true), false);
  assert.equal(C.offerReminders(off, "default", false), false);
  assert.equal(C.offerReminders(null, "default", true), false); // settings didn't load
});

test("checkinSaved: 201 (new) and 200 (today's existing check-in) both count", () => {
  assert.equal(C.checkinSaved(201), true);
  assert.equal(C.checkinSaved(200), true);
  for (const s of [400, 404, 409, 422, 500, 503]) assert.equal(C.checkinSaved(s), false, String(s));
});
