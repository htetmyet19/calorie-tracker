// Small DOM and date helpers shared by the app and login pages. Load before the
// page's own script. isoDate and parseDate are pure (tests/dom.test.js).

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

const pad = (n) => String(n).padStart(2, "0");
// The browser's local calendar date. Not toISOString(), which is UTC: in Yangon
// (UTC+6:30) that would still say yesterday until 06:30.
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = parseDate(s); d.setDate(d.getDate() + n); return isoDate(d); };

// An inline message under a field (inside a .field wrapper), as on the login page:
// red border via [aria-invalid], message linked with aria-describedby. "" clears it.
function fieldError(input, msg) {
  const id = input.id + "-error";
  let note = document.getElementById(id);
  if (!note) {
    note = document.createElement("p");
    note.className = "field-error";
    note.id = id;
    input.closest(".field").after(note);
    input.setAttribute("aria-describedby", ((input.getAttribute("aria-describedby") || "") + " " + id).trim());
  }
  note.textContent = msg;
  note.hidden = !msg;
  // aria-invalid="" reads as false to screen readers, so set "true" explicitly.
  if (msg) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

if (typeof module !== "undefined") {
  module.exports = { pad, isoDate, parseDate, addDays };
}
