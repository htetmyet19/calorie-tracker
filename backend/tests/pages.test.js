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
