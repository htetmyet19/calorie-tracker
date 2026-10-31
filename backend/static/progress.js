// Progress page: check-in card, weight chart, calories vs goal, check-in timeline.
// Needs dom.js, auth.js, units.js, charts.js and nav.js loaded first.
// The functions up to "Browser only" are pure so Node can test them (tests/progress.test.js).

const WEIGHT_DAYS = 84;      // 12 weeks
const CALORIE_DAYS = 7;
const DEFAULT_GOAL = 2000;   // as on Today when no goal is saved
const CHECKIN_LIMIT = 12;    // photos are full-size: keep the timeline to ~3 months
const URL_FRESH_MS = 240000; // signed photo links last 300 s; refresh a little before
const POSES = ["front", "side", "back"];
const POSE_LABEL = { front: "Front", side: "Side", back: "Back" };

const shortDate = (iso) => parseDate(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const kcal = (n) => Math.round(n).toLocaleString("en-IN");
const daysBetween = (a, b) => Math.round((parseDate(b) - parseDate(a)) / 86400000);

function checkinText(data, today) {
  if (data.due) return "Weekly check-in due";
  const n = Math.max(1, daysBetween(today, data.next_due_on));
  return `Next check-in in ${n} ${n === 1 ? "day" : "days"}`;
}

// weights: [{logged_on, weight_kg}] oldest first. The change is taken from the
// values as shown (one decimal in the unit), so it matches what the user reads.
function weightSummary(weights, unit) {
  if (!weights.length) return null;
  const first = weights[0], last = weights[weights.length - 1];
  const latest = formatWeight(last.weight_kg, unit);
  if (weights.length === 1) return { latest, change: "First entry" };
  const diff = Math.round((fromKg(last.weight_kg, unit) - fromKg(first.weight_kg, unit)) * 10) / 10;
  const since = `since ${shortDate(first.logged_on)}`;
  if (diff === 0) return { latest, change: `No change ${since}` };
  const sign = diff > 0 ? "+" : "−";
  return { latest, change: `${sign}${Math.abs(diff).toFixed(1)} ${unit} ${since}` };
}

function weightLabel(weights, unit) {
  const first = weights[0], last = weights[weights.length - 1];
  if (weights.length === 1) return `Weight over 12 weeks: one entry, ${formatWeight(last.weight_kg, unit)}`;
  return `Weight over 12 weeks: from ${formatWeight(first.weight_kg, unit)} to ${formatWeight(last.weight_kg, unit)}`;
}

function caloriesLabel(days, goal) {
  const parts = days.map((d) =>
    `${shortDate(d.date)} ${kcal(d.total_calories)}${d.total_calories > goal ? " (over)" : ""}`);
  return `Calories over the last ${days.length} days against a goal of ${kcal(goal)} kcal: ${parts.join(", ")}`;
}

function dateError(value, today) {
  if (!value) return "Choose a date.";
  if (value > today) return "The date can't be in the future.";
  return "";
}

function photoFor(checkin, pose) {
  return checkin.photos.find((p) => p.pose === pose) || null;
}

function missingPhotoText(pose, date) {
  return `No ${pose} photo on ${shortDate(date)}`;
}

const photoViewTitle = (pose, date) => `${POSE_LABEL[pose]} photo, ${shortDate(date)}`;

const DELETE_PHOTO_CONFIRM = "Delete this photo? This can't be undone.";

// status: the DELETE response status, null when the request itself failed.
// 404 means it is already gone (another tab or device), which is what was wanted.
function photoDeleteError(status) {
  return status === 204 || status === 404 ? "" : "Couldn't delete the photo. Check your connection and try again.";
}


// ---------- Browser only below ----------

let unit = "kg";
let goal = DEFAULT_GOAL;
let weights = null;       // last loaded weights, re-drawn when the unit changes
let days = null;          // last loaded daily totals
let checkins = null;      // last loaded check-ins (newest first)
let checkinsAt = 0;       // when their signed links were made
let settingsReady = null; // resolves once unit and goal are known (or defaulted)

const today = () => isoDate(new Date());

function setMsg(id, msg) {
  $(id).textContent = msg;
}

function busy(section, on) {
  section.setAttribute("aria-busy", String(on));
}

async function getJson(path, fallback) {
  let res;
  try {
    res = await api(path);
  } catch (e) {
    throw new Error(fallback);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" && res.status < 500 ? body.detail : fallback);
  }
  return res.json();
}

// ---------- Check-in card and timeline ----------

async function loadCheckins() {
  const card = $("checkin-when").closest("section");
  const timeline = $("timeline").closest("section");
  setMsg("checkin-status", "");
  setMsg("timeline-status", "");
  try {
    const t = today();
    const data = await getJson(`/api/checkins?today=${t}&limit=${CHECKIN_LIMIT}`,
      "Couldn't load your check-ins. Check your connection and reload.");
    checkins = data.checkins;
    checkinsAt = Date.now();
    setMsg("checkin-when", checkinText(data, t));
    $("checkin-start").hidden = !data.due;
    renderTimeline();
  } catch (err) {
    setMsg("checkin-status", err.message);
    setMsg("timeline-status", err.message);
  } finally {
    busy(card, false);
    busy(timeline, false);
  }
}

function thumb(checkin, pose) {
  const p = photoFor(checkin, pose);
  const label = `${POSE_LABEL[pose]}, ${shortDate(checkin.checked_on)}`;
  const fig = el("figure", { className: "thumb-pose" });
  if (p) {
    // Lazy: only photos scrolled into view are downloaded. loading is set before
    // src, or a browser may start the download as soon as src is assigned.
    const img = document.createElement("img");
    for (const [k, v] of [["loading", "lazy"], ["decoding", "async"], ["width", "96"], ["height", "128"], ["alt", label]]) {
      img.setAttribute(k, v);
    }
    img.src = p.url;
    // Tapping opens the photo full size, where it can be deleted.
    const open = el("button", { className: "thumb-open", type: "button", ariaLabel: `Open ${label} photo` }, img);
    open.addEventListener("click", () => openPhoto(checkin, p));
    img.addEventListener("error", () => open.replaceWith(el("span", { className: "thumb-missing" }, "Couldn't load")), { once: true });
    fig.append(open);
  } else {
    fig.append(el("span", { className: "thumb-missing" }, "No photo"));
  }
  fig.append(el("figcaption", {}, POSE_LABEL[pose]));
  return fig;
}

function renderTimeline() {
  const list = $("timeline");
  list.replaceChildren();
  if (!checkins) return;
  $("timeline-empty").hidden = checkins.length > 0;
  $("compare-open").hidden = checkins.length < 2;
  for (const c of checkins) {
    const head = el("p", { className: "timeline-date" },
      el("time", { dateTime: c.checked_on }, shortDate(c.checked_on)));
    if (c.weight_kg != null) head.append(el("span", { className: "timeline-weight" }, formatWeight(c.weight_kg, unit)));
    list.append(el("li", {}, head, el("div", { className: "timeline-photos" }, ...POSES.map((p) => thumb(c, p)))));
  }
}

// ---------- One photo, full size, with delete ----------

let viewing = null; // the photo open in the viewer

function openPhoto(checkin, photo) {
  viewing = photo;
  const title = photoViewTitle(photo.pose, checkin.checked_on);
  $("photo-dialog-title").textContent = title;
  const img = $("photo-dialog-img");
  img.hidden = false;
  img.alt = title;
  img.src = photo.url;
  setMsg("photo-dialog-status", "");
  $("photo-delete").disabled = false;
  $("photo-dialog").showModal();
}

async function deleteViewedPhoto() {
  if (!viewing || !confirm(DELETE_PHOTO_CONFIRM)) return;
  const btn = $("photo-delete");
  btn.disabled = true;
  let status = null;
  try {
    status = (await api(`/api/progress-photos/${viewing.id}`, { method: "DELETE" })).status;
  } catch (e) { /* network down: status stays null */ }
  const err = photoDeleteError(status);
  if (err) {
    setMsg("photo-dialog-status", err);
    btn.disabled = false;
    return;
  }
  $("photo-dialog").close();
  await loadCheckins();
}

// ---------- Compare ----------

function fillCompareSelects() {
  const a = $("compare-a"), b = $("compare-b");
  const keepA = a.value, keepB = b.value;
  for (const sel of [a, b]) {
    sel.replaceChildren(...checkins.map((c) => el("option", { value: c.checked_on }, shortDate(c.checked_on))));
  }
  const dates = checkins.map((c) => c.checked_on);
  // Default: oldest loaded against newest.
  a.value = dates.includes(keepA) ? keepA : dates[dates.length - 1];
  b.value = dates.includes(keepB) ? keepB : dates[0];
}

function comparePane(date, pose) {
  const c = checkins.find((x) => x.checked_on === date);
  const p = c && photoFor(c, pose);
  const fig = el("figure", { className: "compare-pane" });
  if (p) {
    const img = el("img", { src: p.url, alt: `${POSE_LABEL[pose]}, ${shortDate(date)}`, decoding: "async" });
    img.addEventListener("error", () => img.replaceWith(el("p", { className: "compare-missing" },
      "Couldn't load this photo. Close and open Compare to try again.")), { once: true });
    fig.append(img);
  } else {
    fig.append(el("p", { className: "compare-missing" }, missingPhotoText(pose, date)));
  }
  fig.append(el("figcaption", {}, el("time", { dateTime: date }, shortDate(date))));
  return fig;
}

function renderCompare() {
  const pose = document.querySelector('input[name="compare-pose"]:checked').value;
  $("compare-pair").replaceChildren(comparePane($("compare-a").value, pose), comparePane($("compare-b").value, pose));
}

async function openCompare() {
  // Signed links expire after 5 minutes: fetch fresh ones if these are old.
  if (Date.now() - checkinsAt > URL_FRESH_MS) await loadCheckins();
  if (!checkins || checkins.length < 2) return;
  fillCompareSelects();
  renderCompare();
  $("compare").showModal();
}

// ---------- Weight ----------

async function loadWeights() {
  const section = $("weight-section");
  setMsg("weight-status", "");
  busy(section, true);
  try {
    const t = today();
    weights = await getJson(`/api/weights?from=${addDays(t, -(WEIGHT_DAYS - 1))}&to=${t}`,
      "Couldn't load your weights. Check your connection and reload.");
    await settingsReady;
    renderWeights();
  } catch (err) {
    setMsg("weight-status", err.message);
  } finally {
    busy(section, false);
  }
}

function renderWeights() {
  if (!weights) return;
  const svg = $("weight-chart");
  const summary = weightSummary(weights, unit);
  $("weight-empty").hidden = !!summary;
  $("weight-summary").hidden = !summary;
  svg.hidden = !summary;
  svg.replaceChildren();
  if (!summary) return;
  setMsg("weight-latest", summary.latest);
  setMsg("weight-change", summary.change);

  const W = 320, H = 150, PAD = 14, LABEL = 20; // bottom strip for the date labels
  const values = weights.map((w) => ({ date: w.logged_on, value: fromKg(w.weight_kg, unit) }));
  const points = linePoints(values, W, H - LABEL, PAD);
  svg.setAttribute("aria-label", weightLabel(weights, unit));
  svg.append(svgEl("line", { class: "axis", x1: 0, x2: W, y1: H - LABEL, y2: H - LABEL }));
  if (values.length > 1) svg.append(svgEl("polyline", { class: "line", points }));
  for (const p of points.split(" ")) {
    const [cx, cy] = p.split(",");
    svg.append(svgEl("circle", { class: "dot", cx, cy, r: 3.5 }));
  }
  const first = svgEl("text", { class: "tick", x: 0, y: H - 4 });
  first.textContent = shortDate(values[0].date);
  svg.append(first);
  if (values.length > 1) {
    const last = svgEl("text", { class: "tick", x: W, y: H - 4, "text-anchor": "end" });
    last.textContent = shortDate(values[values.length - 1].date);
    svg.append(last);
  }
}

function openWeightDialog() {
  const t = today();
  const range = weightRange(unit);
  const date = $("w-date"), value = $("w-value");
  date.value = t;
  date.max = t;
  value.min = range.min;
  value.max = range.max;
  value.value = "";
  if (weights && weights.length) value.placeholder = String(fromKg(weights[weights.length - 1].weight_kg, unit));
  setMsg("w-unit", unit);
  fieldError(date, "");
  fieldError(value, "");
  setMsg("weight-form-status", "");
  $("weight-form-status").classList.remove("is-error");
  $("weight-dialog").showModal();
  value.focus();
}

async function saveWeight(e) {
  e.preventDefault();
  const t = today();
  const date = $("w-date"), value = $("w-value");
  const dErr = dateError(date.value, t), wErr = weightError(value.value, unit);
  fieldError(date, dErr);
  fieldError(value, wErr);
  if (dErr || wErr) {
    (dErr ? date : value).focus();
    return;
  }
  const status = $("weight-form-status");
  const save = $("weight-save");
  status.classList.remove("is-error");
  setMsg("weight-form-status", "Saving…");
  save.disabled = true;
  try {
    let res;
    try {
      res = await api(`/api/weights/${date.value}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weight_kg: toKg(Number(value.value), unit) }),
      });
    } catch (err) {
      throw new Error("Couldn't save. Check your connection and try again.");
    }
    if (!res.ok) throw new Error(res.status === 422
      ? `Enter a weight between ${weightRange(unit).min} and ${weightRange(unit).max} ${unit}.`
      : "Couldn't save. Try again in a moment.");
    $("weight-dialog").close();
    await loadWeights();
  } catch (err) {
    status.classList.add("is-error");
    setMsg("weight-form-status", err.message);
  } finally {
    save.disabled = false;
  }
}

// ---------- Calories vs goal ----------

async function loadCalories() {
  const section = $("cal-chart").closest("section");
  setMsg("cal-status", "");
  try {
    const t = today();
    days = await getJson(`/api/meals/daily-totals?from=${addDays(t, -(CALORIE_DAYS - 1))}&to=${t}`,
      "Couldn't load your calories. Check your connection and reload.");
    await settingsReady;
    renderCalories();
  } catch (err) {
    setMsg("cal-status", err.message);
  } finally {
    busy(section, false);
  }
}

function renderCalories() {
  if (!days) return;
  const svg = $("cal-chart");
  const W = 320, H = 170, CHART = 130, TOP = 14; // labels sit below CHART + TOP
  const { bars, goalY } = barHeights(days.map((d) => d.total_calories), goal, CHART);
  const slot = W / days.length, barW = Math.min(28, slot * 0.6);
  svg.replaceChildren();
  svg.setAttribute("aria-label", caloriesLabel(days, goal));
  svg.append(svgEl("line", { class: "axis", x1: 0, x2: W, y1: TOP + CHART, y2: TOP + CHART }));
  days.forEach((d, i) => {
    const x = i * slot + (slot - barW) / 2;
    const h = bars[i];
    svg.append(svgEl("rect", {
      class: d.total_calories > goal ? "bar is-over" : "bar",
      x, y: TOP + CHART - h, width: barW, height: h, rx: 3,
    }));
    const tick = svgEl("text", { class: "tick", x: i * slot + slot / 2, y: H - 6, "text-anchor": "middle" });
    tick.textContent = parseDate(d.date).toLocaleDateString("en-IN", { weekday: "narrow" });
    svg.append(tick);
  });
  svg.append(svgEl("line", { class: "goal", x1: 0, x2: W, y1: TOP + goalY, y2: TOP + goalY }));
  const label = svgEl("text", { class: "goal-label", x: W, y: TOP + goalY - 4, "text-anchor": "end" });
  label.textContent = `Goal ${kcal(goal)}`;
  svg.append(label);
  svg.hidden = false;
}

// ---------- Start ----------

async function loadSettingsForPage() {
  try {
    const s = await loadSettings();
    unit = s.weight_unit === "lb" ? "lb" : "kg";
    goal = s.goal_kcal || DEFAULT_GOAL;
  } catch (err) {
    // Charts still draw, in kg against the default goal; say so where it matters.
    setMsg("weight-status", `${err.message} Showing kg.`);
    setMsg("cal-status", `${err.message} Showing a ${kcal(DEFAULT_GOAL)} kcal goal.`);
  }
}

function wire() {
  $("weight-log").addEventListener("click", openWeightDialog);
  $("weight-form").addEventListener("submit", saveWeight);
  $("weight-cancel").addEventListener("click", () => $("weight-dialog").close());
  // Clear a field's message as soon as it's fixed.
  $("w-value").addEventListener("input", (e) => { if (!weightError(e.target.value, unit)) fieldError(e.target, ""); });
  $("w-date").addEventListener("input", (e) => { if (!dateError(e.target.value, today())) fieldError(e.target, ""); });

  $("photo-dialog-close").addEventListener("click", () => $("photo-dialog").close());
  $("photo-dialog").addEventListener("close", () => { viewing = null; $("photo-dialog-img").removeAttribute("src"); });
  $("photo-dialog-img").addEventListener("error", (e) => {
    if (!e.target.getAttribute("src")) return;
    e.target.hidden = true;
    setMsg("photo-dialog-status", "Couldn't load this photo. Close it and reload the page to try again.");
  });
  $("photo-delete").addEventListener("click", deleteViewedPhoto);

  $("compare-open").addEventListener("click", openCompare);
  $("compare-close").addEventListener("click", () => $("compare").close());
  $("compare-a").addEventListener("change", renderCompare);
  $("compare-b").addEventListener("change", renderCompare);
  document.querySelectorAll('input[name="compare-pose"]').forEach((r) => r.addEventListener("change", renderCompare));

  // Unit changed in Settings: redraw from what is already loaded.
  document.addEventListener("settingschange", (e) => {
    unit = e.detail.weight_unit === "lb" ? "lb" : "kg";
    goal = e.detail.goal_kcal || DEFAULT_GOAL;
    renderWeights();
    renderCalories();
    renderTimeline();
  });
}

// Nothing loads until we know who is using the app: logged in, with a role chosen.
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
    setMsg("page-status", err.message || "Couldn't load your account. Try again.");
    for (const s of document.querySelectorAll("main section")) busy(s, false);
    return;
  }
  settingsReady = loadSettingsForPage();
  // Each section loads on its own: one failing never blocks the others.
  loadCheckins();
  loadWeights();
  loadCalories();
}

if (typeof module !== "undefined") {
  module.exports = { checkinText, weightSummary, weightLabel, caloriesLabel, weightError, dateError, photoFor, missingPhotoText,
    photoViewTitle, DELETE_PHOTO_CONFIRM, photoDeleteError };
} else {
  initNav("progress");
  wire();
  start();
}
