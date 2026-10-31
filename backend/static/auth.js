// Browser-side Supabase auth for the login, signup, welcome and main pages.
// Needs the supabase-js UMD script loaded first (it provides window.supabase).
// Tests run this file in Node with stubbed fetch, window and localStorage (see tests/auth.test.js).

const NO_RETURN_PAGES = ["/login.html", "/signup.html", "/welcome.html"];

// Where to send the user after login. Same-site paths only, so a crafted
// ?next= link can't bounce them to another site.
function safeNext(raw, origin = (typeof location !== "undefined" ? location.origin : "http://localhost")) {
  if (typeof raw !== "string" || !raw.startsWith("/")) return "/";
  // Browsers strip tab/LF/CR when parsing URLs, so "/\t/evil.example" would become "//evil.example".
  // Reject control characters and backslashes, raw or percent-encoded.
  const bad = /[\u0000-\u001f\\]/;
  try {
    if (bad.test(raw) || bad.test(decodeURIComponent(raw))) return "/";
    const u = new URL(raw, origin);
    if (u.origin !== origin) return "/";
    // These pages redirect onward themselves; landing on them after login would loop.
    if (NO_RETURN_PAGES.includes(decodeURIComponent(u.pathname))) return "/";
    return u.pathname + u.search + u.hash;
  } catch (e) {
    return "/";
  }
}

let authClient = null;

async function initAuth() {
  if (authClient) return authClient;
  const res = await fetch("/api/public-config");
  if (!res.ok) throw new Error("Couldn't load the app configuration. Try again in a moment.");
  const cfg = await res.json();
  if (!cfg.supabase_url || !cfg.supabase_publishable_key) {
    throw new Error("App not configured: the server has no Supabase URL or key.");
  }
  if (!window.supabase) throw new Error("Couldn't load the login library. Check your connection.");
  authClient = window.supabase.createClient(cfg.supabase_url, cfg.supabase_publishable_key);
  return authClient;
}

// Drop the stored session even when Supabase can't be reached: signOut keeps it on a
// network or 5xx error, and login.html would then bounce straight back to the app.
async function dropSession(client) {
  let error;
  try {
    ({ error } = await client.auth.signOut({ scope: "local" }));
  } catch (e) {
    error = e;
  }
  if (error) clearStoredSession();
}

function clearStoredSession() {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith("sb-") && key.endsWith("-auth-token")) localStorage.removeItem(key);
    }
  } catch (e) { /* storage blocked: nothing stored to remove */ }
}

async function api(path, options = {}) {
  const client = await initAuth();
  const { data } = await client.auth.getSession();
  const session = data.session;
  if (!session) {
    location = "/login.html?next=" + encodeURIComponent(location.pathname + location.search);
    return new Promise(() => {}); // page is navigating away
  }
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${session.access_token}`);
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    // The server rejected a session we still hold; drop it or login.html would bounce straight back.
    await dropSession(client);
    location = "/login.html?expired=1&next=" + encodeURIComponent(location.pathname + location.search);
    return new Promise(() => {});
  }
  if (res.status === 409) {
    const body = await res.clone().json().catch(() => null);
    if (body && body.detail === "choose_role") {
      location = "/welcome.html";
      return new Promise(() => {});
    }
  }
  return res;
}

// Never throws: logging out must work even if the config or the login library failed to load.
async function logout() {
  let client;
  try {
    client = await initAuth();
  } catch (e) {
    clearStoredSession();
    return;
  }
  await dropSession(client);
}

if (typeof module !== "undefined") {
  module.exports = { safeNext, initAuth, api, logout, dropSession };
}
