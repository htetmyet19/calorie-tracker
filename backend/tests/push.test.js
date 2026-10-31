// Run from backend/: node --test "tests/*.test.js"
const test = require("node:test");
const assert = require("node:assert/strict");
const { urlBase64ToUint8Array } = require("../static/push.js");
const { safeUrl, notificationFrom } = require("../static/sw.js");

test("urlBase64ToUint8Array decodes plain base64", () => {
  assert.deepEqual([...urlBase64ToUint8Array("AQID")], [1, 2, 3]);
});

test("urlBase64ToUint8Array handles - and _ (URL-safe alphabet)", () => {
  // bytes fb ff bf: standard base64 "+/+/", URL-safe "-_-_"
  assert.deepEqual([...urlBase64ToUint8Array("-_-_")], [0xfb, 0xff, 0xbf]);
});

test("urlBase64ToUint8Array handles missing padding", () => {
  assert.deepEqual([...urlBase64ToUint8Array("AQ")], [1]);      // "AQ=="
  assert.deepEqual([...urlBase64ToUint8Array("AQI")], [1, 2]);  // "AQI="
  assert.ok(urlBase64ToUint8Array("AQID") instanceof Uint8Array);
});

test("urlBase64ToUint8Array decodes a 65-byte VAPID public key", () => {
  const key = "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U";
  const bytes = urlBase64ToUint8Array(key);
  assert.equal(bytes.length, 65);
  assert.equal(bytes[0], 0x04); // uncompressed P-256 point
});

const ORIGIN = "https://tracker.example";

test("safeUrl keeps same-origin relative paths", () => {
  assert.equal(safeUrl("/progress.html", ORIGIN), "/progress.html");
  assert.equal(safeUrl("/checkin.html?x=1#a", ORIGIN), "/checkin.html?x=1#a");
});

test("safeUrl falls back to /progress.html for anything else", () => {
  for (const bad of [undefined, null, 5, "", "progress.html", "https://evil.example/",
    "//evil.example/x", "/\\evil.example", "/\t/evil.example", "javascript:alert(1)",
    `${ORIGIN}/progress.html`]) {
    assert.equal(safeUrl(bad, ORIGIN), "/progress.html", String(bad));
  }
});

test("notificationFrom reads the job's payload", () => {
  const n = notificationFrom('{"title":"Weekly check-in due","url":"/progress.html"}', ORIGIN);
  assert.deepEqual(n, {
    title: "Weekly check-in due",
    options: { body: "Tap to start your check-in", data: { url: "/progress.html" } },
  });
});

test("notificationFrom falls back on a missing or broken payload", () => {
  for (const raw of [null, "", "not json", "[]", "null", '{"title":7,"url":"https://evil.example"}']) {
    const n = notificationFrom(raw, ORIGIN);
    assert.equal(n.title, "Weekly check-in due", String(raw));
    assert.equal(n.options.data.url, "/progress.html", String(raw));
    assert.equal(n.options.body, "Tap to start your check-in");
  }
});
