// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.join(__dirname, "..", "static");

// `capture` makes phones open the camera only, so photos already in the gallery can't be picked.
test("photo inputs offer the gallery as well as the camera", () => {
  for (const page of ["index.html", "checkin.html", "progress.html"]) {
    const html = fs.readFileSync(path.join(STATIC, page), "utf8");
    const inputs = html.match(/<input[^>]*type="file"[^>]*>/g) || [];
    assert.ok(inputs.length > 0, `${page} has a photo input`);
    for (const input of inputs) assert.doesNotMatch(input, /\bcapture\b/, `${page}: ${input}`);
  }
});
