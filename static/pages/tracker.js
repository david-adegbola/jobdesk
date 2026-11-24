// Applications → Tracker: a board of the member's applications, one column per status. Every card says the one
// thing to do next. Drag a card, or use "Move to", to change its status.
import { api, h, register, message, getState, today } from "../core.js";

const LABEL = { Rejected: "Not this time" };       // stored statuses stay the same; only the column title is kinder
const EMPTY = { Saved: "Save jobs from Discover.", Shortlisted: "Shortlist a saved job to check your fit.", Applied: "Drag a card here when you've applied.",
  Interview: "Interviews come after applying.", Offer: "No offers yet. Keep going.", Rejected: "Nothing here, and that's fine." };

function fitRing(job) {
  if (!job) return "";
  const ai = job.fit && !job.fit.stale;
  const n = ai ? job.fit.suitability : (job.match?.score || 0);
  const level = n >= 75 ? "high" : n >= 60 ? "mid" : "low";
  return h("span", { class: `fit-ring mini ${level}`, role: "img", "aria-label": `${ai ? "Fit" : "Keyword match"} with your CV: ${n} out of 100` },
    h("span", null, String(n)));
}

// The one next step: the member's own, else a reminder, else what usually comes next at this stage
function nextStep(a) {
  if (a.next_action || a.next_action_date) return h("div", { class: "next" + (a.overdue ? " overdue" : "") },
    h("strong", null, a.overdue ? "Overdue: " : "Next: "), a.next_action || "(no action)", a.next_action_date ? ` · ${a.next_action_date}` : "");
  if (a.follow_up) return h("div", { class: "reminder" }, a.follow_up);
  if (a.status === "Saved" || a.status === "Shortlisted") return h("div", { class: "next" },
    h("strong", null, "Next: "), h("a", { href: `#/prepare?job=${a.job_id}` }, "prepare your CV and letter"), a.deadline ? ` · closes ${a.deadline}` : "");
  if (a.status === "Applied" && a.date_applied) return h("div", { class: "next quiet" }, `Applied ${a.date_applied}. No news yet.`);
  if (a.status === "Interview") return h("div", { class: "next" }, h("strong", null, "Next: "), h("a", { href: "#/draft" }, "practise your answers"));
  return "";
}

function card(a, job, roles, statuses, reload) {
  const f = {};
  const input = (name, label, type = "text") =>
    h("label", { class: "field" }, label, f[name] = h("input", { type, value: a[name] || "" }));
  const out = h("div");
  const cv = roles.find(role => role.slug === a.cv_role);
  const meta = [
    a.cv_role ? ["CV", cv?.title || a.cv_role] : null,
    a.date_applied ? ["Applied", a.date_applied] : null,
    a.contact ? ["Contact", a.contact] : null,
  ].filter(Boolean);
  return h("article", { class: "app-card", draggable: "true", "data-id": a.id, "data-status": a.status,
      ondragstart: e => { e.dataTransfer.setData("text/plain", String(a.id)); e.dataTransfer.effectAllowed = "move"; e.currentTarget.classList.add("dragging"); },
      ondragend: e => e.currentTarget.classList.remove("dragging") },
    h("div", { class: "app-card-top" }, h("span", { class: "muted small" }, [a.company, a.location].filter(Boolean).join(" · ") || "Employer not given"), fitRing(job)),
    h("div", { class: "title" }, a.url ? h("a", { href: a.url, target: "_blank", rel: "noopener" }, a.title) : a.title),
    nextStep(a),
    meta.length ? h("dl", { class: "meta" }, meta.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)])) : "",
    h("label", { class: "move" }, "Move to",
      h("select", { class: "status", "data-status": a.status, "data-focus": `status:${a.id}`, "aria-label": `Status for ${a.title}`, onchange: async e => {
          await api(`/api/applications/${a.id}`, { method: "POST", body: { status: e.target.value } }); reload(`status:${a.id}`);
        } }, statuses.map(s => h("option", { value: s, selected: s === a.status }, LABEL[s] || s)))),
    h("details", null, h("summary", { "data-focus": `details:${a.id}` }, "Details and next step"),
      h("form", { onsubmit: async e => {
          e.preventDefault();
          const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
          try { await api(`/api/applications/${a.id}`, { method: "POST", body }); reload(`details:${a.id}`); }
          catch (err) { out.replaceChildren(message(err.message, true)); }
        } },
        input("next_action", "Next action"),
        input("next_action_date", "Next action date", "date"),
        input("date_applied", "Date applied", "date"),
        h("label", { class: "field" }, "CV used",
          f.cv_role = h("select", null, h("option", { value: "" }, "—"),
            roles.map(r => h("option", { value: r.slug, selected: r.slug === a.cv_role }, r.title)))),
        input("employer_link", "Employer link sent", "url"),
        input("contact", "Contact"),
        h("label", { class: "field" }, "Notes", f.notes = h("textarea", null, a.notes || "")),
        h("button", { type: "submit" }, "Save"), out)));
}

register({
  id: "tracker", title: "Tracker",
  async render(main) {
    const state = await getState();
    // The board scrolls sideways, so it must be reachable with the keyboard (WCAG 2.1.1)
    const board = h("div", { class: "kanban", tabindex: 0, role: "region", "aria-label": "Applications by status" });
    main.append(h("div", { class: "page-head" },
        h("div", null, h("h1", null, "Applications"),
          h("p", { class: "muted" }, "Drag a card to change its stage, or use “Move to”. Every card shows the one thing to do next; " +
            `an application with no news for 5 days gets a follow-up reminder. Today: ${today()}.`)),
        h("div", { class: "page-head-side" }, h("a", { class: "btn secondary", href: "/api/calendar.ics", download: "jobdesk.ics" }, "Add dates to my calendar (.ics)"))),
      board);

    async function load(restoreKey) {
      const focusKey = restoreKey || document.activeElement?.dataset.focus;
      const [{ applications, statuses }, { jobs }] = await Promise.all([api("/api/applications"), api("/api/jobs").catch(() => ({ jobs: [] }))]);
      const jobById = Object.fromEntries(jobs.map(j => [j.id, j]));
      board.replaceChildren(...statuses.map(status => {
        const items = applications.filter(a => a.status === status);
        const col = h("section", { class: "column status", "data-status": status, "aria-label": `${LABEL[status] || status}: ${items.length}`,
            ondragover: e => { e.preventDefault(); col.classList.add("over"); },
            ondragleave: e => { if (!col.contains(e.relatedTarget)) col.classList.remove("over"); },
            ondrop: async e => {
              e.preventDefault(); col.classList.remove("over");
              const id = e.dataTransfer.getData("text/plain");
              if (id) { await api(`/api/applications/${id}`, { method: "POST", body: { status } }); load(); }
            } },
          h("h2", { class: "column-head" }, LABEL[status] || status, h("span", { class: "count" }, items.length)),
          h("div", { class: "column-body" },
            items.length ? items.map(a => card(a, jobById[a.job_id], state.roles, statuses, load))
                         : h("p", { class: "empty" }, EMPTY[status] || "Drag a card here.")));
        return col;
      }));
      if (focusKey) {
        const target = [...board.querySelectorAll("[data-focus]")].find(el => el.dataset.focus === focusKey);
        target?.focus();
      }
    }
    await load();
  },
});
