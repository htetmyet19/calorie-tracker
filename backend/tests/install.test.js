// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { installMode, isIos } = require("../static/install.js");

const STATIC = path.join(__dirname, "..", "static");
const PAGES = ["index.html", "progress.html", "checkin.html", "login.html", "signup.html", "welcome.html"];

const IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";
const ANDROID_UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";
const MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15";

test("isIos: iPhone yes, Android no", () => {
  assert.equal(isIos(IPHONE_UA, 5), true);
  assert.equal(isIos(ANDROID_UA, 5), false);
});

test("isIos: iPadOS reports a Mac but has touch", () => {
  assert.equal(isIos(MAC_UA, 5), true);
  assert.equal(isIos(MAC_UA, 0), false); // a real Mac
});

test("installMode: already installed wins", () => {
  assert.equal(installMode({ standalone: true, ios: true, canPrompt: false }), "installed");
  assert.equal(installMode({ standalone: true, ios: false, canPrompt: true }), "installed");
});

test("installMode: Chrome's install prompt is available", () => {
  assert.equal(installMode({ standalone: false, ios: false, canPrompt: true }), "prompt");
});

test("installMode: iPhone needs Share -> Add to Home Screen", () => {
  assert.equal(installMode({ standalone: false, ios: true, canPrompt: false }), "ios");
});

test("installMode: other browsers get the menu hint", () => {
  assert.equal(installMode({ standalone: false, ios: false, canPrompt: false }), "manual");
});

function pngSize(file) {
  const buf = fs.readFileSync(file);
  assert.equal(buf.toString("ascii", 1, 4), "PNG", `${file} is a PNG`);
  return [buf.readUInt32BE(16), buf.readUInt32BE(20)];
}

test("manifest describes an installable app with real icons", () => {
  const m = JSON.parse(fs.readFileSync(path.join(STATIC, "manifest.webmanifest"), "utf8"));
  assert.equal(m.start_url, "/");
  assert.equal(m.scope, "/");
  assert.equal(m.display, "standalone");
  assert.ok(m.name && m.short_name && m.short_name.length <= 12);
  assert.match(m.background_color, /^#[0-9a-f]{6}$/i);
  assert.match(m.theme_color, /^#[0-9a-f]{6}$/i);

  const sizes = new Set();
  for (const icon of m.icons) {
    const [w, h] = pngSize(path.join(STATIC, icon.src));
    assert.equal(`${w}x${h}`, icon.sizes, icon.src);
    assert.equal(icon.type, "image/png");
    sizes.add(`${icon.sizes} ${icon.purpose || "any"}`);
  }
  for (const need of ["192x192 any", "512x512 any", "512x512 maskable"]) assert.ok(sizes.has(need), need);
});

test("every page links the manifest, the touch icon and covers the notch", () => {
  const touch = /<link rel="apple-touch-icon" href="([^"]+)">/;
  for (const page of PAGES) {
    const html = fs.readFileSync(path.join(STATIC, page), "utf8");
    assert.match(html, /<link rel="manifest" href="\/manifest\.webmanifest">/, page);
    assert.match(html, /<meta name="viewport" content="[^"]*viewport-fit=cover[^"]*">/, page);
    assert.match(html, /<meta name="apple-mobile-web-app-capable" content="yes">/, page);
    const icon = html.match(touch);
    assert.ok(icon, `${page} has an apple-touch-icon`);
    assert.deepEqual(pngSize(path.join(STATIC, icon[1])), [180, 180], page);
  }
});
