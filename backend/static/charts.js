// Chart geometry for the Progress page. Pure functions, no DOM, so Node can test
// them (tests/charts.test.js); progress.js turns the numbers into inline SVG.

const DAY_MS = 86400000;
const r2 = (x) => Math.round(x * 100) / 100;
const dayNumber = (iso) => {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / DAY_MS;
};

// values: [{date: "YYYY-MM-DD", value}] sorted by date. Returns an SVG `points`
// string. x follows the date (gaps stay gaps), y the value (higher is higher),
// both inside `pad` from the edges. One point, or a flat line, sits mid-height.
function linePoints(values, width, height, pad) {
  if (!values.length) return "";
  const days = values.map((v) => dayNumber(v.date));
  const nums = values.map((v) => v.value);
  const d0 = Math.min(...days), d1 = Math.max(...days);
  const lo = Math.min(...nums), hi = Math.max(...nums);
  const innerW = width - 2 * pad, innerH = height - 2 * pad;
  return values.map((v, i) => {
    const x = d1 === d0 ? width / 2 : pad + ((days[i] - d0) / (d1 - d0)) * innerW;
    const y = hi === lo ? height / 2 : pad + ((hi - nums[i]) / (hi - lo)) * innerH;
    return `${r2(x)},${r2(y)}`;
  }).join(" ");
}

// Bar heights for calories against a goal. The scale top is max(goal, largest
// value) x 1.1, so the goal line and the tallest bar never touch the top edge.
// goalY is measured from the top of the chart, as SVG does.
function barHeights(values, goal, height) {
  const top = Math.max(goal || 0, ...values) * 1.1 || 1;
  return {
    bars: values.map((v) => r2((Math.max(0, v) / top) * height)),
    goalY: r2(height - ((goal || 0) / top) * height),
  };
}

if (typeof module !== "undefined") {
  module.exports = { linePoints, barHeights };
}
