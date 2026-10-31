// Shared behaviour for login.html and signup.html: status line, busy state,
// password eye toggle, Google button and the "already logged in" skip.
// Needs auth.js loaded first.

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const next = safeNext(params.get("next"));

function setStatus(msg, isError = false) {
  $("status").textContent = msg;
  $("status").classList.toggle("is-error", isError);
}

async function run(fn) {
  const buttons = document.querySelectorAll(".auth-form button, #google");
  for (const b of buttons) b.disabled = true;
  setStatus("");
  try { await fn(); } catch (err) { setStatus(err.message || "Something went wrong. Try again.", true); }
  for (const b of buttons) b.disabled = false;
}

function initAuthPage() {
  // Keep ?next= when switching between login and sign-up.
  for (const a of document.querySelectorAll("[data-keep-next]")) {
    if (next !== "/") a.href += "?next=" + encodeURIComponent(next);
  }

  $("show-password").addEventListener("click", (e) => {
    const show = $("password").type === "password";
    $("password").type = show ? "text" : "password";
    e.currentTarget.setAttribute("aria-pressed", String(show));
    e.currentTarget.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });

  $("google").addEventListener("click", () => run(async () => {
    const client = await initAuth();
    const { error } = await client.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: location.origin + next },
    });
    if (error) throw error;
  }));

  // Already logged in: skip the form.
  initAuth().then(async (client) => {
    const { data } = await client.auth.getSession();
    if (data.session) location = next;
  }).catch((err) => setStatus(err.message, true));
}
