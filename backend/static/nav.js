// Shared by the app pages: bottom bar, Settings panel and the settings cache.
// Needs auth.js (api, logout) loaded first, push.js for the reminders switch and
// install.js for "Install app".
// settingsBody and legacySettings are pure so Node can test them (tests/nav.test.js).

const SETTINGS_DEFAULTS = {
  height_cm: null, weight_kg: null, age: null, sex: null, activity: null,
  weight_goal: null, goal_kcal: null, goal_weight_kg: null, weight_unit: "kg", reminders_enabled: false,
};

// PUT /api/settings replaces every field, so a partial change is merged into the
// last loaded settings and the whole object is sent. goal_set_by is server-owned.
function settingsBody(current, partial) {
  const body = {};
  for (const [key, fallback] of Object.entries(SETTINGS_DEFAULTS)) {
    if (partial && key in partial) body[key] = partial[key];
    else if (current && current[key] !== undefined) body[key] = current[key];
    else body[key] = fallback;
  }
  return body;
}

// The calculator and goal used to live in localStorage ("profile", "goal").
// Returns the fields to move to the server (only values it would accept), or
// null when nothing is stored. A weight already on the server is kept: it came
// from the weight log, which is newer than the browser's copy.
function legacySettings(rawProfile, rawGoal, server) {
  if (rawProfile == null && rawGoal == null) return null;
  const out = {};
  let p = null;
  try { p = JSON.parse(rawProfile); } catch (e) { /* unreadable: nothing to move */ }
  const num = (v, min, max) => (typeof v === "number" && v >= min && v <= max ? v : undefined);
  const pick = (v, allowed) => (allowed.includes(v) ? v : undefined);
  if (p && typeof p === "object") {
    out.height_cm = num(p.heightCm, 120, 230);
    out.weight_kg = num(p.weightKg, 30, 300);
    out.age = Number.isInteger(p.age) ? num(p.age, 18, 100) : undefined;
    out.sex = pick(p.sex, ["male", "female", "unspecified"]);
    out.activity = pick(p.activity, [1.2, 1.375, 1.55, 1.725, 1.9]);
    out.weight_goal = pick(p.goal, ["lose", "maintain", "gain"]);
    if (out.weight_kg !== undefined && server && server.weight_kg != null) delete out.weight_kg;
  }
  if (rawGoal != null) {
    const g = Math.round(Number(rawGoal));
    if (g >= 500 && g <= 9000) out.goal_kcal = g;
  }
  for (const k of Object.keys(out)) if (out[k] === undefined) delete out[k];
  return out;
}


// ---------- Settings cache (browser only below) ----------

const SAVE_ERROR = "Couldn't save your settings. Check your connection and try again.";
let settingsPromise = null;   // one GET per page
let lastSettings = null;      // what the server last returned
let saveChain = Promise.resolve();

async function settingsError(res, fallback) {
  const body = await res.json().catch(() => ({}));
  return new Error(typeof body.detail === "string" ? body.detail : fallback);
}

function readLegacy() {
  try { return [localStorage.getItem("profile"), localStorage.getItem("goal")]; }
  catch (e) { return [null, null]; }
}

function dropLegacy() {
  try { localStorage.removeItem("profile"); localStorage.removeItem("goal"); } catch (e) { /* blocked */ }
}

// One-time move of old browser settings. Never overwrites settings already saved
// on the server. Keys are removed on 200, on 409, or when nothing valid is left.
async function moveLegacySettings(server) {
  const [rawProfile, rawGoal] = readLegacy();
  const fields = legacySettings(rawProfile, rawGoal, server);
  if (fields === null) return server;
  if (Object.keys(fields).length === 0) { dropLegacy(); return server; }
  try {
    const res = await api("/api/settings?only_if_empty=1", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    if (res.ok) { dropLegacy(); return await res.json(); }
    if (res.status === 409) dropLegacy(); // the server already has settings: keep those
    // Any other answer (422, 5xx) keeps the keys for the next load.
  } catch (e) { /* offline: keep the keys and try on the next load */ }
  return server;
}

async function getSettings(fallback) {
  let res;
  try {
    res = await api("/api/settings");
  } catch (e) {
    throw new Error(fallback);
  }
  if (!res.ok) throw await settingsError(res, fallback);
  return res.json();
}

async function fetchSettings() {
  return moveLegacySettings(await getSettings("Couldn't load your settings. Check your connection."));
}

function loadSettings() {
  if (!settingsPromise) {
    settingsPromise = fetchSettings().then((s) => (lastSettings = s));
    settingsPromise.catch(() => { settingsPromise = null; }); // let the next call retry
  }
  return settingsPromise;
}

// Saves run one after another, so a second quick change merges onto the first.
// Each save merges into a fresh copy from the server, not the page's cache: the
// page may be hours old and another device may have changed the weight or
// reminders since, which a full-object PUT would otherwise reset.
function saveSettings(partial) {
  const run = saveChain.then(async () => {
    await loadSettings(); // the one-time browser-settings move happens first
    const current = await getSettings(SAVE_ERROR);
    let res;
    try {
      res = await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settingsBody(current, partial)),
      });
    } catch (e) {
      throw new Error(SAVE_ERROR);
    }
    if (!res.ok) throw await settingsError(res, SAVE_ERROR);
    lastSettings = await res.json();
    settingsPromise = Promise.resolve(lastSettings);
    document.dispatchEvent(new CustomEvent("settingschange", { detail: lastSettings }));
    return lastSettings;
  });
  saveChain = run.catch(() => {});
  return run;
}

// Drops the cached settings and loads them again, e.g. after the reminders
// routes changed reminders_enabled on the server. Queued behind pending saves.
function refreshSettings() {
  const run = saveChain.then(async () => {
    settingsPromise = null;
    const s = await loadSettings();
    document.dispatchEvent(new CustomEvent("settingschange", { detail: s }));
    return s;
  });
  saveChain = run.catch(() => {});
  return run;
}

// ---------- Bottom bar and Settings panel ----------

const TABS = [
  { id: "today", href: "/", label: "Today",
    icon: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>' },
  { id: "progress", href: "/progress.html", label: "Progress",
    icon: '<path d="M4 18l5-6 4 3 7-9"/><path d="M4 21h16"/>' },
  { id: "workout", href: "/workout.html", label: "Workout",
    icon: '<path d="M6 7v10M18 7v10M3 10v4M21 10v4M6 12h12"/>' },
];

function renderTabbar(active) {
  const nav = document.createElement("nav");
  nav.className = "tabbar";
  nav.setAttribute("aria-label", "Main");
  for (const tab of TABS) {
    const a = document.createElement("a");
    a.href = tab.href;
    a.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${tab.icon}</svg>`;
    a.append(tab.label);
    if (tab.id === active) a.setAttribute("aria-current", "page");
    nav.append(a);
  }
  document.body.append(nav);
  document.body.classList.add("has-tabbar");
}

const REMINDERS_HINT = "A notification when your weekly check-in is due.";
const REMINDERS_BLOCKED = "Notifications are blocked. In Chrome: ⋮ → Settings → Site settings → Notifications";
const REMINDERS_UNAVAILABLE = "Reminders aren't available yet.";
const REMINDERS_UNSUPPORTED = "This browser can't show reminders.";
const REMINDERS_IOS = "On iPhone, reminders work once you add the app to your Home Screen (see below).";

const INSTALL_HINTS = {
  prompt: "Add Tracker to your home screen. It opens full-screen, like an app.",
  ios: "Tap the Share button, then \u201cAdd to Home Screen\u201d.",
  manual: "In your browser's menu, choose \u201cInstall app\u201d or \u201cAdd to Home screen\u201d.",
};

const SETTINGS_HTML = `
  <div class="settings-head">
    <h2 id="settings-title" class="section-title">Settings</h2>
    <button class="icon-round icon-close" type="button" id="settings-close" aria-label="Close settings">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>
    </button>
  </div>
  <fieldset class="meal-type settings-unit">
    <legend>Weight unit</legend>
    <div class="meal-type-options">
      <label><input type="radio" name="weight-unit" value="kg">kg</label>
      <label><input type="radio" name="weight-unit" value="lb">lb</label>
    </div>
  </fieldset>
  <div class="settings-reminders" id="settings-reminders">
    <label class="switch-row">
      <span>Weekly reminders</span>
      <input type="checkbox" role="switch" id="reminders-switch" class="switch" aria-describedby="reminders-hint">
    </label>
    <p class="hint" id="reminders-hint">A notification when your weekly check-in is due.</p>
  </div>
  <div class="settings-coach">
    <label class="switch-row">
      <span>Show coach</span>
      <input type="checkbox" role="switch" id="coach-switch" class="switch" aria-describedby="coach-hint">
    </label>
    <p class="hint" id="coach-hint">Coach Ollie's tips on the Today page, on this device.</p>
  </div>
  <div class="settings-install" id="settings-install" hidden>
    <div class="switch-row">
      <span>Install app</span>
      <button class="btn btn-outline" type="button" id="install-app" hidden>Install</button>
    </div>
    <p class="hint" id="install-hint"></p>
  </div>
  <p class="status" id="settings-status" role="status" aria-live="polite"></p>
  <button class="btn settings-logout" type="button" id="logout">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/></svg>
    <span id="logout-label">Log out</span>
  </button>`;

// Coach Ollie on/off is per device; blocked storage means "on".
const COACH_OFF_KEY = "coach-off";
function coachEnabled() {
  try { return localStorage.getItem(COACH_OFF_KEY) !== "1"; } catch (e) { return true; }
}
function setCoachEnabled(on) {
  try { if (on) localStorage.removeItem(COACH_OFF_KEY); else localStorage.setItem(COACH_OFF_KEY, "1"); } catch (e) { /* blocked */ }
  document.dispatchEvent(new Event("coachchange"));
}

function renderSettingsPanel() {
  const dialog = document.createElement("dialog");
  dialog.className = "calc settings";
  dialog.id = "settings";
  dialog.setAttribute("aria-labelledby", "settings-title");
  dialog.innerHTML = SETTINGS_HTML;
  document.body.append(dialog);

  const status = dialog.querySelector("#settings-status");
  const setPanelStatus = (msg, isError) => {
    status.textContent = msg;
    status.classList.toggle("is-error", !!isError);
  };
  const showUnit = (unit) => {
    const radio = dialog.querySelector(`input[name="weight-unit"][value="${unit}"]`);
    if (radio) radio.checked = true;
  };

  // Weekly reminders switch: reflects reminders_enabled; a blocked permission
  // shows how to unblock it and keeps the switch off.
  const remSwitch = dialog.querySelector("#reminders-switch");
  const remHint = dialog.querySelector("#reminders-hint");
  const showReminders = (enabled) => {
    const supported = typeof pushSupported === "function" && pushSupported();
    const blocked = supported && Notification.permission === "denied";
    remSwitch.checked = !!enabled && supported && !blocked;
    remSwitch.disabled = !supported || blocked;
    const iosBrowser = typeof isIos === "function" && isIos(navigator.userAgent, navigator.maxTouchPoints || 0)
      && !isStandalone();
    remHint.textContent = !supported ? (iosBrowser ? REMINDERS_IOS : REMINDERS_UNSUPPORTED)
      : blocked ? REMINDERS_BLOCKED : REMINDERS_HINT;
    remHint.classList.toggle("is-blocked", blocked);
  };
  remSwitch.addEventListener("change", async () => {
    setPanelStatus("");
    const want = remSwitch.checked;
    remSwitch.disabled = true;
    try {
      if (want) {
        const result = await enableReminders();
        if (result === "unavailable") setPanelStatus(REMINDERS_UNAVAILABLE, true);
        showReminders(result === "enabled");
      } else {
        await disableReminders();
        showReminders(false);
      }
    } catch (err) {
      setPanelStatus(err.message, true);
      showReminders(lastSettings ? lastSettings.reminders_enabled : !want);
    }
  });

  const coachSwitch = dialog.querySelector("#coach-switch");
  coachSwitch.checked = coachEnabled();
  coachSwitch.addEventListener("change", () => setCoachEnabled(coachSwitch.checked));

  // Install app: Chrome's dialog, the iPhone steps, or nothing once installed.
  const installBox = dialog.querySelector("#settings-install");
  const installBtn = dialog.querySelector("#install-app");
  const showInstall = () => {
    const mode = typeof currentInstallMode === "function" ? currentInstallMode() : "installed";
    installBox.hidden = mode === "installed";
    installBtn.hidden = mode !== "prompt";
    dialog.querySelector("#install-hint").textContent = INSTALL_HINTS[mode] || "";
  };
  installBtn.addEventListener("click", async () => {
    await promptInstall();
    showInstall();
  });
  document.addEventListener("installchange", showInstall);
  showInstall();

  dialog.querySelector("#settings-close").addEventListener("click", () => dialog.close());
  dialog.querySelectorAll('input[name="weight-unit"]').forEach((radio) => {
    radio.addEventListener("change", async () => {
      setPanelStatus("");
      try {
        await saveSettings({ weight_unit: radio.value });
      } catch (err) {
        setPanelStatus(err.message, true);
        if (lastSettings) showUnit(lastSettings.weight_unit);
      }
    });
  });
  // Log out asks once: the first tap turns the button into "Tap again to log out" for 3 s.
  const logoutBtn = dialog.querySelector("#logout");
  const logoutLabel = dialog.querySelector("#logout-label");
  let logoutTimer = 0;
  const resetLogout = () => {
    clearTimeout(logoutTimer);
    logoutBtn.classList.remove("is-confirming");
    logoutLabel.textContent = "Log out";
  };
  dialog.addEventListener("close", resetLogout);
  logoutBtn.addEventListener("click", async () => {
    if (!logoutBtn.classList.contains("is-confirming")) {
      logoutBtn.classList.add("is-confirming");
      logoutLabel.textContent = "Tap again to log out";
      logoutTimer = setTimeout(resetLogout, 3000);
      return;
    }
    clearTimeout(logoutTimer);
    logoutBtn.disabled = true;
    logoutLabel.textContent = "Logging out…";
    // While still logged in: stop this browser's reminders (account setting untouched).
    if (typeof forgetThisDevice === "function") await forgetThisDevice();
    try { await logout(); } catch (e) { /* logout clears what it can; leave either way */ }
    location = "/login.html";
  });

  const open = document.createElement("button");
  open.className = "icon-round settings-open";
  open.type = "button";
  open.id = "settings-open";
  open.setAttribute("aria-haspopup", "dialog");
  open.setAttribute("aria-label", "Settings");
  open.setAttribute("aria-expanded", "false");
  dialog.addEventListener("close", () => open.setAttribute("aria-expanded", "false"));
  open.innerHTML = `<svg class="gear" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
  open.addEventListener("click", async () => {
    setPanelStatus("");
    showInstall();
    dialog.showModal();
    open.setAttribute("aria-expanded", "true");
    if (typeof preloadPushKey === "function" && pushSupported()) preloadPushKey().catch(() => {});
    try {
      const settings = await loadSettings();
      showUnit(settings.weight_unit);
      showReminders(settings.reminders_enabled);
    } catch (err) {
      setPanelStatus(err.message, true);
    }
  });
  const masthead = document.querySelector(".masthead");
  if (masthead) masthead.append(open);
}

// active: "today" or "progress".
function initNav(active) {
  renderTabbar(active);
  renderSettingsPanel();
}

if (typeof module !== "undefined") {
  module.exports = { settingsBody, legacySettings, moveLegacySettings, loadSettings, saveSettings, refreshSettings, SETTINGS_DEFAULTS };
}
