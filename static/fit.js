// How well a job fits the member's CV: the rating, strengths, gaps and recommendations, from
// POST /api/jobs/<id>/evaluate (queued in the background) and GET /api/jobs/<id>/fit.
import { api, h, message } from "./core.js";

// The words carry the meaning; the colour only repeats it.
export const FIT = {
  strong: ["Strong fit", "tag new"],
  possible: ["Possible fit", "tag"],
  stretch: ["A stretch", "tag warn"],
  weak: ["Weak fit", "tag bad"],
};

// The fit ring, shared by Home, My jobs and the Tracker. A current CV comparison is a rating, shown as a symbol
// that fits the ring (the colour repeats it, the label says it in words); otherwise the keyword match, 0–100.
const RATING = {
  strong: { score: 90, symbol: "✓✓", level: "high" },
  possible: { score: 70, symbol: "✓", level: "mid" },
  stretch: { score: 50, symbol: "≈", level: "low" },
  weak: { score: 30, symbol: "✗", level: "low" },
};

export function fitScore(job) {
  if (job?.fit && !job.fit.stale) return (RATING[job.fit.suitability] || RATING.stretch).score;
  return job?.match?.score || 0;
}

export function fitRing(job, size = "") {
  if (!job) return "";
  if (job.fit && !job.fit.stale) {
    const rating = RATING[job.fit.suitability] || RATING.stretch;
    const [label] = FIT[job.fit.suitability] || FIT.stretch;
    return h("span", { class: `fit-ring ${size} ${rating.level} is-rating`, role: "img", "aria-label": `${label} with your CV` },
      h("span", { "aria-hidden": "true" }, rating.symbol));
  }
  const n = job.match?.score || 0;
  const level = n >= 75 ? "high" : n >= 60 ? "mid" : "low";
  return h("span", { class: `fit-ring ${size} ${level}`, role: "img", "aria-label": `Keyword match with your CV: ${n} out of 100` },
    h("span", { "aria-hidden": "true" }, String(n)));
}

export function fitBadge(f) {
  const [label, cls] = FIT[f.suitability] || FIT.stretch;
  return h("span", { class: cls }, label + (f.stale ? " (out of date)" : ""));
}

const METHODS = { llm: "AI, checked against your CV and the ad", rules: "word comparison, without AI" };

function evaluationView(e, jobId, onChange) {
  const quote = q => q ? h("div", { class: "small" }, "Ad: ", h("q", null, q)) : "";
  const list = (items, render, empty) => items.length ? h("ul", null, items.map(i => h("li", null, render(i))))
    : h("p", { class: "muted small" }, empty);
  return h("div", { class: "fit" },
    h("p", null, fitBadge(e), " ", e.summary || ""),
    e.notice ? h("p", { class: "muted small" }, e.notice) : "",
    h("h3", null, "Strengths"),
    list(e.strengths, s => [s.point, quote(s.ad_quote),
      h("div", { class: "muted small" }, "Your CV: ", (s.facts || s.fact_ids).join(" · "))], "Nothing in your CV clearly matches this ad."),
    h("h3", null, "Gaps"),
    list(e.gaps, g => [h("b", null, g.requirement), quote(g.ad_quote !== g.requirement ? g.ad_quote : ""),
      g.advice ? h("div", { class: "small" }, g.advice) : ""], "No gaps found."),
    h("h3", null, "Recommendations"),
    list(e.recommendations, r => r, "None."),
    h("p", { class: "muted small" }, `Compared with “${e.cv_title}” on ${e.created_at.replace("T", " ").slice(0, 16)} by ` +
      `${METHODS[e.method] || e.method}${e.model ? ` (${e.model})` : ""}. ` +
      (e.checks?.dropped_strengths || e.checks?.cleared_quotes
        ? `${e.checks.dropped_strengths} unsupported strength(s) and ${e.checks.cleared_quotes} quote(s) not found in the ad were removed. ` : "") +
      "It can be wrong: read the ad yourself."),
    h("div", { class: "row" },
      h("a", { class: "btn small", href: `#/prepare?job=${jobId}` }, "Prepare CV, letter and email"),
      e.stale ? h("button", { class: "secondary small", onclick: () => evaluate(jobId, false).then(onChange) },
        "Compare again (the ad or your CV changed)") : "",
      h("button", { class: "secondary small", onclick: async () => {
        await api(`/api/jobs/${jobId}/status`, { method: "POST", body: { status: "Not a fit" } }); onChange(true);
      } }, "Mark as not a fit")));
}

export async function evaluate(jobId, shortlist) {
  return api(`/api/jobs/${jobId}/evaluate`, { method: "POST", body: { shortlist } });
}

// A panel that shows the evaluation, or its progress while the background task runs.
// onChange(reloadList) is called when the member acts on it.
// note: a message to show first (for example "Add a CV first").
export function fitPanel(jobId, onChange, note) {
  const box = h("div", { "aria-live": "polite" }, h("p", { class: "muted small" }, "Loading…"));
  async function refresh() {
    if (!box.isConnected && box.dataset.started) return;      // the table was redrawn: stop polling
    box.dataset.started = "1";
    try {
      const { evaluation, task } = await api(`/api/jobs/${jobId}/fit`);
      if (task && (task.status === "queued" || task.status === "running")) {
        box.replaceChildren(h("p", { class: "muted small" }, task.status === "queued"
          ? "Waiting in the queue to compare this job with your CV…" : "Comparing this job with your CV…"));
        setTimeout(refresh, 1500);
        return;
      }
      const failed = task && task.status === "failed" ? message(`The comparison failed: ${task.error}`, true) : "";
      box.replaceChildren(note ? message(note, true) : "", failed, evaluation ? evaluationView(evaluation, jobId, again => again ? onChange(true) : refresh())
        : h("div", { class: "row" }, h("span", { class: "muted small" }, "Not compared with your CV yet."),
          h("button", { class: "secondary small", onclick: async () => { await start(); } }, "Compare with my CV")));
    } catch (error) { box.replaceChildren(message(error.message, true)); }
  }
  async function start(shortlist = false) {
    try {
      const r = await evaluate(jobId, shortlist);
      if (r.needs_cv || r.needs_text) { box.replaceChildren(message(r.message, true)); return r; }
      refresh();
      return r;
    } catch (error) { box.replaceChildren(message(error.message, true)); return null; }
  }
  box.start = start;
  setTimeout(refresh, 0);
  return box;
}
