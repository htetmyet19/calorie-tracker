// Meal advice card on the result screen: "Have you eaten this yet?" → a short suggestion.
// Needs dom.js and auth.js loaded first; app.js calls initAdviceCard() and resetAdvice().
// The functions up to "Browser only" are pure so Node can test them (tests/advice.test.js).

const ADVICE_NOTE = "Estimates are approximate. If food or eating feels stressful, talk to a doctor or someone you trust.";
const ADVICE_ERROR = "Couldn't get a suggestion. You can still save the meal.";
const ADVICE_LOADING = "Thinking…";

// Only what the server reads. Items added by hand may have no name yet.
function adviceBody(items, eaten, today) {
  return {
    items: items.map((i) => ({
      name: (i.name || "").trim() || "Food item",
      calories: i.calories, protein_g: i.protein_g, carbs_g: i.carbs_g, fat_g: i.fat_g,
    })),
    eaten,
    date: today,
  };
}

// seq grows with every choice and reset, so a late answer for an older one is ignored.
const INITIAL = Object.freeze({ choice: null, status: "idle", text: "", seq: 0 });

function nextCardState(state, event) {
  switch (event.type) {
    case "choose":
      return { choice: event.eaten, status: "loading", text: "", seq: state.seq + 1 };
    case "loaded":
      return event.seq === state.seq ? { ...state, status: "shown", text: event.text } : state;
    case "failed":
      // The choice is cleared so tapping the same option again retries.
      return event.seq === state.seq ? { ...state, choice: null, status: "error", text: ADVICE_ERROR } : state;
    case "reset":
      return { ...INITIAL, seq: state.seq + 1 };
    default:
      return state;
  }
}


// ---------- Browser only below ----------

let adviceState = INITIAL;
let adviceItems = () => [];

function renderAdvice() {
  const s = adviceState;
  const text = $("advice-text");
  text.textContent = s.status === "loading" ? ADVICE_LOADING : s.text;
  text.classList.toggle("is-error", s.status === "error");
  $("advice").classList.toggle("is-loading", s.status === "loading");
  for (const r of document.querySelectorAll('input[name="advice-eaten"]')) {
    r.checked = s.choice !== null && (r.value === "yes") === s.choice;
    r.disabled = s.status === "loading";
  }
}

function dispatchAdvice(event) {
  adviceState = nextCardState(adviceState, event);
  renderAdvice();
}

async function askAdvice(eaten) {
  dispatchAdvice({ type: "choose", eaten });
  const seq = adviceState.seq;
  try {
    const res = await api("/api/meals/advice", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(adviceBody(adviceItems(), eaten, isoDate(new Date()))),
    });
    const data = res.ok ? await res.json().catch(() => null) : null;
    if (!data || typeof data.text !== "string") throw new Error("advice");
    dispatchAdvice({ type: "loaded", seq, text: data.text });
  } catch (e) {
    dispatchAdvice({ type: "failed", seq });
  }
}

// Any change to the meal makes the shown advice describe a different meal: clear it.
function resetAdvice() {
  if (adviceState.status !== "idle") dispatchAdvice({ type: "reset" });
}

function initAdviceCard(getItems) {
  adviceItems = getItems;
  $("advice-note").textContent = ADVICE_NOTE;
  for (const r of document.querySelectorAll('input[name="advice-eaten"]')) {
    r.addEventListener("change", () => { if (r.checked) askAdvice(r.value === "yes"); });
  }
  renderAdvice();
}

if (typeof module !== "undefined") {
  module.exports = { adviceBody, nextCardState, INITIAL, ADVICE_NOTE, ADVICE_ERROR };
}
