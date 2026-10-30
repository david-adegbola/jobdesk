import { api, h, register, message, getState, today } from "../core.js";

const kanbanCss = `
.kanban { display: grid; grid-template-columns: repeat(5, minmax(220px, 1fr)); gap: 12px; overflow-x: auto; padding-bottom: 8px; }
.column { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px; min-height: 160px; }
.column.over { outline: 2px dashed var(--accent); }
.column h2 { margin: 0 0 8px; font-size: 1rem; display: flex; justify-content: space-between; }
.app-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin-bottom: 8px; background: var(--bg); cursor: grab; }
.app-card .title { font-weight: 700; }
.app-card details summary { cursor: pointer; color: var(--accent); font-size: .85rem; margin-top: 6px; }
.app-card form { display: grid; gap: 8px; margin-top: 8px; }
.app-card label.field { font-size: .8rem; }
.app-card input, .app-card select, .app-card textarea { width: 100%; }
.app-card textarea { min-height: 70px; }
.reminder { margin-top: 6px; padding: 4px 8px; border-radius: 6px; background: var(--warn-bg); color: var(--warn-fg); font-size: .82rem; font-weight: 600; }
`;

function card(a, roles, statuses, reload) {
  const f = {};
  const input = (name, label, type = "text") =>
    h("label", { class: "field" }, label, f[name] = h("input", { type, value: a[name] || "" }));
  const out = h("div");
  return h("div", { class: "app-card", draggable: "true", "data-id": a.id,
      ondragstart: e => { e.dataTransfer.setData("text/plain", String(a.id)); e.dataTransfer.effectAllowed = "move"; } },
    h("div", { class: "title" }, a.url ? h("a", { href: a.url, target: "_blank", rel: "noopener" }, a.title) : a.title),
    h("div", { class: "muted small" }, [a.company, a.location].filter(Boolean).join(" · ")),
    a.cv_role ? h("div", { class: "small" }, "CV: ", a.employer_link ? h("a", { href: a.employer_link, target: "_blank", rel: "noopener" }, a.cv_role) : a.cv_role) : "",
    a.date_applied ? h("div", { class: "small muted" }, `Applied ${a.date_applied}`) : "",
    a.next_action || a.next_action_date ? h("div", { class: "small" + (a.overdue ? " overdue" : "") },
      "Next: ", a.next_action || "(no action)", a.next_action_date ? ` · ${a.next_action_date}` : "", a.overdue ? " · overdue" : "") : "",
    a.follow_up ? h("div", { class: "reminder" }, a.follow_up) : "",
    h("label", { class: "check small" }, "Move to ",
      h("select", { "aria-label": `Status for ${a.title}`, onchange: async e => {
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
    if (!document.getElementById("kanban-css")) document.head.append(h("style", { id: "kanban-css" }, kanbanCss));
    const state = await getState();
    const board = h("div", { class: "kanban" });
    main.append(h("h1", null, "Tracker"),
      h("div", { class: "row" },
        h("a", { class: "btn secondary", href: "/api/calendar.ics", download: "jobdesk.ics" }, "Export deadlines and interviews (.ics)"),
        h("span", { class: "muted small" }, `Applied with no change for 5 days shows a follow-up reminder. Today: ${today()}`)),
      board);

    async function load() {
      const { applications, statuses } = await api("/api/applications");
      board.replaceChildren(...statuses.map(status => {
        const items = applications.filter(a => a.status === status);
        const col = h("section", { class: "column", "aria-label": status,
            ondragover: e => { e.preventDefault(); col.classList.add("over"); },
            ondragleave: () => col.classList.remove("over"),
            ondrop: async e => {
              e.preventDefault(); col.classList.remove("over");
              const id = e.dataTransfer.getData("text/plain");
              if (id) { await api(`/api/applications/${id}`, { method: "POST", body: { status } }); load(); }
            } },
          h("h2", null, status, h("span", { class: "muted" }, items.length)),
          items.length ? items.map(a => card(a, state.roles, statuses, load))
                       : h("p", { class: "muted small" }, status === "Saved" ? "Save jobs from the Jobs page." : "Drop a card here."));
        return col;
      }));
    }
    await load();
  },
});
