// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { safeNext, dropSession, logout, initAuth } = require("../static/auth.js");

test("safeNext keeps same-site paths", () => assert.equal(safeNext("/?d=1"), "/?d=1"));
test("safeNext blocks other sites", () => {
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", null, "", "/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "/%09/evil.example"])
    assert.equal(safeNext(bad), "/");
});
test("safeNext sends login and welcome pages to /", () => {
  for (const loop of ["/login.html", "/login.html?next=/", "/welcome.html", "/welcome.html#x", "/./login.html", "/%6Cogin.html"])
    assert.equal(safeNext(loop), "/");
});
test("safeNext keeps other pages with query and hash", () =>
  assert.equal(safeNext("/index.html?d=2026-10-31#meals"), "/index.html?d=2026-10-31#meals"));

// Minimal stand-in for window.localStorage: methods live on the prototype, so
// Object.keys() lists only stored keys, as with the real Storage.
class FakeStorage {
  constructor(items) { Object.assign(this, items); }
  removeItem(k) { delete this[k]; }
}
const SESSION = { "sb-127-auth-token": "{}", "sb-127-auth-token-code-verifier": "v", goal: "2000" };

test("dropSession keeps storage when signOut succeeds", async () => {
  globalThis.localStorage = new FakeStorage(SESSION);
  const client = { auth: { signOut: async (o) => { assert.deepEqual(o, { scope: "local" }); return { error: null }; } } };
  await dropSession(client);
  assert.deepEqual(Object.keys(localStorage).sort(), Object.keys(SESSION).sort());
});

for (const [name, signOut] of [
  ["returns an error", async () => ({ error: new Error("network") })],
  ["throws", async () => { throw new Error("network"); }],
]) {
  test(`dropSession removes the stored session when signOut ${name}`, async () => {
    globalThis.localStorage = new FakeStorage(SESSION);
    await dropSession({ auth: { signOut } });
    assert.deepEqual(Object.keys(localStorage).sort(), ["goal", "sb-127-auth-token-code-verifier"]);
  });
}

test("logout clears the stored session when the config can't load", async () => {
  globalThis.localStorage = new FakeStorage(SESSION);
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await logout(); // must not throw
  assert.ok(!("sb-127-auth-token" in localStorage));
});

test("initAuth explains a missing config or login library", async () => {
  const cfg = (c) => async () => ({ ok: true, json: async () => c });
  globalThis.window = {};
  globalThis.fetch = cfg({ supabase_url: "", supabase_publishable_key: "" });
  await assert.rejects(initAuth(), /App not configured/);
  globalThis.fetch = cfg({ supabase_url: "http://x", supabase_publishable_key: "k" });
  await assert.rejects(initAuth(), /Couldn't load the login library/);
});
