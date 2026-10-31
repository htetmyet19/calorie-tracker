// Service worker for weekly check-in reminders. Push only: no caching, no fetch
// handler, no offline mode. safeUrl and notificationFrom are pure so Node can
// test them (tests/push.test.js).

const FALLBACK_TITLE = "Weekly check-in due";
const FALLBACK_URL = "/progress.html";
const BODY = "Tap to start your check-in";

// Only same-origin relative paths are followed; anything else opens Progress.
function safeUrl(raw, origin) {
  if (typeof raw !== "string" || !raw.startsWith("/") || raw.startsWith("//")) return FALLBACK_URL;
  if (/[\u0000-\u001f\\]/.test(raw)) return FALLBACK_URL;
  try {
    const u = new URL(raw, origin);
    if (u.origin !== origin) return FALLBACK_URL;
    const path = u.pathname + u.search + u.hash;
    // Dot segments can collapse "/..//x" to "//x", which a browser reads as another host.
    if (path.startsWith("//")) return FALLBACK_URL;
    return path;
  } catch (e) {
    return FALLBACK_URL;
  }
}

// rawText: the push message as text (null when the push had no data).
function notificationFrom(rawText, origin) {
  let data = null;
  try { data = rawText ? JSON.parse(rawText) : null; } catch (e) { /* not JSON: use the fallback */ }
  if (!data || typeof data !== "object" || Array.isArray(data)) data = {};
  const title = typeof data.title === "string" && data.title ? data.title : FALLBACK_TITLE;
  return { title, options: { body: BODY, data: { url: safeUrl(data.url, origin) } } };
}

if (typeof module !== "undefined") {
  module.exports = { safeUrl, notificationFrom };
} else {
  self.addEventListener("install", () => self.skipWaiting());
  self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

  self.addEventListener("push", (event) => {
    let text = null;
    try { text = event.data ? event.data.text() : null; } catch (e) { /* unreadable: fallback */ }
    const { title, options } = notificationFrom(text, self.location.origin);
    event.waitUntil(self.registration.showNotification(title, options));
  });

  self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const data = event.notification.data || {};
    const url = safeUrl(data.url, self.location.origin);
    event.waitUntil((async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows.find((c) => new URL(c.url).origin === self.location.origin);
      if (open) {
        try {
          await open.focus();
          // navigate() only works on pages this worker controls; otherwise open a new tab.
          if ("navigate" in open) { await open.navigate(url); return; }
        } catch (e) { /* fall through to a new tab */ }
      }
      await self.clients.openWindow(url);
    })());
  });
}
