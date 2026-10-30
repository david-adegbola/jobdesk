import { api, h, register, store, message, getState } from "../core.js";

function places(text) {
  const p = (text || "").split(", ").filter(Boolean);
  return p.length > 3 ? h("span", { title: p.join(", ") }, p.slice(0, 3).join(", ") + ` +${p.length - 3} more`) : p.join(", ");
}

const daysText = d => d == null ? "" : d < 0 ? "closed" : d === 0 ? "today" : `${d} d`;

function sortJobs(jobs) {
  // Deadline first (soonest on top, none last), then newest posted
  return jobs.sort((a, b) => {
    const da = a.deadline || "9999", db = b.deadline || "9999";
    if (da !== db) return da.localeCompare(db);
    return (b.posted || "").localeCompare(a.posted || "");
  });
}

function addForm(state, onAdded) {
  const f = {};
  const field = (name, label, attrs = {}) =>
    h("label", { class: "field" }, label, f[name] = h(attrs.tag || "input", { name, ...attrs, tag: null }));
  const out = h("div");
  const form = h("form", { class: "grid", onsubmit: async e => {
      e.preventDefault();
      const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
      try {
        await api("/api/jobs", { method: "POST", body });
        form.reset();
        out.replaceChildren(message("Job added."));
        onAdded();
      } catch (err) { out.replaceChildren(message(err.message, true)); }
    } },
    field("url", "Link to the ad", { type: "url", placeholder: "https://…" }),
    field("title", "Job title", { required: true }),
    field("company", "Company"),
    field("location", "Place"),
    field("deadline", "Deadline", { type: "date" }),
    h("label", { class: "field" }, "Type",
      f.category = h("select", { name: "category" }, h("option", { value: "" }, "Work it out from the text"),
        state.job_types.map(t => h("option", { value: t }, t)))),
    field("contact_name", "Contact name"),
    field("contact_phone", "Contact phone", { type: "tel" }),
    h("label", { class: "field", style: "grid-column: 1 / -1" }, "Ad text (paste it, for Match and Blockers)",
      f.ad_text = h("textarea", { name: "ad_text" })),
    h("div", { class: "row" }, h("button", { type: "submit" }, "Add job")));
  return h("details", { class: "card" },
    h("summary", null, "Add job manually"),
    h("p", { class: "muted small" }, "For jobs from Duunitori, Työmarkkinatori, Indeed, LinkedIn or email alerts."),
    form, out);
}

register({
  id: "jobs", title: "Jobs",
  async render(main) {
    const state = await getState();
    const status = h("span", { class: "muted", role: "status" });
    const checkBtn = h("button", { onclick: startCheck }, "Check for new jobs");
    const listArea = h("div");
    main.append(h("h1", null, "Jobs"),
      h("div", { class: "row" }, checkBtn, status),
      addForm(state, load), listArea);

    async function startCheck() {
      await api("/api/scrape", { method: "POST" });
      poll();
    }
    async function poll() {
      const s = await api("/api/scrape");
      checkBtn.disabled = s.running;
      status.textContent = s.running
        ? `${s.message} (${s.done}/${s.total} categories; Jobly asks for 10 s between pages)`
        : (s.result ? `Finished: ${s.result.found} jobs, ${s.result.new} new.` : "");
      if (s.running) setTimeout(poll, 3000);
      else if (s.result) load();
    }

    const filters = {
      type: store("jobs.type") || "", status: store("jobs.status") || "",
      blocked: store("jobs.blocked") === "1", closing: store("jobs.closing") === "1",
    };
    let jobs = [];

    async function load() {
      const data = await api("/api/jobs");
      jobs = sortJobs(data.jobs);
      const c = data.latest_check;
      const newCount = jobs.filter(j => j.is_new).length;
      if (!checkBtn.disabled) status.textContent = c
        ? `Last checked: ${c.finished_at.replace("T", " ")}, ${newCount} new` + (c.error ? ` (error: ${c.error})` : "")
        : "Not checked yet.";
      draw();
    }

    function draw() {
      const types = [...new Set(jobs.map(j => j.category).filter(Boolean))].sort();
      const sel = (key, options) => h("select", { onchange: e => { filters[key] = e.target.value; store("jobs." + key, e.target.value); draw(); } },
        options.map(([v, t]) => h("option", { value: v, selected: filters[key] === v }, t)));
      const chk = (key, text) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: filters[key],
        onchange: e => { filters[key] = e.target.checked; store("jobs." + key, e.target.checked ? "1" : "0"); draw(); } }), text);

      const shown = jobs.filter(j =>
        (!filters.type || j.category === filters.type) &&
        (!filters.status || (filters.status === "none" ? !j.status : j.status === filters.status)) &&
        (!filters.blocked || !j.blockers.length) &&
        (!filters.closing || (j.days_left != null && j.days_left >= 0 && j.days_left <= 3)));

      const rows = shown.map(j => h("tr", null,
        h("td", null, j.is_new ? h("span", { class: "tag new" }, "NEW") : ""),
        h("td", null, j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener" }, j.title) : j.title,
          j.source !== "Jobly" || j.manual ? h("div", { class: "muted small" }, j.manual ? "added by hand" : j.source) : ""),
        h("td", null, j.company),
        h("td", null, places(j.location)),
        h("td", { class: "nowrap" }, j.posted),
        h("td", { class: "nowrap" + (j.days_left != null && j.days_left <= 3 && j.days_left >= 0 ? " overdue" : "") },
          j.deadline, j.deadline ? h("div", { class: "small" }, daysText(j.days_left)) : ""),
        h("td", { class: "nowrap" }, j.category),
        h("td", null, h("span", { class: "score" }, j.match.score), " ", h("span", { class: "small" }, j.match.score ? j.match.slug : "–"),
          j.match.words.length ? h("div", { class: "muted small" }, j.match.words.join(", ")) : "",
          !j.has_ad_text && j.url ? h("div", null, h("button", { class: "link small", onclick: async e => {
            e.target.disabled = true; e.target.textContent = "reading…";
            try { await api(`/api/jobs/${j.id}/fetch`, { method: "POST" }); load(); }
            catch (err) { e.target.textContent = err.message; }
          } }, "read full ad")) : ""),
        h("td", null, j.blockers.map(b => h("span", { class: "tag bad" }, b))),
        h("td", { class: "nowrap" }, j.use_cv ? h("a", { href: j.use_cv_link, target: "_blank", rel: "noopener" }, j.use_cv) : "",
          h("div", null, h("a", { class: "small", href: `#/prompt?job=${j.id}` }, "CV prompt"))),
        h("td", null, h("select", { "aria-label": `Status for ${j.title}`, onchange: async e => {
            await api(`/api/jobs/${j.id}/status`, { method: "POST", body: { status: e.target.value } });
            load();
          } }, h("option", { value: "" }, "—"), state.statuses.map(s => h("option", { value: s, selected: j.status === s }, s))))));

      listArea.replaceChildren(
        h("div", { class: "row" },
          h("label", { class: "check" }, "Type ", sel("type", [["", "All"], ...types.map(t => [t, t])])),
          h("label", { class: "check" }, "Status ", sel("status", [["", "All"], ["none", "Not saved"], ...state.statuses.map(s => [s, s])])),
          chk("blocked", "Hide blocked"), chk("closing", "Closing in 3 days"),
          h("span", { class: "muted small" }, `${shown.length} of ${jobs.length} jobs`)),
        h("p", { class: "muted small" }, "Match and Blockers read the title, company and place, plus the ad text when there is one. " +
          "For Jobly jobs, “read full ad” fetches the ad page for a better check."),
        h("div", { class: "scroll" }, h("table", null,
          h("thead", null, h("tr", null, ["", "Job", "Company", "Location", "Posted", "Deadline", "Type", "Match", "Blockers", "Use CV", "Status"].map(t => h("th", null, t)))),
          h("tbody", null, rows.length ? rows : h("tr", null, h("td", { colspan: 11, class: "empty" },
            jobs.length ? "No jobs match these filters." : "No jobs yet. Press “Check for new jobs” or add one by hand."))))));
    }

    await load();
    poll();
  },
});
