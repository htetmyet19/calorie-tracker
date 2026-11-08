// Workout page: build a weekly routine of exercise demos, play them, tick off days.
// Needs dom.js, auth.js and nav.js loaded first.
// The functions up to "Browser only" are pure so Node can test them (tests/workout.test.js).

const SAFETY_STOP = "Please check with a doctor or physiotherapist before starting a routine.";
const UNAVAILABLE = "This video is no longer available";
const REPLACE_CONFIRM = "This replaces your current routine.";
const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;
const DEFAULT_INPUTS = { days_per_week: 3, level: "beginner", equipment: "none", session_min: 30 };
const INPUT_NAMES = ["days_per_week", "level", "equipment", "session_min"];

function itemText(item) {
  if (item.warm_up) return "Warm-up · 5 min";
  const amount = item.reps != null ? `${item.reps}` : `${item.seconds} s`;
  return `${item.sets} × ${amount} · rest ${item.rest_sec} s`;
}

function weekText(done, dayCount) {
  const n = new Set(done.map((d) => d.day_index)).size;
  return `This week: ${n} of ${dayCount} done`;
}

// The date a day was last ticked this week (done holds only this week's ticks), or null.
function doneDate(done, dayIndex) {
  const dates = done.filter((d) => d.day_index === dayIndex).map((d) => d.done_on).sort();
  return dates.length ? dates[dates.length - 1] : null;
}

function doneLabel(date, today) {
  if (date === today) return "✓ Done today";
  return `✓ Done ${parseDate(date).toLocaleDateString("en-IN", { weekday: "short" })}`;
}

function embedUrl(youtubeId) {
  if (typeof youtubeId !== "string" || !YOUTUBE_ID.test(youtubeId)) return null;
  return `https://www.youtube-nocookie.com/embed/${youtubeId}?rel=0`;
}

function builderDefaults(routine) {
  if (!routine) return { ...DEFAULT_INPUTS };
  return Object.fromEntries(INPUT_NAMES.map((k) => [k, routine[k]]));
}


// ---------- Browser only below ----------

const BUILD_ERROR = "Couldn't build your routine. Check your connection and try again.";
const LOAD_ERROR = "Couldn't load your routine. Check your connection and reload.";
const TICK_ERROR = "Couldn't save that. Check your connection and try again.";

let routine = null;   // the active routine, or null
let done = [];        // this week's ticks
let building = false;

const today = () => isoDate(new Date());

function setMsg(id, msg) {
  $(id).textContent = msg;
}

async function errorText(res, fallback) {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === "string" && res.status < 500 ? body.detail : fallback;
}

// ---------- Loading and showing ----------

async function loadRoutine() {
  setMsg("routine-status", "");
  let res;
  try {
    res = await api(`/api/routines/active?today=${today()}`);
  } catch (e) {
    throw new Error(LOAD_ERROR);
  }
  if (!res.ok) throw new Error(await errorText(res, LOAD_ERROR));
  const data = await res.json();
  routine = data.routine;
  done = data.done;
  render();
}

function render() {
  $("intro").setAttribute("aria-busy", "false");
  $("intro").hidden = !!routine || !$("builder").hidden;
  $("intro-build").hidden = false;
  $("routine").hidden = !routine || !$("builder").hidden;
  const list = $("days");
  list.replaceChildren();
  if (!routine || !$("builder").hidden) return;
  setMsg("week-done", weekText(done, routine.days.length));
  $("routine-note").hidden = !routine.note;
  setMsg("routine-note", routine.note || "");
  for (const day of routine.days) list.append(dayCard(day));
}

function dayCard(day) {
  const doneOn = doneDate(done, day.index);
  const isDone = doneOn !== null;
  const head = el("div", { className: "card-head" },
    el("h3", { className: "day-title" }, `Day ${day.index + 1} · ${day.title}`),
    el("span", { className: "day-est" }, `~${day.est_min} min`));
  const items = el("ol", { className: "exercises" }, ...day.items.map(exerciseRow));
  const tick = el("button", { type: "button", className: isDone ? "btn btn-outline day-done is-done" : "btn btn-primary day-done",
    ariaPressed: String(isDone) }, isDone ? doneLabel(doneOn, today()) : `Mark Day ${day.index + 1} done`);
  // Tapping a done day removes that tick, whichever day this week it was made.
  tick.addEventListener("click", () => toggleDone(day.index, isDone ? doneOn : today(), !isDone, tick));
  return el("li", { className: "card workout-day" }, head, el("p", { className: "day-why" }, day.why), items, tick);
}

function exerciseRow(item) {
  const text = el("span", { className: "exercise-text" },
    el("span", { className: "exercise-title" }, item.title),
    el("span", { className: "exercise-dose" }, itemText(item)));
  if (!item.available || !embedUrl(item.youtube_id)) {
    return el("li", { className: "exercise is-unavailable" },
      el("span", { className: "play is-off", ariaHidden: "true" }, "–"), text,
      el("span", { className: "exercise-gone" }, UNAVAILABLE));
  }
  const play = el("button", { type: "button", className: "exercise-play", ariaLabel: `Play ${item.title} demo` },
    el("span", { className: "play", ariaHidden: "true" }, "▶"), text);
  play.addEventListener("click", () => openVideo(item));
  return el("li", { className: "exercise" }, play);
}

// ---------- Video ----------

function openVideo(item) {
  const src = embedUrl(item.youtube_id);
  if (!src) return;
  setMsg("video-title", item.title);
  setMsg("video-credit", item.channel ? `Video: ${item.channel} on YouTube` : "");
  const frame = el("iframe", { src, title: `${item.title} demo`, loading: "lazy",
    referrerPolicy: "strict-origin-when-cross-origin" });
  frame.setAttribute("allow", "encrypted-media; picture-in-picture");
  frame.setAttribute("allowfullscreen", "");
  $("video-frame").replaceChildren(frame);
  $("video-dialog").showModal();
}

// ---------- Ticks ----------

async function toggleDone(dayIndex, date, on, btn) {
  btn.disabled = true;
  setMsg("routine-status", "");
  try {
    let res;
    try {
      res = await api(`/api/routines/${routine.id}/days/${dayIndex}/done/${date}`, { method: on ? "PUT" : "DELETE" });
    } catch (e) {
      throw new Error(TICK_ERROR);
    }
    if (!res.ok) throw new Error(await errorText(res, TICK_ERROR));
    await loadRoutine();
  } catch (err) {
    setMsg("routine-status", err.message);
    btn.disabled = false;
  }
}

// ---------- Builder ----------

function openBuilder() {
  if (routine && !confirm(REPLACE_CONFIRM)) return;
  for (const r of document.querySelectorAll('input[name="safety"]')) r.checked = false;
  setMsg("safety-stop", "");
  setMsg("builder-status", "");
  $("builder-form").hidden = true;
  const defaults = builderDefaults(routine);
  for (const name of INPUT_NAMES) {
    const input = document.querySelector(`input[name="${name}"][value="${defaults[name]}"]`);
    if (input) input.checked = true;
  }
  $("builder").hidden = false;
  render();
  $("builder-title").focus();
}

function closeBuilder() {
  $("builder").hidden = true;
  render();
}

function safetyChanged(value) {
  // "Yes" stops here: nothing is sent and the answer is never stored.
  setMsg("safety-stop", value === "yes" ? SAFETY_STOP : "");
  $("builder-form").hidden = value !== "no";
}

async function build(e) {
  e.preventDefault();
  if (building) return;
  const body = {};
  for (const name of INPUT_NAMES) {
    const checked = document.querySelector(`input[name="${name}"]:checked`);
    body[name] = name === "level" || name === "equipment" ? checked.value : Number(checked.value);
  }
  building = true;
  const submit = $("builder-submit");
  submit.disabled = true;
  $("builder-status").classList.remove("is-error");
  setMsg("builder-status", "Building your routine…");
  try {
    let res;
    try {
      res = await api("/api/routines", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (err) {
      throw new Error(BUILD_ERROR);
    }
    if (!res.ok) throw new Error(await errorText(res, BUILD_ERROR));
    $("builder").hidden = true;
    await loadRoutine();
    window.scrollTo(0, 0);
  } catch (err) {
    $("builder-status").classList.add("is-error");
    setMsg("builder-status", err.message);
  } finally {
    building = false;
    submit.disabled = false;
  }
}

// ---------- Start ----------

function wire() {
  $("intro-build").addEventListener("click", openBuilder);
  $("routine-new").addEventListener("click", openBuilder);
  $("builder-cancel").addEventListener("click", closeBuilder);
  $("builder-form").addEventListener("submit", build);
  document.querySelectorAll('input[name="safety"]').forEach((r) =>
    r.addEventListener("change", () => safetyChanged(r.value)));
  $("video-close").addEventListener("click", () => $("video-dialog").close());
  // Closing removes the player, so nothing keeps playing or loading from YouTube.
  $("video-dialog").addEventListener("close", () => $("video-frame").replaceChildren());
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
    if (!me.ok) throw new Error(await errorText(me, "Couldn't load your account. Try again."));
    await loadRoutine();
  } catch (err) {
    setMsg("page-status", err.message || LOAD_ERROR);
    $("intro").setAttribute("aria-busy", "false");
  }
}

if (typeof module !== "undefined") {
  module.exports = { itemText, weekText, doneDate, doneLabel, embedUrl, builderDefaults, SAFETY_STOP, UNAVAILABLE, REPLACE_CONFIRM };
} else {
  initNav("workout");
  wire();
  start();
}
