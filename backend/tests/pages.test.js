// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const STATIC = path.join(__dirname, "..", "static");

// `capture` alone makes phones open the camera only, so photos already in the gallery can't be
// picked; without it, Android's photo picker offers the gallery only. Each page keeps a gallery
// input, and the meal logger adds a separate camera input next to it.
const fileInputs = (page) =>
  fs.readFileSync(path.join(STATIC, page), "utf8").match(/<input[^>]*type="file"[^>]*>/g) || [];

test("photo inputs always offer the gallery", () => {
  for (const page of ["index.html", "checkin.html", "progress.html"]) {
    const gallery = fileInputs(page).filter((i) => !/\bcapture\b/.test(i));
    assert.ok(gallery.length > 0, `${page} has a gallery photo input`);
  }
});

test("the meal logger also offers the camera, so Android can take a photo", () => {
  const camera = fileInputs("index.html").filter((i) => /\bcapture="environment"/.test(i));
  assert.equal(camera.length, 1);
  assert.match(camera[0], /id="photo-camera"/);
  assert.match(camera[0], /accept="image\/\*"/);
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
  assert.match(html, /<label[^>]*for="photo-camera"[^>]*>[\s\S]*?Take a photo/);
});

test("check-in photos can use the camera as well as the gallery", () => {
  const checkin = fileInputs("checkin.html").filter((i) => /\bcapture="user"/.test(i));
  assert.equal(checkin.length, 1, "the photo step template has one camera input");
  assert.match(checkin[0], /class="[^"]*photo-camera-input/);
  const progress = fileInputs("progress.html").filter((i) => /\bcapture="user"/.test(i));
  assert.equal(progress.length, 1);
  assert.match(progress[0], /id="add-photo-camera"/);
});

test("the Today page has Coach Ollie's card, and loads coach.js after zone.js and before app.js", () => {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
  assert.match(html, /<section[^>]*id="coach"[^>]*hidden/);
  assert.match(html, /<button[^>]*id="coach-otter"[^>]*aria-label="Tap Ollie for another message"/);
  assert.match(html, /id="coach-text"[^>]*role="status"/);
  assert.match(html, /<button[^>]*id="coach-hide"[^>]*aria-label="Hide coach for today"/);
  const order = ["/zone.js", "/coach.js", "/app.js"].map((s) => html.indexOf(`src="${s}?v=2"`));
  assert.ok(order.every((i) => i > 0) && order[0] < order[1] && order[1] < order[2], String(order));
});

test("settings have a Show coach switch", () => {
  const nav = fs.readFileSync(path.join(STATIC, "nav.js"), "utf8");
  assert.match(nav, /id="coach-switch"/);
  assert.match(nav, /Show coach/);
});
