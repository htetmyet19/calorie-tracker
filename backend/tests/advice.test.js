// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const A = require("../static/advice.js");

test("request body keeps only what the server reads, and names every item", () => {
  const items = [
    { name: "Fried rice", portion: "1 plate", grams: 300, calories: 900, protein_g: 12, carbs_g: 120, fat_g: 30, confidence: "high" },
    { name: "  ", portion: "", grams: 100, calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, confidence: null },
  ];
  assert.deepEqual(A.adviceBody(items, "2026-11-08"), {
    items: [
      { name: "Fried rice", calories: 900, protein_g: 12, carbs_g: 120, fat_g: 30 },
      { name: "Food item", calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
    ],
    date: "2026-11-08",
  });
});

test("a request loads, and a reset clears the advice", () => {
  let s = A.nextCardState(A.INITIAL, { type: "request" });
  assert.equal(s.status, "loading");
  s = A.nextCardState(s, { type: "loaded", seq: s.seq, text: "About 900 kcal." });
  assert.deepEqual([s.status, s.text], ["shown", "About 900 kcal."]);
  s = A.nextCardState(s, { type: "reset" });
  assert.deepEqual([s.status, s.text], ["idle", ""]);
});

test("a late answer for an older request or a reset is ignored", () => {
  const first = A.nextCardState(A.INITIAL, { type: "request" });
  const second = A.nextCardState(first, { type: "request" });
  assert.equal(A.nextCardState(second, { type: "loaded", seq: first.seq, text: "old" }), second);
  const reset = A.nextCardState(second, { type: "reset" });
  assert.equal(A.nextCardState(reset, { type: "failed", seq: second.seq }), reset);
});

test("a failure shows the error copy", () => {
  const s = A.nextCardState(A.INITIAL, { type: "request" });
  assert.deepEqual(A.nextCardState(s, { type: "failed", seq: s.seq }).text, A.ADVICE_ERROR);
});

test("copy fixed by the spec", () => {
  assert.equal(A.ADVICE_ERROR, "Couldn't get a suggestion. You can still save the meal.");
  assert.equal(A.ADVICE_NOTE, "Estimates are approximate. If food or eating feels stressful, talk to a doctor or someone you trust.");
});

test("editing the meal marks shown advice as out of date, and drops a pending answer", () => {
  let s = A.nextCardState(A.INITIAL, { type: "request" });
  s = A.nextCardState(s, { type: "loaded", seq: s.seq, text: "About 900 kcal." });
  s = A.nextCardState(s, { type: "changed" });
  assert.deepEqual([s.status, s.text], ["stale", A.ADVICE_STALE]);

  const pending = A.nextCardState(A.INITIAL, { type: "request" });
  const changed = A.nextCardState(pending, { type: "changed" });
  assert.equal(A.nextCardState(changed, { type: "loaded", seq: pending.seq, text: "old" }), changed);
});

test("editing before any advice was asked for changes nothing", () => {
  assert.equal(A.nextCardState(A.INITIAL, { type: "changed" }), A.INITIAL);
});

test("the update button shows only when the advice is out of date or failed", () => {
  assert.equal(A.refreshLabel({ status: "stale" }), "Update suggestion");
  assert.equal(A.refreshLabel({ status: "error" }), "Try again");
  for (const status of ["idle", "loading", "shown"]) assert.equal(A.refreshLabel({ status }), null);
});
