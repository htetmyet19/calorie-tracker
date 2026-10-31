// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { safeNext } = require("../static/auth.js");

test("safeNext keeps same-site paths", () => assert.equal(safeNext("/?d=1"), "/?d=1"));
test("safeNext blocks other sites", () => {
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", null, ""])
    assert.equal(safeNext(bad), "/");
});
