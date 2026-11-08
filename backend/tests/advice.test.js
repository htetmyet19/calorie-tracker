// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const A = require("../static/advice.js");

test("request body keeps only what the server reads, and names every item", () => {
  const items = [
    { name: "Fried rice", portion: "1 plate", grams: 300, calories: 900, protein_g: 12, carbs_g: 120, fat_g: 30, confidence: "high" },
    { name: "  ", portion: "", grams: 100, calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, confidence: null },
  ];
  assert.deepEqual(A.adviceBody(items, false, "2026-11-08"), {
    items: [
      { name: "Fried rice", calories: 900, protein_g: 12, carbs_g: 120, fat_g: 30 },
      { name: "Food item", calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
    ],
    eaten: false,
    date: "2026-11-08",
  });
});

test("choosing loads, and a reset clears the advice", () => {
  let s = A.nextCardState(A.INITIAL, { type: "choose", eaten: true });
  assert.equal(s.status, "loading");
  assert.equal(s.choice, true);
  s = A.nextCardState(s, { type: "loaded", seq: s.seq, text: "About 900 kcal." });
  assert.deepEqual([s.status, s.text], ["shown", "About 900 kcal."]);
  s = A.nextCardState(s, { type: "reset" });
  assert.deepEqual([s.status, s.text, s.choice], ["idle", "", null]);
});

test("a late answer for an older choice or a reset is ignored", () => {
  const first = A.nextCardState(A.INITIAL, { type: "choose", eaten: false });
  const second = A.nextCardState(first, { type: "choose", eaten: true });
  assert.equal(A.nextCardState(second, { type: "loaded", seq: first.seq, text: "old" }), second);
  const reset = A.nextCardState(second, { type: "reset" });
  assert.equal(A.nextCardState(reset, { type: "failed", seq: second.seq }), reset);
});

test("a failure shows the error copy", () => {
  const s = A.nextCardState(A.INITIAL, { type: "choose", eaten: false });
  assert.deepEqual(A.nextCardState(s, { type: "failed", seq: s.seq }).text, A.ADVICE_ERROR);
});

test("copy fixed by the spec", () => {
  assert.equal(A.ADVICE_ERROR, "Couldn't get a suggestion. You can still save the meal.");
  assert.equal(A.ADVICE_NOTE, "Estimates are approximate. If food or eating feels stressful, talk to a doctor or someone you trust.");
});
