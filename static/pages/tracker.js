import { api, h, register, message, getState, today } from "../core.js";

function card(a, roles, statuses, reload) {
  const f = {};
  const input = (name, label, type = "text") =>
    h("label", { class: "field" }, label, f[name] = h("input", { type, value: a[name] || "" }));
  const out = h("div");
  const meta = [
    a.company || a.location ? ["Employer", [a.company, a.location].filter(Boolean).join(" · ")] : null,
    a.cv_role ? ["CV", a.employer_link ? h("a", { href: a.employer_link, target: "_blank", rel: "noopener" }, a.cv_role) : a.cv_role] : null,
    a.date_applied ? ["Applied", a.date_applied] : null,
    a.contact ? ["Contact", a.contact] : null,
  ].filter(Boolean);
  return h("article", { class: "app-card", draggable: "true", "data-id": a.id, "data-status": a.status,
      ondragstart: e => { e.dataTransfer.setData("text/plain", String(a.id)); e.dataTransfer.effectAllowed = "move"; e.currentTarget.classList.add("dragging"); },
      ondragend: e => e.currentTarget.classList.remove("dragging") },
    h("div", { class: "title" }, a.url ? h("a", { href: a.url, target: "_blank", rel: "noopener" }, a.title) : a.title),
    meta.length ? h("dl", { class: "meta" }, meta.flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)])) : "",
    a.next_action || a.next_action_date ? h("div", { class: "next" + (a.overdue ? " overdue" : "") },
      h("strong", null, a.overdue ? "Overdue: " : "Next: "), a.next_action || "(no action)",
      a.next_action_date ? ` · ${a.next_action_date}` : "") : "",
    a.follow_up ? h("div", { class: "reminder" }, a.follow_up) : "",
    a.status === "Applied" || a.status === "Interview"
      ? h("a", { class: "prep-link", href: `#/prep?job=${a.job_id}` }, "Prep: call script and answers") : "",
    h("label", { class: "move" }, "Move to",
      h("select", { class: "status", "data-status": a.status, "aria-label": `Status for ${a.title}`, onchange: async e => {
          await api(`/api/applications/${a.id}`, { method: "POST", body: { status: e.target.value } }); reload();
        } }, statuses.map(s => h("option", { value: s, selected: s === a.status }, s)))),
    h("details", null, h("summary", null, "Details"),
      h("form", { onsubmit: async e => {
          e.preventDefault();
          const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
          try { await api(`/api/applications/${a.id}`, { method: "POST", body }); reload(); }
          catch (err) { out.replaceChildren(message(err.message, true)); }
        } },
        input("date_applied", "Date applied", "date"),
        h("label", { class: "field" }, "CV used",
          f.cv_role = h("select", null, h("option", { value: "" }, "—"),
            roles.map(r => h("option", { value: r.slug, selected: r.slug === a.cv_role }, r.slug)))),
        input("employer_link", "Employer link sent", "url"),
        input("contact", "Contact"),
        h("label", { class: "field" }, "Notes", f.notes = h("textarea", null, a.notes || "")),
        input("next_action", "Next action"),
        input("next_action_date", "Next action date", "date"),
        h("button", { type: "submit" }, "Save"), out)));
}

register({
  id: "tracker", title: "Tracker",
  async render(main) {
    const state = await getState();
    const board = h("div", { class: "kanban" });
    main.append(h("h1", null, "Tracker"),
      h("div", { class: "row" },
        h("a", { class: "btn secondary", href: "/api/calendar.ics", download: "jobdesk.ics" }, "Export deadlines and interviews (.ics)"),
        h("span", { class: "muted small" }, `Drag cards between columns or use "Move to". Applied with no change for 5 days shows a follow-up reminder. Today: ${today()}`)),
      board);

    async function load() {
      const { applications, statuses } = await api("/api/applications");
      board.replaceChildren(...statuses.map(status => {
        const items = applications.filter(a => a.status === status);
        const col = h("section", { class: "column status", "data-status": status, "aria-label": `${status}: ${items.length}`,
            ondragover: e => { e.preventDefault(); col.classList.add("over"); },
            ondragleave: e => { if (!col.contains(e.relatedTarget)) col.classList.remove("over"); },
            ondrop: async e => {
              e.preventDefault(); col.classList.remove("over");
              const id = e.dataTransfer.getData("text/plain");
              if (id) { await api(`/api/applications/${id}`, { method: "POST", body: { status } }); load(); }
            } },
          h("h2", { class: "column-head" }, status, h("span", { class: "count" }, items.length)),
          h("div", { class: "column-body" },
            items.length ? items.map(a => card(a, state.roles, statuses, load))
                         : h("p", { class: "empty" }, status === "Saved" ? "Save jobs from the Jobs page." : "Drag a card here.")));
        return col;
      }));
    }
    await load();
  },
});
