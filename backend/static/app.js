// Today page. Needs dom.js, auth.js, energy.js, units.js, images.js and nav.js loaded first.

const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"];
const MEAL_LABEL = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner", snack: "Snack" };
const CONFIDENCE_LABEL = { high: "confident", medium: "likely", low: "rough guess" };
const MACROS = [["protein_g", "P"], ["carbs_g", "C"], ["fat_g", "F"]];

let items = [];          // food items for the meal being reviewed
let selectedFile = null;
let justSavedId = null;  // the segment to draw in after a save
let loadError = null;    // the message loadDay last showed, if any
const DEFAULT_GOAL = 2000;
let savedGoal = DEFAULT_GOAL; // the goal the server last confirmed

const localDateTime = (d) => `${isoDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const fmt = (n) => Math.round(n).toLocaleString("en-IN");
const round1 = (x) => Math.round(x * 10) / 10;

function dayLabel(dateStr) {
  const today = isoDate(new Date());
  const y = new Date(); y.setDate(y.getDate() - 1);
  if (dateStr === today) return "Today";
  if (dateStr === isoDate(y)) return "Yesterday";
  return parseDate(dateStr).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

function setStatus(msg, isError = false) {
  $("status").textContent = msg;
  $("status").classList.toggle("is-error", isError);
}

function guessMealType() {
  const h = new Date().getHours();
  if (h >= 5 && h < 11) return "breakfast";
  if (h >= 11 && h < 16) return "lunch";
  if (h >= 18 && h < 23) return "dinner";
  return "snack";
}

// ---------- Day navigation ----------

function currentDate() { return $("log-date").value; }

function setDate(dateStr) {
  $("log-date").value = dateStr;
  $("day-name").textContent = dayLabel(dateStr);
  $("next-day").disabled = dateStr >= isoDate(new Date());
  $("save").textContent = dateStr === isoDate(new Date()) ? "Save to today" : `Save to ${dayLabel(dateStr)}`;
  loadDay();
}

function shiftDay(delta) {
  const d = parseDate(currentDate());
  d.setDate(d.getDate() + delta);
  setDate(isoDate(d));
}

$("prev-day").addEventListener("click", () => shiftDay(-1));
$("next-day").addEventListener("click", () => shiftDay(1));
$("day-name").addEventListener("click", () => {
  const input = $("log-date");
  input.max = isoDate(new Date());
  if (input.showPicker) input.showPicker(); else input.click();
});
$("log-date").addEventListener("change", (e) => e.target.value && setDate(e.target.value));

// Saves the goal (plus any calculator details) to the server; on failure the
// field goes back to the saved goal.
async function saveGoal(goal, extra = {}) {
  $("goal").value = goal;
  loadDay();
  try {
    await saveSettings({ ...extra, goal_kcal: goal });
  } catch (err) {
    setStatus(err.message, true);
    $("goal").value = savedGoal;
    loadDay();
    return;
  }
  savedGoal = goal;
}

$("goal").addEventListener("change", () => {
  const goal = Math.round(Math.min(9000, Math.max(500, parseFloat($("goal").value) || DEFAULT_GOAL)));
  saveGoal(goal);
});

// ---------- Goal calculator ----------

// The calculator shows weight in the unit chosen in Settings; the server keeps kg.
let calcUnit = "kg";

function setCalcUnit(unit) {
  if (unit === calcUnit) return;
  const input = $("c-weight");
  const old = parseFloat(input.value);
  if (!Number.isNaN(old)) input.value = inputWeight(toKg(old, calcUnit), unit);
  calcUnit = unit;
  const range = weightRange(unit);
  input.min = range.min;
  input.max = range.max;
  $("c-weight-unit").textContent = unit;
  renderCalc();
}

// Calculator values in the settings' field names, or null while incomplete.
function readProfile() {
  for (const id of ["c-height", "c-weight", "c-age"]) {
    if (!$(id).checkValidity() || $(id).value === "") return null;
  }
  return {
    height_cm: parseFloat($("c-height").value),
    weight_kg: toKg(parseFloat($("c-weight").value), calcUnit), // weightRange keeps it in 30-300 kg
    age: parseInt($("c-age").value, 10),
    sex: document.querySelector('input[name="c-sex"]:checked').value,
    activity: parseFloat($("c-activity").value),
    weight_goal: document.querySelector('input[name="c-goal"]:checked').value,
  };
}

// energy.js takes the calculator's own field names.
const energyProfile = (s) => ({
  heightCm: s.height_cm, weightKg: s.weight_kg, age: s.age, sex: s.sex,
  activity: s.activity, goal: s.weight_goal,
});

function renderCalc() {
  const p = readProfile();
  $("calc-result").hidden = !p;
  $("calc-use").disabled = !p;
  $("r-floor").hidden = true;
  if (!p) return;
  const e = energyProfile(p);
  const b = bmi(e.weightKg, e.heightCm);
  const suggestion = suggestedGoal(e);
  $("r-bmi").textContent = b.toFixed(1);
  $("r-bmi-cat").textContent = bmiCategory(b);
  $("r-tdee").textContent = fmt(tdee(e));
  $("r-goal").textContent = fmt(suggestion.kcal);
  $("r-floor").hidden = !suggestion.floored;
}

function restoreProfile(s) {
  setCalcUnit(s.weight_unit || "kg");
  if (s.height_cm != null) $("c-height").value = s.height_cm;
  if (s.weight_kg != null) $("c-weight").value = inputWeight(s.weight_kg, calcUnit);
  if (s.age != null) $("c-age").value = s.age;
  if (s.activity != null) $("c-activity").value = String(s.activity);
  for (const [name, value] of [["sex", s.sex], ["goal", s.weight_goal]]) {
    const radio = value && document.querySelector(`input[name="c-${name}"][value="${value}"]`);
    if (radio) radio.checked = true;
  }
}

$("calc-open").addEventListener("click", async () => {
  let s;
  try {
    s = await loadSettings();
  } catch (err) {
    setStatus(err.message, true);
    return;
  }
  restoreProfile(s);
  renderCalc();
  $("calc").returnValue = ""; // Escape keeps the previous value, which may be "use"
  $("calc").showModal();
});
$("calc-form").addEventListener("input", renderCalc);
$("calc").addEventListener("close", () => {
  const p = $("calc").returnValue === "use" && readProfile();
  if (!p) return;
  saveGoal(suggestedGoal(energyProfile(p)).kcal, p); // one save: details and goal together
});

document.addEventListener("settingschange", (e) => setCalcUnit(e.detail.weight_unit));

// ---------- The plate ----------

const R = 103;               // ring radius in viewBox units (viewBox is 240)
const STROKE = 20;
const GAP = 2.5;             // surface gap between segments
const CIRC = 2 * Math.PI * R;

function renderPlate(day) {
  const goal = parseFloat($("goal").value) || 2000;
  const total = day.total_calories;
  const scale = Math.max(goal, total); // past the goal the ring is full and segments share it
  const ring = $("ring");
  ring.replaceChildren();

  let start = 0;
  const segments = [];
  for (const meal of day.meals) {
    const len = (meal.total_calories / scale) * CIRC;
    if (len <= 0) continue;
    segments.push({ meal, start, len });
    start += len;
  }

  // Unfilled remainder of the rim.
  if (start < CIRC - GAP) {
    const from = segments.length ? start : 0;
    const len = CIRC - from - (segments.length ? GAP : 0);
    ring.append(svgEl("circle", {
      class: "track", cx: 120, cy: 120, r: R, "stroke-width": STROKE,
      "stroke-dasharray": `${len} ${CIRC}`, "stroke-dashoffset": -from,
    }));
  }

  for (const { meal, start: s, len } of segments) {
    const visible = Math.max(len - GAP, 0.5);
    const seg = svgEl("circle", {
      class: `seg seg-${meal.meal_type}`, cx: 120, cy: 120, r: R, "stroke-width": STROKE,
      "stroke-dasharray": `${visible} ${CIRC}`, "stroke-dashoffset": -s,
    });
    // A wider invisible stroke makes thin segments easy to hover.
    const hit = svgEl("circle", {
      class: "hit", cx: 120, cy: 120, r: R, "stroke-width": STROKE + 16,
      "stroke-dasharray": `${visible} ${CIRC}`, "stroke-dashoffset": -s,
    });
    const tip = `${MEAL_LABEL[meal.meal_type]} at ${meal.eaten_at.slice(11, 16)}: ${fmt(meal.total_calories)} kcal`;
    hit.addEventListener("pointermove", (e) => showTooltip(e, tip));
    hit.addEventListener("pointerleave", hideTooltip);
    ring.append(seg, hit);

    if (meal.id === justSavedId) {
      seg.setAttribute("stroke-dasharray", `0 ${CIRC}`);
      requestAnimationFrame(() => requestAnimationFrame(() =>
        seg.setAttribute("stroke-dasharray", `${visible} ${CIRC}`)));
    }
  }
  justSavedId = null;

  $("day-total").textContent = fmt(total);
  const remaining = $("remaining");
  remaining.classList.toggle("is-over", total > goal);
  if (total > goal) {
    remaining.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1l7 13H1zM7.2 6v4h1.6V6zm0 5.2v1.6h1.6v-1.6z"/></svg>';
    remaining.append(`${fmt(total - goal)} kcal over goal`);
  } else {
    remaining.textContent = total === 0 ? "" : `${fmt(goal - total)} kcal left`;
  }
  $("plate-summary").textContent =
    `${fmt(total)} of ${fmt(goal)} kcal eaten on ${dayLabel(day.date)} across ${day.meals.length} meals.`;
}

function showTooltip(e, text) {
  const tip = $("tooltip");
  const box = $("plate").getBoundingClientRect();
  tip.textContent = text;
  tip.style.left = `${e.clientX - box.left}px`;
  tip.style.top = `${e.clientY - box.top}px`;
  tip.hidden = false;
}
function hideTooltip() { $("tooltip").hidden = true; }

function renderLegend(day) {
  const byType = Object.fromEntries(MEAL_TYPES.map((t) => [t, 0]));
  for (const m of day.meals) byType[m.meal_type] += m.total_calories;
  const present = MEAL_TYPES.filter((t) => byType[t] > 0);
  $("legend").replaceChildren(...present.map((t) => {
    const sw = el("span", { className: "swatch" });
    sw.style.setProperty("--c", `var(--${t})`);
    return el("li", {}, sw, MEAL_LABEL[t], el("span", { className: "kcal", textContent: fmt(byType[t]) }));
  }));
}

// ---------- Meal photos ----------

const ANALYSIS_SIDE = 1600, ANALYSIS_QUALITY = 0.85; // sent to /api/analyze only
const STORED_SIDE = 800, STORED_QUALITY = 0.7;       // kept with the meal
const MAX_STORED_BYTES = 300 * 1024;                 // the server's meal-photo limit

const failedUploads = new Map(); // mealId -> Blob whose upload failed; memory only
const uploadingIds = new Set();  // meals whose photo is uploading now
const photoBlobs = new Map();    // mealId -> Blob already here (uploaded or fetched)
const photoFetches = new Map();  // mealId -> in-flight Promise<Blob|null>
let thumbUrls = [];              // object URLs of the rendered rows
let thumbObserver = null;

// The ~800 px copy kept with the meal, under the server's 300 KB limit.
// null when this browser can't decode the photo.
async function storedCopy(file) {
  try {
    let blob = await resizeImage(file, STORED_SIDE, STORED_QUALITY);
    if (blob.size > MAX_STORED_BYTES) blob = await resizeImage(file, STORED_SIDE, 0.5);
    if (blob.size > MAX_STORED_BYTES) blob = await resizeImage(file, 600, 0.5);
    return blob.size <= MAX_STORED_BYTES ? blob : null;
  } catch (e) {
    return null;
  }
}

// PUT the photo; on any failure keep the blob so the row can offer a retry.
async function uploadMealPhoto(id, blob) {
  const form = new FormData();
  form.append("photo", blob, "meal.jpg");
  let res = null;
  try {
    res = await api(`/api/meals/${id}/photo`, { method: "PUT", body: form });
  } catch (e) { /* offline: res stays null */ }
  if (res && res.ok) {
    failedUploads.delete(id);
    photoBlobs.set(id, blob); // no need to download what we just sent
    return true;
  }
  if (res && res.status === 404) failedUploads.delete(id); // the meal is gone
  else failedUploads.set(id, blob);
  return false;
}

// The meal's photo as a Blob, downloaded once per page. null when there is none.
function mealPhoto(id) {
  if (photoBlobs.has(id)) return Promise.resolve(photoBlobs.get(id));
  if (!photoFetches.has(id)) {
    // api() sends the token; fetch follows the 307 to the short-lived signed URL.
    const p = api(`/api/meals/${id}/photo`)
      .then((res) => (res.ok ? res.blob() : null))
      .catch(() => null)
      .then((blob) => {
        photoFetches.delete(id);
        if (blob) photoBlobs.set(id, blob);
        return blob;
      });
    photoFetches.set(id, p);
  }
  return photoFetches.get(id);
}

function resetThumbs() {
  if (thumbObserver) thumbObserver.disconnect();
  for (const url of thumbUrls) URL.revokeObjectURL(url);
  thumbUrls = [];
  thumbObserver = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        thumbObserver.unobserve(entry.target);
        showThumb(entry.target);
      }
    }, { rootMargin: "100px" })
    : null;
}

// Thumbnails are fetched only when their row scrolls into view: mobile data is dear.
async function showThumb(button) {
  const id = Number(button.dataset.mealId);
  const blob = await mealPhoto(id);
  if (!button.isConnected) return; // the day re-rendered meanwhile
  if (!blob) { // gone since the list loaded (e.g. the 90-day cleanup)
    button.closest("li").classList.remove("has-thumb");
    button.remove();
    return;
  }
  const url = URL.createObjectURL(blob);
  thumbUrls.push(url);
  button.querySelector("img").src = url;
}

function mealThumb(m, time) {
  if (!m.has_photo) return null;
  const label = MEAL_LABEL[m.meal_type];
  const img = el("img", { alt: `Photo of ${label.toLowerCase()}`, loading: "lazy", width: 40, height: 40 });
  const button = el("button", { className: "thumb", type: "button" }, img);
  button.dataset.mealId = m.id;
  button.addEventListener("click", () => openPhoto(m.id, `${label} at ${time}`));
  if (thumbObserver) thumbObserver.observe(button); else showThumb(button);
  return button;
}

async function openPhoto(id, title) {
  const blob = await mealPhoto(id);
  if (!blob) { setStatus("Couldn't load the photo. Check your connection.", true); return; }
  const img = $("photo-view-img");
  if (img.src) URL.revokeObjectURL(img.src);
  img.src = URL.createObjectURL(blob);
  img.alt = `Photo of ${title.toLowerCase()}`;
  $("photo-view-title").textContent = title;
  $("photo-view").showModal();
}
$("photo-view-close").addEventListener("click", () => $("photo-view").close());

// Under the meal's text: uploading, upload failed (retry), or removed after 90 days.
function photoNote(m) {
  if (m.has_photo) return null;
  if (uploadingIds.has(m.id)) return el("p", { className: "photo-note", textContent: "Uploading photo…" });
  if (failedUploads.has(m.id)) {
    const retry = el("button", { className: "btn btn-quiet photo-retry", type: "button",
      textContent: "Photo not uploaded – retry" });
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      retry.textContent = "Uploading photo…";
      await uploadMealPhoto(m.id, failedUploads.get(m.id));
      loadDay();
    });
    return retry;
  }
  if (m.photo_removed) { // set by the daily job when it removes a photo after 90 days
    return el("p", { className: "photo-note", textContent: "Photo removed after 90 days" });
  }
  return null;
}

function renderMeals(day) {
  resetThumbs();
  $("meals-empty").hidden = day.meals.length > 0;
  $("meals").replaceChildren(...day.meals.map((m) => {
    const sw = el("span", { className: "swatch" });
    sw.style.setProperty("--c", `var(--${m.meal_type})`);
    const time = m.eaten_at.slice(11, 16);
    const del = el("button", { className: "icon-btn", ariaLabel: `Delete ${MEAL_LABEL[m.meal_type].toLowerCase()} at ${time}` });
    del.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${MEAL_LABEL[m.meal_type].toLowerCase()} at ${time}?`)) return;
      let res = null;
      try {
        res = await api(`/api/meals/${m.id}`, { method: "DELETE" });
      } catch (err) { /* network down: res stays null */ }
      // 404: already gone (another tab or device), so treat it like a delete.
      if (!res || (!res.ok && res.status !== 404)) {
        setStatus("Couldn't delete the meal. Check your connection and try again.", true);
        return; // the meal and any photo kept for a retry stay as they are
      }
      failedUploads.delete(m.id);
      photoBlobs.delete(m.id);
      loadDay();
    });
    const text = el("div", {},
      el("p", { className: "when" }, MEAL_LABEL[m.meal_type], el("time", { dateTime: m.eaten_at, textContent: time })),
      el("p", { className: "what", textContent: m.items.map((i) => `${i.name} (${Math.round(i.grams)} g)`).join(", ") }));
    const note = photoNote(m);
    if (note) text.append(note);
    const thumb = mealThumb(m, time);
    const li = el("li", {}, sw, ...(thumb ? [thumb] : []), text,
      el("span", { className: "kcal", textContent: `${fmt(m.total_calories)} kcal` }),
      del);
    li.classList.toggle("has-thumb", !!thumb);
    return li;
  }));
}

async function loadDay() {
  const date = currentDate();
  const fallback = "Couldn't load your meals. Check your connection.";
  let day;
  try {
    const res = await api(`/api/meals?date=${date}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : fallback);
    day = data;
  } catch (err) {
    if (date !== currentDate()) return;
    // fetch rejects with a TypeError ("Failed to fetch") when the network is down.
    loadError = err instanceof TypeError ? fallback : err.message || fallback;
    setStatus(loadError, true);
    return;
  }
  if (date !== currentDate()) return; // user moved on to another day meanwhile
  // Clear our own earlier error, but not a message someone else has shown since.
  if (loadError && $("status").textContent === loadError) setStatus("");
  loadError = null;
  renderPlate(day);
  renderLegend(day);
  renderMeals(day);
  $("m-protein").textContent = fmt(day.protein_g);
  $("m-carbs").textContent = fmt(day.carbs_g);
  $("m-fat").textContent = fmt(day.fat_g);
}

// ---------- Photo & estimate ----------

$("photo").addEventListener("change", (e) => {
  selectedFile = e.target.files[0] || null;
  $("analyze").disabled = !selectedFile;
  $("result").hidden = true;
  setStatus("");
  if (!selectedFile) return;
  $("preview").src = URL.createObjectURL(selectedFile);
  $("preview").hidden = false;
  $("drop-empty").hidden = true;
  $("drop").classList.add("has-photo");
});

$("analyze").addEventListener("click", async () => {
  if (!selectedFile) return;
  $("analyze").disabled = true;
  $("analyze").textContent = "Estimating…";
  $("drop").classList.add("is-busy");
  setStatus("");
  try {
    // A 1600 px copy is plenty for the estimate and far less mobile data than
    // the camera original. If this browser can't decode it, send the original.
    const copy = await resizeImage(selectedFile, ANALYSIS_SIDE, ANALYSIS_QUALITY).catch(() => null);
    const form = new FormData();
    if (copy) form.append("photo", copy, "meal.jpg"); else form.append("photo", selectedFile);
    const res = await api("/api/analyze", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `The estimate failed (${res.status}). Try again.`);
    if (!data.is_food) {
      setStatus("No food found in this photo. Try one with the plate clearly in frame.", true);
      return;
    }
    items = data.items;
    $("notes").textContent = data.notes ? `Assumed: ${data.notes}` : "";
    $("warnings").replaceChildren(...data.warnings.map((w) => el("li", { textContent: w })));
    selectMealType(guessMealType());
    renderItems();
    $("result").hidden = false;
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("analyze").disabled = false;
    $("analyze").textContent = "Estimate calories";
    $("drop").classList.remove("is-busy");
  }
});

// ---------- Reviewing items ----------

function numField(value, unit, className, onChange, label) {
  const input = el("input", { type: "number", min: 0, step: "any", value: round1(value), inputMode: "decimal", ariaLabel: label });
  input.addEventListener("change", () => onChange(Math.max(0, parseFloat(input.value) || 0)));
  return el("label", { className: `field ${className}` }, input, el("span", { className: "unit", textContent: unit }));
}

function renderItems() {
  $("items").replaceChildren(...items.map((item, idx) => {
    const name = el("input", { value: item.name, ariaLabel: "Food name" });
    name.addEventListener("change", () => { item.name = name.value.trim() || item.name; });

    // Changing grams rescales calories and macros, keeping the estimated energy density.
    const grams = numField(item.grams, "g", "field-num grams", (g) => {
      const ratio = item.grams > 0 ? g / item.grams : 0;
      item.grams = g;
      if (ratio) for (const k of ["calories", "protein_g", "carbs_g", "fat_g"]) item[k] *= ratio;
      renderItems();
    }, `${item.name} grams`);
    const kcal = numField(item.calories, "kcal", "field-num kcal-field", (v) => { item.calories = v; updateTotal(); }, `${item.name} calories`);
    const macros = el("div", { className: "macro-fields" },
      ...MACROS.map(([k, short]) => numField(item[k], short, "field-macro", (v) => { item[k] = v; }, `${item.name} ${k.replace("_g", "")} grams`)));

    const meta = el("span", { className: "meta" });
    if (item.portion) meta.append(item.portion);
    if (item.confidence) {
      if (item.portion) meta.append(", ");
      meta.append(el("span", { className: item.confidence === "low" ? "conf-low" : "", textContent: CONFIDENCE_LABEL[item.confidence] }));
    }

    const remove = el("button", { className: "icon-btn", ariaLabel: `Remove ${item.name}` });
    remove.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
    remove.addEventListener("click", () => { items.splice(idx, 1); renderItems(); });

    return el("li", {}, el("label", { className: "field name" }, name), grams, kcal, remove, meta, macros);
  }));
  updateTotal();
}

function updateTotal() {
  $("meal-total").textContent = fmt(items.reduce((s, i) => s + i.calories, 0));
  $("save").disabled = items.length === 0;
}

$("add-item").addEventListener("click", () => {
  items.push({ name: "", portion: "", grams: 100, calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, confidence: null });
  renderItems();
  $("items").lastElementChild.querySelector("input").focus();
});

function selectMealType(type) {
  $("meal-type").querySelector(`input[value="${type}"]`).checked = true;
}

$("meal-type").append(...MEAL_TYPES.map((t) => {
  const sw = el("span", { className: "swatch" });
  sw.style.setProperty("--c", `var(--${t})`);
  return el("label", {}, el("input", { type: "radio", name: "meal-type", value: t }), sw, MEAL_LABEL[t]);
}));

// ---------- Saving ----------

function resetLogger() {
  items = [];
  selectedFile = null;
  $("photo").value = "";
  $("preview").hidden = true;
  $("drop-empty").hidden = false;
  $("drop").classList.remove("has-photo");
  $("result").hidden = true;
  $("analyze").disabled = true;
}

$("save").addEventListener("click", async () => {
  const unnamed = items.find((i) => !i.name.trim());
  if (unnamed) { setStatus("Give every item a name before saving.", true); return; }
  $("save").disabled = true;
  const now = new Date();
  const date = currentDate();
  // Meals logged onto a past day get midday as their time.
  const eaten_at = date === isoDate(now) ? localDateTime(now) : `${date}T12:00`;
  const meal_type = $("meal-type").querySelector("input:checked").value;
  const photo = selectedFile; // resetLogger clears selectedFile
  let data;
  try {
    const res = await api("/api/meals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eaten_at, meal_type, items: items.map((i) => ({ ...i, confidence: i.confidence || "high" })) }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Couldn't save the meal. Check the numbers and try again.");
    justSavedId = data.id;
    resetLogger();
    setStatus(`Saved ${MEAL_LABEL[meal_type].toLowerCase()}, ${fmt(data.total_calories)} kcal.`);
  } catch (err) {
    setStatus(err.message, true);
    $("save").disabled = false;
    return;
  }
  // The meal is saved; the photo follows and never blocks it.
  if (photo) uploadingIds.add(data.id);
  loadDay();
  if (!photo) return;
  const stored = await storedCopy(photo);
  if (stored) await uploadMealPhoto(data.id, stored);
  else setStatus("Saved without the photo: this browser can't read it.");
  uploadingIds.delete(data.id);
  loadDay();
});

// ---------- Start ----------

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
    setStatus(err.message, true);
    return;
  }
  try {
    // Also moves old browser settings to the server, once.
    savedGoal = (await loadSettings()).goal_kcal || DEFAULT_GOAL;
  } catch (err) {
    setStatus(err.message, true); // the day still loads, against the default goal
  }
  $("goal").value = savedGoal;
  setDate(isoDate(new Date()));
}

initNav("today");
start();
