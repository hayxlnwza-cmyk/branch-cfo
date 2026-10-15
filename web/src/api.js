const j = async (r) => {
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
};
export const api = {
  state: () => fetch("/api/state").then(j),
  version: () => fetch("/api/version").then(j),
  forecast: (branch) => fetch("/api/forecast" + (branch ? `?branch=${encodeURIComponent(branch)}` : "")).then(j),
  parse: (text) => fetch("/api/parse", post({ text })).then(j),
  compare: (branch_id) => fetch("/api/compare", post({ branch_id })).then(j),
  debt: () => fetch("/api/debt").then(j),
  backtest: () => fetch("/api/backtest").then(j),
  lender: () => fetch("/api/lender_export").then(j),
  outcome: (b) => fetch("/api/collections/outcome", post(b)).then(j),
  merge: (branch_id, reason) => fetch("/api/merge", post({ branch_id, reason })).then(j),
  reset: () => fetch("/api/reset", post({})).then(j),
};
function post(body) {
  return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}
