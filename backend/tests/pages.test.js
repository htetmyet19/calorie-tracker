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
  assert.match(html, /<button[^>]*id="coach-otter"[^>]*aria-label="Coach Ollie: tap for another message"/);
  assert.match(html, /id="coach-text"[^>]*role="status"/);
  assert.match(html, /<button[^>]*id="coach-fold"[^>]*aria-label="Fold the message away"/);
  const order = ["/zone.js", "/coach.js", "/app.js"].map((s) => html.indexOf(`src="${s}?v=2"`));
  assert.ok(order.every((i) => i > 0) && order[0] < order[1] && order[1] < order[2], String(order));
});

test("settings have a Show coach switch", () => {
  const nav = fs.readFileSync(path.join(STATIC, "nav.js"), "utf8");
  assert.match(nav, /id="coach-switch"/);
  assert.match(nav, /Show coach/);
});

test("on phones the Today page fits the screen: only the meals list scrolls, and Ollie floats in the corner", () => {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
  assert.match(html, /<body[^>]*class="[^"]*\bapp-today\b/);
  const css = fs.readFileSync(path.join(STATIC, "styles.css"), "utf8");
  const phone = css.slice(css.indexOf("@media (max-width: 899px)"));
  assert.ok(css.includes("@media (max-width: 899px)"), "a phone layout block");
  assert.match(phone, /body\.app-today\s*\{[^}]*height:\s*100dvh[^}]*overflow:\s*hidden/);
  assert.match(phone, /\.app-today \.meals-section\s*\{[^}]*overflow-y:\s*auto/);
  assert.match(css, /\.coach\s*\{[^}]*position:\s*fixed/);
});

test("full-body Ollie: every move in coach.js has a pose in the page and a rule in the styles", () => {
  const { ACTIONS } = require("../static/coach.js");
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
  assert.match(html, /<svg class="ollie" id="coach-ollie" data-action="[a-z]+"/);
  for (const pose of ["pose-stand", "pose-pushup", "pose-sleep", "pose-eat"]) assert.ok(html.includes(`class="pose ${pose}"`), pose);
  const css = fs.readFileSync(path.join(STATIC, "styles.css"), "utf8");
  for (const a of ACTIONS) assert.match(css, new RegExp(`\\.ollie\\[data-action="${a}"\\] \\.pose-`), a);
  assert.match(css, /prefers-reduced-motion: reduce\) \{ \.ollie, \.ollie \* \{ animation: none !important; \} \}/);
  for (const joint of ["s-fore-l", "s-shin-r", "p-fore-n", "e-fore-r"]) assert.ok(html.includes(`class="${joint}"`), joint);
});

test("no pulsing ring around Ollie when his message is folded away", () => {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
  const css = fs.readFileSync(path.join(STATIC, "styles.css"), "utf8");
  assert.doesNotMatch(html, /coach-pulse/);
  assert.doesNotMatch(css, /coach-pulse/);
});

test("Ollie's message is a frosted-glass bubble with a name tag and a tail; tapping it folds it", () => {
  const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
  const bubble = html.slice(html.indexOf('id="coach-bubble"'), html.indexOf('id="coach-otter"'));
  assert.match(bubble, /<span class="coach-name" aria-hidden="true">Coach Ollie<\/span>/, "a small name tag, hidden from screen readers");
  assert.match(bubble, /<button[^>]*class="coach-fold"[^>]*aria-label="Fold the message away"/);
  const css = fs.readFileSync(path.join(STATIC, "styles.css"), "utf8");
  const rule = css.match(/\.coach-bubble\s*\{[^}]*\}/)[0];
  assert.match(rule, /backdrop-filter:\s*blur/, "frosted glass");
  assert.match(rule, /-webkit-backdrop-filter:\s*blur/, "frosted glass on iPhone Safari");
  assert.doesNotMatch(css, /#fff6e6/, "the cream bubble is gone");
  assert.match(css, /\.coach-bubble::after\s*\{/, "a tail pointing at Ollie");
  assert.match(css, /\.coach-fold\s*\{[^}]*inset:\s*0/, "the fold button covers the whole bubble");
});

test("the message box floats, glows, shimmers and brings words in one by one; reduced motion stops it", () => {
  const css = fs.readFileSync(path.join(STATIC, "styles.css"), "utf8");
  for (const name of ["bubble-float", "bubble-glow", "bubble-shimmer", "word-in"]) {
    assert.match(css, new RegExp(`@keyframes ${name}\\b`), `${name} keyframes`);
  }
  assert.match(css, /\.coach-word\s*\{[^}]*animation:[^}]*word-in/, "each word animates in");
  assert.match(css, /\.coach-word\s*\{[^}]*animation-delay:\s*var\(--d/, "words use their own delay");
  const bubbleReduced = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{[^@]*\.coach-bubble[^@]*\}/);
  assert.ok(bubbleReduced && /\.coach-word/.test(bubbleReduced[0]), "reduced motion stills the bubble and the words");
  const js = fs.readFileSync(path.join(STATIC, "app.js"), "utf8");
  assert.match(js, /wordDelays\(/, "app.js uses wordDelays");
  assert.doesNotMatch(js, /coach-text[^\n]*innerHTML/, "words are built as elements, not HTML strings");
});
