// The Tracker's rules, without the DOM (tests/js/tracker.test.mjs runs them in Node).

export const STAGE_LABEL = { Rejected: "Not this time" };       // stored statuses stay; only the title is kinder
export const stageLabel = status => STAGE_LABEL[status] || status;
export const RATING_RANK = { strong: 4, possible: 3, stretch: 2, weak: 1 };

// The deadline as a chip: red within 3 days, grey "Closed" once passed
export function deadlineChip(app, today = new Date()) {
  if (app.days_left == null) return null;
  if (app.days_left < 0) return { kind: "closed", text: "Closed" };
  const day = app.deadline ? formatDay(app.deadline) : "";
  if (app.days_left === 0) return { kind: "soon", text: "Closes today" };
  if (app.days_left === 1) return { kind: "soon", text: "Closes tomorrow" };
  if (app.days_left <= 3) return { kind: "soon", text: `Closes in ${app.days_left} days` };
  return { kind: "normal", text: `Closes ${day}` };
}

export function formatDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${Number(m[3])}.${Number(m[2])}.` : iso;
}

// "Espoo", "Espoo +1", "Espoo · also abroad"; the posting's own text when no Finnish town is named
export function placeText(app) {
  if (!app.town) return app.place_text || "";
  return app.town + (app.other_towns ? ` +${app.other_towns}` : "") + (app.abroad ? " · also abroad" : "");
}

export function matchesSearch(app, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  return [app.title, app.company, app.location, app.notes].some(v => (v || "").toLowerCase().includes(q));
}

// filter: "all" | "week" (closes within 7 days) | "closed"
export function passesFilter(app, filter) {
  if (filter === "week") return app.days_left != null && app.days_left >= 0 && app.days_left <= 7;
  if (filter === "closed") return Boolean(app.closed);
  return true;
}

export function sortCards(apps, sort) {
  const added = a => a.created_at || "";
  const byDeadline = (a, b) => (a.days_left ?? 1e9) - (b.days_left ?? 1e9) || added(b).localeCompare(added(a));
  const compare = {
    deadline: byDeadline,
    added: (a, b) => added(b).localeCompare(added(a)),
    match: (a, b) => (RATING_RANK[b.rating] || 0) - (RATING_RANK[a.rating] || 0) || byDeadline(a, b),
  }[sort] || byDeadline;
  return [...apps].sort(compare);
}

// A stage's cards: open ones first (sorted), then closed ones (dimmed, at the end), or none if they're hidden
export function stageCards(apps, status, { query = "", filter = "all", sort = "deadline", hideClosed = false } = {}) {
  const shown = apps.filter(a => a.status === status && matchesSearch(a, query) && passesFilter(a, filter)
    && !(hideClosed && a.closed && filter !== "closed"));
  const sorted = sortCards(shown, sort);
  return { open: sorted.filter(a => !a.closed), closed: sorted.filter(a => a.closed) };
}

// "5 saved · 2 closing this week · 0 applied"
export function summary(apps) {
  const count = status => apps.filter(a => a.status === status).length;
  const week = apps.filter(a => ["Saved", "Shortlisted"].includes(a.status) && a.days_left != null && a.days_left >= 0 && a.days_left <= 7).length;
  return `${count("Saved")} saved · ${week} closing this week · ${count("Applied")} applied` +
    (count("Interview") ? ` · ${count("Interview")} at interview` : "");
}

// Stack or rail: empty stages are rails; a stage the member folded stays a rail; one they opened stays a stack
export function layoutFor(status, count, prefs) {
  if ((prefs.collapsed || []).includes(status)) return "rail";
  if (count === 0 && !(prefs.expanded || []).includes(status)) return "rail";
  return "stack";
}

// The optimistic move: the new list right away, and the one to go back to if saving fails
export function moved(apps, id, status) {
  const before = apps;
  const after = apps.map(a => (a.id === id ? { ...a, status } : a));
  return { before, after };
}
