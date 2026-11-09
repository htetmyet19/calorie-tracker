// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { settingsBody, accountSummary } = require("../static/nav.js");

const LOADED = {
  height_cm: 170, weight_kg: 70.5, age: 30, sex: "female", activity: 1.375,
  weight_goal: "lose", goal_kcal: 1800, weight_unit: "lb", reminders_enabled: true,
  goal_set_by: "trainer-1",
};

test("a partial save sends every field, so PUT never resets the others", () => {
  assert.deepEqual(settingsBody(LOADED, { weight_unit: "kg" }), {
    height_cm: 170, weight_kg: 70.5, age: 30, sex: "female", activity: 1.375,
    weight_goal: "lose", goal_kcal: 1800, goal_weight_kg: null, weight_unit: "kg",
    reminders_enabled: true,
  });
});

test("goal_set_by is server-owned and never sent", () => {
  assert.equal("goal_set_by" in settingsBody(LOADED, { goal_kcal: 2000 }), false);
});

test("missing loaded settings fall back to the server defaults", () => {
  assert.deepEqual(settingsBody(null, { goal_kcal: 2000 }), {
    height_cm: null, weight_kg: null, age: null, sex: null, activity: null,
    weight_goal: null, goal_kcal: 2000, goal_weight_kg: null, weight_unit: "kg",
    reminders_enabled: false,
  });
});

const { legacySettings } = require("../static/nav.js");

const PROFILE = JSON.stringify({ heightCm: 170, weightKg: 70.5, age: 30, sex: "female",
  activity: 1.375, goal: "lose" });

test("old browser settings map onto the settings fields", () => {
  assert.deepEqual(legacySettings(PROFILE, "1800", {}), {
    height_cm: 170, weight_kg: 70.5, age: 30, sex: "female", activity: 1.375,
    weight_goal: "lose", goal_kcal: 1800,
  });
});

test("nothing stored means nothing to move", () => {
  assert.equal(legacySettings(null, null, {}), null);
});

test("goal alone moves alone", () => {
  assert.deepEqual(legacySettings(null, "2150", {}), { goal_kcal: 2150 });
});

test("a weight already on the server is newer than the browser's copy", () => {
  assert.equal("weight_kg" in legacySettings(PROFILE, null, { weight_kg: 72 }), false);
});

test("values the server would reject are dropped, not sent", () => {
  const junk = JSON.stringify({ heightCm: 500, weightKg: "x", age: 12, sex: "other",
    activity: 1.3, goal: "lose" });
  assert.deepEqual(legacySettings(junk, "99999", {}), { weight_goal: "lose" });
  assert.deepEqual(legacySettings("{not json", "abc", {}), {});
});

test("a save merges into the fresh server copy, keeping another device's changes", () => {
  // Page loaded hours ago; since then another device logged a weight and turned reminders on.
  const fresh = { ...LOADED, weight_kg: 68.04, reminders_enabled: true };
  const body = settingsBody(fresh, { goal_kcal: 2000 });
  assert.equal(body.weight_kg, 68.04);
  assert.equal(body.reminders_enabled, true);
  assert.equal(body.goal_kcal, 2000);
});

test("saveSettings re-reads the server before every PUT", async () => {
  const calls = [];
  const server = { ...LOADED, goal_set_by: undefined };
  global.document = { dispatchEvent() {} };
  global.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
  global.localStorage = { getItem: () => null, removeItem() {} };
  global.api = async (path, opts = {}) => {
    calls.push([opts.method || "GET", path]);
    if ((opts.method || "GET") === "GET") {
      return { ok: true, json: async () => ({ ...server }) };
    }
    const body = JSON.parse(opts.body);
    Object.assign(server, body);
    return { ok: true, json: async () => ({ ...server }) };
  };
  const nav = require("../static/nav.js");
  await nav.loadSettings();                       // page load
  server.weight_kg = 68.04;                       // another device, later
  server.reminders_enabled = false;
  const out = await nav.saveSettings({ weight_unit: "kg" });
  assert.equal(out.weight_kg, 68.04);
  assert.equal(out.reminders_enabled, false);
  assert.deepEqual(calls, [["GET", "/api/settings"], ["GET", "/api/settings"], ["PUT", "/api/settings"]]);
  delete global.api; delete global.document; delete global.CustomEvent; delete global.localStorage;
});

for (const [outcome, dropped] of [[200, true], [409, true], [422, false], [500, false], ["offline", false]]) {
  test(`old browser settings are ${dropped ? "removed" : "kept"} after a ${outcome} move`, async () => {
    const store = { profile: PROFILE, goal: "1800" };
    global.localStorage = {
      getItem: (k) => (k in store ? store[k] : null),
      removeItem: (k) => { delete store[k]; },
    };
    global.api = async (path, opts) => {
      assert.equal(path, "/api/settings?only_if_empty=1");
      assert.equal(opts.method, "PUT");
      if (outcome === "offline") throw new TypeError("Failed to fetch");
      return { ok: outcome === 200, status: outcome, json: async () => ({ goal_kcal: 1800 }) };
    };
    const { moveLegacySettings } = require("../static/nav.js");
    await moveLegacySettings({});
    assert.deepEqual(Object.keys(store).length === 0, dropped);
    delete global.api; delete global.localStorage;
  });
}

test("old browser settings with nothing valid left are removed without a request", async () => {
  const store = { profile: "{not json", goal: "abc" };
  global.localStorage = { getItem: (k) => store[k] ?? null, removeItem: (k) => { delete store[k]; } };
  global.api = async () => { throw new Error("no request expected"); };
  const { moveLegacySettings } = require("../static/nav.js");
  await moveLegacySettings({});
  assert.deepEqual(store, {});
  delete global.api; delete global.localStorage;
});

test("Settings, Close and Log out are modern icon buttons with spoken names", () => {
  const fs = require("node:fs"), path = require("node:path");
  const src = fs.readFileSync(path.join(__dirname, "../static/nav.js"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../static/styles.css"), "utf8");
  // Settings: a round glass gear button, named for screen readers
  assert.match(src, /open\.className = "icon-round settings-open"/);
  assert.match(src, /open\.setAttribute\("aria-label", "Settings"\)/);
  assert.match(src, /open\.innerHTML = `<svg class="gear"/);
  assert.doesNotMatch(src, /open\.textContent = "Settings"/, "no plain text link any more");
  // Close: a round ×
  assert.match(src, /<button class="icon-round icon-close" type="button" id="settings-close" aria-label="Close settings">/);
  // Log out: soft red, exit icon, second tap confirms
  assert.match(src, /<button class="btn settings-logout" type="button" id="logout">\s*<svg/);
  assert.match(src, /Tap again to log out/);
  assert.match(css, /\.icon-round\s*\{[^}]*border-radius:\s*50%/);
  assert.match(css, /\.icon-round\s*\{[^}]*width:\s*4[0-4]px/, "a finger-sized target");
  assert.match(css, /\.settings-logout\s*\{[^}]*color:\s*var\(--chili\)/);
  assert.match(css, /\.settings-logout\.is-confirming\s*\{/);
  assert.match(css, /prefers-reduced-motion: reduce\)\s*\{[^}]*\.gear/, "the gear doesn't spin under reduced motion");
});

// ---------- Account card ----------

test("a Google user shows name, email, photo and the sign-in method", () => {
  const user = {
    email: "ana@gmail.com",
    app_metadata: { provider: "google", providers: ["google"] },
    user_metadata: { full_name: "Ana Lim", avatar_url: "https://lh3.googleusercontent.com/a/x=s96-c" },
  };
  assert.deepEqual(accountSummary(user), {
    name: "Ana Lim", email: "ana@gmail.com", initial: "A",
    photo: "https://lh3.googleusercontent.com/a/x=s96-c", method: "Signed in with Google",
  });
});

test("an email-and-password user has no name or photo and an initial from the email", () => {
  const user = { email: "bo@example.com", app_metadata: { provider: "email" }, user_metadata: {} };
  assert.deepEqual(accountSummary(user), {
    name: "", email: "bo@example.com", initial: "B", photo: "", method: "Signed in with email",
  });
});

test("Google's `name` and `picture` fields are used when full_name/avatar_url are missing", () => {
  const s = accountSummary({ email: "c@gmail.com", app_metadata: { provider: "google" },
    user_metadata: { name: "  Chan  ", picture: "https://lh3.googleusercontent.com/p" } });
  assert.equal(s.name, "Chan");
  assert.equal(s.photo, "https://lh3.googleusercontent.com/p");
});

test("only https photos are used", () => {
  const s = accountSummary({ email: "d@gmail.com", app_metadata: { provider: "google" },
    user_metadata: { avatar_url: "javascript:alert(1)" } });
  assert.equal(s.photo, "");
});

test("missing user, provider or email still gives a safe summary", () => {
  assert.deepEqual(accountSummary(null), { name: "", email: "", initial: "?", photo: "", method: "" });
  const s = accountSummary({ email: "e@x.io", app_metadata: {} });
  assert.equal(s.method, "");
  assert.equal(s.initial, "E");
  assert.equal(accountSummary({ email: "", user_metadata: { full_name: "zoe" } }).initial, "Z");
});

test("the Settings panel has an account card above the settings", () => {
  const fs = require("node:fs"), path = require("node:path");
  const src = fs.readFileSync(path.join(__dirname, "../static/nav.js"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../static/styles.css"), "utf8");
  const html = src.slice(src.indexOf("const SETTINGS_HTML"), src.indexOf("</button>`;"));
  assert.ok(html.indexOf('id="settings-account"') > html.indexOf('id="settings-title"'));
  assert.ok(html.indexOf('id="settings-account"') < html.indexOf("settings-unit"));
  for (const id of ["account-photo", "account-initial", "account-name", "account-email", "account-method"]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(src, /accountSummary\(/);
  assert.match(src, /addEventListener\("error"/, "a photo that fails to load falls back to the initial");
  assert.match(css, /\.account-email\s*\{[^}]*text-overflow:\s*ellipsis/);
});
