// Weekly check-in reminders by web push (Chrome on Android). Needs auth.js (api)
// and nav.js (refreshSettings, saveSettings) loaded on the page. Never asks for
// permission on its own: only from a button the user pressed.
// urlBase64ToUint8Array is pure so Node can test it (tests/push.test.js).

// VAPID keys are URL-safe base64 without padding; PushManager wants the raw bytes.
function urlBase64ToUint8Array(s) {
  const padded = s + "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// ---------- Browser only below ----------

const PUSH_ERROR = "Couldn't change reminders. Check your connection and try again.";

function pushSupported() {
  return typeof navigator !== "undefined" && "serviceWorker" in navigator
    && typeof window !== "undefined" && "PushManager" in window && "Notification" in window;
}

// The key is fetched ahead (preloadPushKey) when a reminder button appears, so the
// permission prompt still runs inside the tap's user activation on slow data.
let keyPromise = null;

async function fetchPushKey() {
  const res = await fetch("/api/push/public-key");
  if (res.status === 503) return null; // VAPID not configured on this server
  if (!res.ok) throw new Error(PUSH_ERROR);
  const { key } = await res.json();
  return key;
}

function preloadPushKey() {
  if (!keyPromise) {
    keyPromise = fetchPushKey();
    keyPromise.catch(() => { keyPromise = null; }); // let the next try fetch again
  }
  return keyPromise;
}

async function subscribeBrowser(reg, key) {
  const options = { userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) };
  try {
    return await reg.pushManager.subscribe(options);
  } catch (e) {
    // An old subscription made with another server key blocks a new one: drop it and retry.
    const old = await reg.pushManager.getSubscription();
    if (!old) throw e;
    await old.unsubscribe();
    return reg.pushManager.subscribe(options);
  }
}

async function sendSubscription(sub) {
  const { endpoint, keys } = sub.toJSON();
  let res;
  try {
    res = await api("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint, keys: { p256dh: keys.p256dh, auth: keys.auth } }),
    });
  } catch (e) {
    throw new Error(PUSH_ERROR);
  }
  return res.status;
}

// Returns 'enabled', 'blocked' (permission denied), 'dismissed' (prompt closed
// without a choice), 'unsupported' (no push in this browser) or 'unavailable'
// (the server has no VAPID key). Throws an Error with a message on other failures.
async function enableReminders() {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "blocked";
  let key;
  try {
    key = await preloadPushKey();
  } catch (e) {
    throw new Error(PUSH_ERROR);
  }
  if (!key) return "unavailable";

  const permission = await Notification.requestPermission();
  if (permission === "denied") return "blocked";
  if (permission !== "granted") return "dismissed";

  let sub;
  try {
    await navigator.serviceWorker.register("/sw.js");
    const reg = await navigator.serviceWorker.ready;
    sub = (await reg.pushManager.getSubscription()) || (await subscribeBrowser(reg, key));
    let status = await sendSubscription(sub);
    if (status === 409) {
      // This browser's endpoint is registered to another account (shared phone):
      // make a fresh endpoint for this one.
      await sub.unsubscribe();
      sub = await subscribeBrowser(reg, key);
      status = await sendSubscription(sub);
    }
    if (status !== 201) throw new Error(PUSH_ERROR);
  } catch (e) {
    throw new Error(PUSH_ERROR);
  }
  await refreshSettings().catch(() => {}); // the server set reminders_enabled
  return "enabled";
}

async function currentSubscription() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

// Removes this browser's subscription, then makes sure reminders are off for the
// account (the server only turns them off by itself when no device is left).
async function disableReminders() {
  try {
    const sub = await currentSubscription();
    if (sub) {
      const res = await api("/api/push/subscribe", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: sub.endpoint }),
      });
      if (!res.ok) throw new Error(PUSH_ERROR);
      await sub.unsubscribe().catch(() => {}); // the server no longer sends to it either way
    }
  } catch (e) {
    throw new Error(PUSH_ERROR);
  }
  const settings = await refreshSettings();
  if (settings.reminders_enabled) await saveSettings({ reminders_enabled: false });
}

// On logout: this browser stops getting the account's reminders. Unlike
// disableReminders it never saves reminders_enabled, so the account's other
// devices keep theirs. Never throws, and gives up on the server after timeoutMs
// so a slow or stuck request cannot hold up the logout.
async function forgetThisDevice(timeoutMs = 3000) {
  try {
    const sub = await currentSubscription();
    if (!sub) return;
    const removed = api("/api/push/subscribe", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    }).catch(() => {});
    let timer;
    await Promise.race([removed, new Promise((r) => { timer = setTimeout(r, timeoutMs); })]);
    clearTimeout(timer);
    // Unsubscribe even if the server call failed: the push service then answers 410
    // and the daily job deletes the row.
    await sub.unsubscribe().catch(() => {});
  } catch (e) { /* logout goes ahead regardless */ }
}

if (typeof module !== "undefined") {
  module.exports = { urlBase64ToUint8Array, forgetThisDevice };
}
