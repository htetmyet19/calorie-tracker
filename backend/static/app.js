const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
const svgEl = (tag, attrs = {}) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};

const MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"];
const MEAL_LABEL = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner", snack: "Snack" };
const CONFIDENCE_LABEL = { high: "confident", medium: "likely", low: "rough guess" };
const MACROS = [["protein_g", "P"], ["carbs_g", "C"], ["fat_g", "F"]];

let items = [];          // food items for the meal being reviewed
let selectedFile = null;
let justSavedId = null;  // the segment to draw in after a save

const pad = (n) => String(n).padStart(2, "0");
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const localDateTime = (d) => `${isoDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const parseDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
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

$("goal").addEventListener("change", () => {
  const goal = Math.min(9000, Math.max(500, parseFloat($("goal").value) || 2000));
  $("goal").value = goal;
  localStorage.setItem("goal", goal);
  loadDay();
});

// ---------- Goal calculator ----------

const CALC_FIELDS = { heightCm: "c-height", weightKg: "c-weight", age: "c-age" };

function readProfile() {
  const p = {
    sex: document.querySelector('input[name="c-sex"]:checked').value,
    goal: document.querySelector('input[name="c-goal"]:checked').value,
    activity: parseFloat($("c-activity").value),
  };
  for (const [key, id] of Object.entries(CALC_FIELDS)) {
    if (!$(id).checkValidity() || $(id).value === "") return null;
    p[key] = parseFloat($(id).value);
  }
  return p;
}

function renderCalc() {
  const p = readProfile();
  $("calc-result").hidden = !p;
  $("calc-use").disabled = !p;
  $("r-floor").hidden = true;
  if (!p) return;
  const b = bmi(p.weightKg, p.heightCm);
  const suggestion = suggestedGoal(p);
  $("r-bmi").textContent = b.toFixed(1);
  $("r-bmi-cat").textContent = bmiCategory(b);
  $("r-tdee").textContent = fmt(tdee(p));
  $("r-goal").textContent = fmt(suggestion.kcal);
  $("r-floor").hidden = !suggestion.floored;
  try { localStorage.setItem("profile", JSON.stringify(p)); } catch {}
}

function restoreProfile() {
  let p;
  try { p = JSON.parse(localStorage.getItem("profile")); } catch {}
  if (!p) return;
  for (const [key, id] of Object.entries(CALC_FIELDS)) $(id).value = p[key];
  $("c-activity").value = String(p.activity);
  for (const name of ["sex", "goal"]) {
    const radio = document.querySelector(`input[name="c-${name}"][value="${p[name]}"]`);
    if (radio) radio.checked = true;
  }
}

$("calc-open").addEventListener("click", () => {
  restoreProfile();
  renderCalc();
  $("calc").returnValue = ""; // Escape keeps the previous value, which may be "use"
  $("calc").showModal();
});
$("calc-form").addEventListener("input", renderCalc);
$("calc").addEventListener("close", () => {
  const p = $("calc").returnValue === "use" && readProfile();
  if (!p) return;
  $("goal").value = suggestedGoal(p).kcal;
  $("goal").dispatchEvent(new Event("change")); // same clamp, save and redraw as a typed goal
});

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

function renderMeals(day) {
  $("meals-empty").hidden = day.meals.length > 0;
  $("meals").replaceChildren(...day.meals.map((m) => {
    const sw = el("span", { className: "swatch" });
    sw.style.setProperty("--c", `var(--${m.meal_type})`);
    const time = m.eaten_at.slice(11, 16);
    const del = el("button", { className: "icon-btn", ariaLabel: `Delete ${MEAL_LABEL[m.meal_type].toLowerCase()} at ${time}` });
    del.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${MEAL_LABEL[m.meal_type].toLowerCase()} at ${time}?`)) return;
      await fetch(`/api/meals/${m.id}`, { method: "DELETE" });
      loadDay();
    });
    return el("li", {},
      sw,
      el("div", {},
        el("p", { className: "when" }, MEAL_LABEL[m.meal_type], el("time", { dateTime: m.eaten_at, textContent: time })),
        el("p", { className: "what", textContent: m.items.map((i) => `${i.name} (${Math.round(i.grams)} g)`).join(", ") })),
      el("span", { className: "kcal", textContent: `${fmt(m.total_calories)} kcal` }),
      del);
  }));
}

async function loadDay() {
  const date = currentDate();
  const res = await fetch(`/api/meals?date=${date}`);
  if (!res.ok) return;
  const day = await res.json();
  if (date !== currentDate()) return; // user moved on to another day meanwhile
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
  const form = new FormData();
  form.append("photo", selectedFile);
  try {
    const res = await fetch("/api/analyze", { method: "POST", body: form });
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
  try {
    const res = await fetch("/api/meals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eaten_at, meal_type, items: items.map((i) => ({ ...i, confidence: i.confidence || "high" })) }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Couldn't save the meal. Check the numbers and try again.");
    justSavedId = data.id;
    resetLogger();
    setStatus(`Saved ${MEAL_LABEL[meal_type].toLowerCase()}, ${fmt(data.total_calories)} kcal.`);
    loadDay();
  } catch (err) {
    setStatus(err.message, true);
    $("save").disabled = false;
  }
});

// ---------- Start ----------

$("goal").value = localStorage.getItem("goal") || 2000;
setDate(isoDate(new Date()));
