// Shared behaviour for login.html and signup.html: status line, busy state,
// password eye toggle, Google button and the "already logged in" skip.
// Needs dom.js and auth.js loaded first.

const params = new URLSearchParams(location.search);
const next = safeNext(params.get("next"));

// kind: "info", "error" or "success"; sets the alert's colour and icon.
function setStatus(msg, kind = "info") {
  $("status").textContent = msg;
  $("status").dataset.kind = kind;
}

const FIELD_MESSAGES = {
  email: { valueMissing: "Enter your email.", typeMismatch: "That doesn't look like an email address." },
  password: { valueMissing: "Enter your password.", tooShort: "Use at least 6 characters." },
};

// Replaces the browser's validation bubbles with messages under each field.
// Returns true when the form can be sent; focuses the first bad field otherwise.
function validate(form) {
  let first = null;
  for (const input of form.querySelectorAll("input")) {
    const reason = Object.keys(FIELD_MESSAGES[input.id] || {}).find((k) => input.validity[k]);
    fieldError(input, reason ? FIELD_MESSAGES[input.id][reason] : "");
    if (reason && !first) first = input;
  }
  if (first) first.focus();
  return !first;
}

async function run(fn) {
  const buttons = document.querySelectorAll(".auth-form button, #google");
  for (const b of buttons) b.disabled = true;
  setStatus("");
  try { await fn(); } catch (err) { setStatus(err.message || "Something went wrong. Try again.", "error"); }
  for (const b of buttons) b.disabled = false;
}

// Touch screens have no hover: light the ring while a finger is on it,
// and keep it lit briefly after lifting so a quick tap is visible.
function lightOrbOnTouch() {
  const orb = $("orb");
  if (!orb) return;
  let timer = 0;
  orb.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    clearTimeout(timer);
    orb.classList.add("is-lit");
  });
  const release = () => { timer = setTimeout(() => orb.classList.remove("is-lit"), 700); };
  orb.addEventListener("pointerup", release);
  orb.addEventListener("pointercancel", release);
  orb.addEventListener("pointerleave", release);
}

function initAuthPage() {
  lightOrbOnTouch();
  const form = document.querySelector(".auth-form");
  form.noValidate = true;
  // Clear a field's message as soon as it's fixed.
  form.addEventListener("input", (e) => { if (e.target.validity.valid) fieldError(e.target, ""); });

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
  }).catch((err) => setStatus(err.message, "error"));
}
