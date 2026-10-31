// Browser-side Supabase auth for the login, welcome and main pages.
// Needs the supabase-js UMD script loaded first (it provides window.supabase).
// Only safeNext is meant to run outside a browser (see tests/auth.test.js).

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
  authClient = window.supabase.createClient(cfg.supabase_url, cfg.supabase_publishable_key);
  return authClient;
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
    try { await client.auth.signOut({ scope: "local" }); } catch (e) { /* ignore */ }
    location = "/login.html?next=" + encodeURIComponent(location.pathname + location.search);
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

async function logout() {
  const client = await initAuth();
  await client.auth.signOut();
}

if (typeof module !== "undefined") {
  module.exports = { safeNext, initAuth, api, logout };
}
