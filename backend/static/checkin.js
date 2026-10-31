// Weekly check-in: Weight → Front → Side → Back → Done, one step per screen.
// Needs dom.js, auth.js, units.js, images.js, push.js and nav.js loaded first.
// The functions up to "Browser only" are pure so Node can test them (tests/checkin.test.js).

const STEPS = ["weight", "front", "side", "back", "done"];
const PHOTO_POSES = ["front", "side", "back"];
const POSE_NAME = { front: "Front", side: "Side", back: "Back" };
const PHOTO_MAX_SIDE = 1600;
const PHOTO_QUALITY = 0.8;

const stepLabel = (i) => `Step ${i + 1} of ${STEPS.length}`;

function doneSummary(weightKg, unit, photoCount) {
  const photos = `${photoCount} of ${PHOTO_POSES.length} photos`;
  return weightKg == null ? photos : `Weight ${formatWeight(weightKg, unit)} · ${photos}`;
}

// "Remind me next week?" only for someone who never chose: reminders off, the
// browser has not asked yet, and push works here.
function offerReminders(settings, permission, pushOk) {
  return !!settings && settings.reminders_enabled === false && permission === "default" && pushOk;
}

// POST /api/checkins: 201 created, 200 today's check-in already existed (a retry).
const checkinSaved = (status) => status === 201 || status === 200;


// ---------- Browser only below ----------

const CHECKIN_ERROR = "Couldn't save your check-in. Check your connection and try again.";
const NOT_UPLOADED = "Not uploaded – retry";
const UNREADABLE = "Couldn't read this photo. Take it again or choose another.";

let unit = "kg";
let step = 0;
let checkin = null;  // {id, checked_on, weight_kg} once created
let settings = null; // null when settings could not be loaded
// Per pose: state is empty | preparing | uploading | done | failed | unreadable.
// blob is the resized JPEG, kept for a retry (the original file is never sent).
const photos = {};

// ---------- Steps ----------

function showStep(i) {
  step = i;
  const name = STEPS[i];
  for (const [j, s] of STEPS.entries()) $(`step-${s}`).hidden = j !== i;
  const dots = $("ci-dots");
  dots.setAttribute("aria-label", stepLabel(i));
  [...dots.children].forEach((d, j) => d.classList.toggle("is-on", j === i));
  $("ci-back").hidden = !(i > 0 && name !== "done");
  if (name === "weight") renderWeight();
  if (PHOTO_POSES.includes(name)) renderPhoto(name);
  if (name === "done") showDone();
  $(`step-${name}`).querySelector(".step-title").focus();
  window.scrollTo(0, 0);
}

// ---------- Weight ----------

function renderWeight() {
  const input = $("ci-weight");
  const { min, max } = weightRange(unit);
  $("ci-unit").textContent = unit;
  $("ci-unit-label").textContent = unit;
  input.min = min;
  input.max = max;
  document.querySelector(`input[name="ci-unit"][value="${unit}"]`).checked = true;
  const saved = !!checkin;
  // The check-in exists: its weight can't be changed here any more.
  input.disabled = saved;
  document.querySelectorAll('input[name="ci-unit"]').forEach((r) => { r.disabled = saved; });
  $("ci-weight-skip").hidden = saved;
  if (saved) {
    input.value = checkin.weight_kg == null ? "" : fromKg(checkin.weight_kg, unit).toFixed(1);
    $("ci-weight-hint").textContent = checkin.weight_kg == null
      ? "Saved without a weight." : "Saved with this check-in.";
  } else {
    $("ci-weight-hint").textContent =
      `${min}–${max} ${unit}. One entry per day: a second entry today replaces the first.`;
  }
}

function changeUnit(next) {
  const input = $("ci-weight");
  const v = Number(input.value);
  if (input.value.trim() !== "" && Number.isFinite(v)) {
    input.value = fromKg(toKg(v, unit), next).toFixed(1);
  }
  unit = next;
  fieldError(input, "");
  renderWeight();
  saveSettings({ weight_unit: next }).catch(() => {}); // a preference only; the entry works either way
}

let creating = false;

async function leaveWeight(withWeight) {
  if (checkin) { showStep(1); return; }
  if (creating) return;
  const input = $("ci-weight");
  let kg = null;
  if (withWeight) {
    const err = weightError(input.value, unit);
    fieldError(input, err);
    if (err) { input.focus(); return; }
    kg = toKg(Number(input.value), unit);
  } else {
    fieldError(input, "");
  }
  const status = $("ci-weight-status");
  status.textContent = "";
  status.classList.remove("is-error");
  creating = true;
  $("ci-weight-next").disabled = $("ci-weight-skip").disabled = true;
  try {
    let res;
    try {
      res = await api("/api/checkins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked_on: isoDate(new Date()), weight_kg: kg }),
      });
    } catch (e) {
      throw new Error(CHECKIN_ERROR);
    }
    if (!checkinSaved(res.status)) {
      const body = await res.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" && res.status < 500 ? body.detail : CHECKIN_ERROR);
    }
    checkin = await res.json();
    showStep(1);
  } catch (err) {
    status.textContent = err.message;
    status.classList.add("is-error");
  } finally {
    creating = false;
    $("ci-weight-next").disabled = $("ci-weight-skip").disabled = false;
  }
}

// ---------- Photos ----------

function buildPhotoSteps() {
  const tpl = $("photo-step-template");
  for (const [k, pose] of PHOTO_POSES.entries()) {
    photos[pose] = { state: "empty", blob: null, preview: null, seq: 0, pending: null };
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.id = `step-${pose}`;
    node.setAttribute("aria-labelledby", `${pose}-title`);
    node.querySelector(".step-count").textContent = stepLabel(k + 1);
    const title = node.querySelector(".step-title");
    title.id = `${pose}-title`;
    title.textContent = `${POSE_NAME[pose]} photo`;
    const input = node.querySelector("input[type=file]");
    input.id = `photo-${pose}`;
    node.querySelector(".drop-title").textContent = `Take or choose a ${pose} photo`;
    node.querySelector(".photo-preview").alt = `Your ${pose} photo`;
    input.addEventListener("change", () => photoChosen(pose, input));
    node.querySelector(".photo-skip").addEventListener("click", () => showStep(k + 2));
    node.querySelector(".photo-main").addEventListener("click", () => {
      const st = photos[pose].state;
      if (st === "failed") uploadPhoto(pose);
      else if (st === "done") showStep(k + 2);
      else input.click();
    });
    $("photo-steps").append(node);
  }
}

function renderPhoto(pose) {
  const p = photos[pose];
  const node = $(`step-${pose}`);
  const drop = node.querySelector(".photo-drop");
  const img = node.querySelector(".photo-preview");
  const status = node.querySelector(".photo-status");
  const main = node.querySelector(".photo-main");
  img.hidden = !p.preview;
  if (p.preview && img.src !== p.preview) img.src = p.preview;
  node.querySelector(".drop-empty").hidden = !!p.preview;
  drop.classList.toggle("has-photo", !!p.preview);
  drop.classList.toggle("is-busy", p.state === "uploading" || p.state === "preparing");
  drop.classList.toggle("is-failed", p.state === "failed");
  const text = {
    preparing: "Preparing the photo…", uploading: "Uploading…", done: "Photo saved. Tap it to take it again.",
    failed: NOT_UPLOADED, unreadable: UNREADABLE,
  }[p.state] || "";
  status.textContent = text;
  status.classList.toggle("is-error", p.state === "failed" || p.state === "unreadable");
  const busy = p.state === "uploading" || p.state === "preparing";
  main.disabled = busy;
  // No new file while one is being prepared or sent.
  node.querySelector("input[type=file]").disabled = busy;
  main.textContent = { uploading: "Uploading…", preparing: "Uploading…", done: "Next", failed: "Retry" }[p.state] || "Take photo";
  node.querySelector(".photo-skip").hidden = p.state === "done";
}

async function photoChosen(pose, input) {
  const file = input.files && input.files[0];
  input.value = ""; // choosing the same file again still fires change
  if (!file) return;
  const p = photos[pose];
  const seq = ++p.seq;
  p.state = "preparing";
  renderPhoto(pose);
  let blob;
  try {
    blob = await resizeImage(file, PHOTO_MAX_SIDE, PHOTO_QUALITY);
  } catch (e) {
    if (seq !== p.seq) return;
    p.state = "unreadable";
    renderPhoto(pose);
    return;
  }
  if (seq !== p.seq) return;
  if (p.preview) URL.revokeObjectURL(p.preview);
  p.blob = blob;
  p.preview = URL.createObjectURL(blob);
  uploadPhoto(pose);
}

// upload-url → PUT the resized bytes → record. Never blocks the other steps.
function uploadPhoto(pose) {
  const p = photos[pose];
  if (!p.blob || !checkin) return Promise.resolve();
  const seq = ++p.seq;
  // This upload sends this blob, even if a newer photo replaces p.blob meanwhile.
  const blob = p.blob;
  p.state = "uploading";
  renderPhoto(pose);
  const run = (async () => {
    const base = `/api/checkins/${checkin.id}/photos`;
    const json = { "Content-Type": "application/json" };
    const r1 = await api(`${base}/upload-url`, { method: "POST", headers: json, body: JSON.stringify({ pose }) });
    if (!r1.ok) throw new Error("upload-url");
    const { upload_url, path } = await r1.json();
    const put = await fetch(upload_url, { method: "PUT", headers: { "content-type": "image/jpeg" }, body: blob });
    if (!put.ok) throw new Error("put");
    const r2 = await api(base, { method: "POST", headers: json, body: JSON.stringify({ pose, path }) });
    if (r2.status !== 201) throw new Error("record");
  })().then(() => "done", () => "failed").then((state) => {
    if (seq !== p.seq) return; // a newer photo for this pose took over
    p.state = state;
    renderPhoto(pose);
    if (STEPS[step] === "done") renderDoneSummary();
  });
  p.pending = run;
  return run;
}

// ---------- Done ----------

const photoCount = () => PHOTO_POSES.filter((pose) => photos[pose].state === "done").length;

function renderDoneSummary() {
  const busy = PHOTO_POSES.some((pose) => ["uploading", "preparing"].includes(photos[pose].state));
  const weightKg = checkin ? checkin.weight_kg : null;
  $("done-summary").textContent = busy
    ? "Saving photos…" : doneSummary(weightKg, unit, photoCount());
  const list = $("done-retry");
  list.replaceChildren();
  for (const pose of PHOTO_POSES) {
    if (photos[pose].state !== "failed") continue;
    const btn = el("button", { type: "button", className: "btn btn-outline btn-small" },
      `${POSE_NAME[pose]} photo: ${NOT_UPLOADED}`);
    btn.addEventListener("click", () => { uploadPhoto(pose); renderDoneSummary(); });
    list.append(el("li", {}, btn));
  }
}

let remindDecided = false;

function showDone() {
  renderDoneSummary();
  const pushOk = pushSupported();
  const ask = !remindDecided && offerReminders(settings, pushOk ? Notification.permission : "", pushOk);
  $("remind").hidden = !ask;
  if (ask) preloadPushKey().catch(() => {}); // so the permission prompt follows the tap quickly
}

async function remindYes() {
  const status = $("remind-status");
  status.classList.remove("is-error");
  status.textContent = "";
  $("remind-yes").disabled = $("remind-no").disabled = true;
  try {
    const result = await enableReminders();
    const text = {
      enabled: "Reminders are on. You can turn them off in Settings.",
      blocked: REMINDERS_BLOCKED,
      unavailable: "Reminders aren't available yet.",
      unsupported: "This browser can't show reminders.",
      dismissed: "No reminders for now. You can turn them on in Settings.",
    }[result];
    status.textContent = text;
    status.classList.toggle("is-error", result === "blocked" || result === "unavailable");
    remindDecided = true;
    $("remind").hidden = true;
  } catch (err) {
    status.textContent = err.message;
    status.classList.add("is-error");
  } finally {
    $("remind-yes").disabled = $("remind-no").disabled = false;
  }
}

// ---------- Wiring and start ----------

function wire() {
  buildPhotoSteps();
  $("ci-weight-form").addEventListener("submit", (e) => { e.preventDefault(); leaveWeight(true); });
  $("ci-weight-skip").addEventListener("click", () => leaveWeight(false));
  $("ci-weight").addEventListener("input", (e) => { if (!weightError(e.target.value, unit)) fieldError(e.target, ""); });
  document.querySelectorAll('input[name="ci-unit"]').forEach((r) =>
    r.addEventListener("change", () => changeUnit(r.value)));
  $("ci-back").addEventListener("click", () => { if (step > 0) showStep(step - 1); });
  $("remind-yes").addEventListener("click", remindYes);
  $("remind-no").addEventListener("click", () => { remindDecided = true; $("remind").hidden = true; });
  // Leaving while a photo is still uploading would lose it.
  window.addEventListener("beforeunload", (e) => {
    if (PHOTO_POSES.some((pose) => ["uploading", "preparing"].includes(photos[pose].state))) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

async function start() {
  try {
    const client = await initAuth();
    const { data } = await client.auth.getSession();
    if (!data.session) {
      location = "/login.html?next=" + encodeURIComponent(location.pathname + location.search);
      return;
    }
    const me = await api("/api/me"); // api() sends 401s to the login page
    if (me.status === 404) {
      location = "/welcome.html";
      return;
    }
    if (!me.ok) {
      const body = await me.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't load your account. Try again.");
    }
  } catch (err) {
    $("page-status").textContent = err.message || "Couldn't load your account. Try again.";
    return;
  }
  try {
    settings = await loadSettings();
    unit = settings.weight_unit === "lb" ? "lb" : "kg";
  } catch (e) {
    settings = null; // kg, and no reminder offer: we can't tell whether it was already answered
  }
  showStep(0);
}

if (typeof module !== "undefined") {
  module.exports = { STEPS, stepLabel, doneSummary, offerReminders, checkinSaved };
} else {
  wire();
  start();
}
