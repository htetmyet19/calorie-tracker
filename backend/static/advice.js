// Meal advice card on the result screen: a short suggestion, asked for as soon as the
// photo is analysed. Needs dom.js and auth.js loaded first; app.js calls initAdviceCard(),
// requestAdvice(), mealChanged() and resetAdvice().
// The functions up to "Browser only" are pure so Node can test them (tests/advice.test.js).

const ADVICE_NOTE = "Estimates are approximate. If food or eating feels stressful, talk to a doctor or someone you trust.";
const ADVICE_ERROR = "Couldn't get a suggestion. You can still save the meal.";
const ADVICE_STALE = "You changed the meal, so this suggestion is out of date.";
const ADVICE_LOADING = "Thinking…";

// Only what the server reads. Items added by hand may have no name yet.
function adviceBody(items, today) {
  return {
    items: items.map((i) => ({
      name: (i.name || "").trim() || "Food item",
      calories: i.calories, protein_g: i.protein_g, carbs_g: i.carbs_g, fat_g: i.fat_g,
    })),
    date: today,
  };
}

// seq grows with every request, edit and reset, so a late answer for an older meal is ignored.
const INITIAL = Object.freeze({ status: "idle", text: "", seq: 0 });

function nextCardState(state, event) {
  switch (event.type) {
    case "request":
      return { status: "loading", text: "", seq: state.seq + 1 };
    case "loaded":
      return event.seq === state.seq ? { ...state, status: "shown", text: event.text } : state;
    case "failed":
      return event.seq === state.seq ? { ...state, status: "error", text: ADVICE_ERROR } : state;
    case "changed":
      // Not re-asked by itself: every request counts toward the daily limit.
      return state.status === "idle" ? state : { status: "stale", text: ADVICE_STALE, seq: state.seq + 1 };
    case "reset":
      return { ...INITIAL, seq: state.seq + 1 };
    default:
      return state;
  }
}

function refreshLabel(state) {
  if (state.status === "stale") return "Update suggestion";
  if (state.status === "error") return "Try again";
  return null;
}


// ---------- Browser only below ----------

let adviceState = INITIAL;
let adviceItems = () => [];

function renderAdvice() {
  const s = adviceState;
  $("advice").hidden = s.status === "idle";
  const text = $("advice-text");
  text.textContent = s.status === "loading" ? ADVICE_LOADING : s.text;
  text.classList.toggle("is-error", s.status === "error");
  text.classList.toggle("is-stale", s.status === "stale");
  $("advice").classList.toggle("is-loading", s.status === "loading");
  const label = refreshLabel(s);
  $("advice-refresh").hidden = !label;
  if (label) $("advice-refresh").textContent = label;
}

function dispatchAdvice(event) {
  adviceState = nextCardState(adviceState, event);
  renderAdvice();
}

async function requestAdvice() {
  const items = adviceItems();
  if (!items.length) return resetAdvice();
  dispatchAdvice({ type: "request" });
  const seq = adviceState.seq;
  try {
    const res = await api("/api/meals/advice", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(adviceBody(items, isoDate(new Date()))),
    });
    const data = res.ok ? await res.json().catch(() => null) : null;
    if (!data || typeof data.text !== "string") throw new Error("advice");
    dispatchAdvice({ type: "loaded", seq, text: data.text });
  } catch (e) {
    dispatchAdvice({ type: "failed", seq });
  }
}

// Any change to the meal makes the shown advice describe a different meal.
function mealChanged() {
  dispatchAdvice({ type: "changed" });
}

function resetAdvice() {
  if (adviceState.status !== "idle") dispatchAdvice({ type: "reset" });
}

function initAdviceCard(getItems) {
  adviceItems = getItems;
  $("advice-note").textContent = ADVICE_NOTE;
  $("advice-refresh").addEventListener("click", requestAdvice);
  renderAdvice();
}

if (typeof module !== "undefined") {
  module.exports = { adviceBody, nextCardState, refreshLabel, INITIAL, ADVICE_NOTE, ADVICE_ERROR, ADVICE_STALE };
}
