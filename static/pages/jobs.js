import { api, h, register, store, message, getState } from "../core.js";

function places(text) {
  const p = (text || "").split(", ").filter(Boolean);
  return p.length > 3 ? h("span", { title: p.join(", ") }, p.slice(0, 3).join(", ") + ` +${p.length - 3} more`) : p.join(", ");
}

const daysText = d => d == null ? "" : d < 0 ? "closed" : d === 0 ? "today" : `${d} d`;

// Sortable columns -> header text. Sort is a list of levels, most important first: [{key, dir: 1 | -1}]
const SORTABLE = { posted: "Posted", deadline: "Deadline", category: "Type", match: "Match" };
const MAX_LEVELS = 3;
const defaultView = () => ({ sort: [{ key: "deadline", dir: 1 }, { key: "match", dir: -1 }],
  posted: "", deadline: "", hideExpired: true, types: [], minMatch: 0 });

function loadJSON(key) {
  try { return JSON.parse(store(key) || "null"); } catch (e) { return null; }
}

function loadView() {
  const v = { ...defaultView(), ...(loadJSON("jobs.view") || {}) };
  v.sort = (Array.isArray(v.sort) ? v.sort : []).filter(s => SORTABLE[s.key] && (s.dir === 1 || s.dir === -1)).slice(0, MAX_LEVELS);
  if (!Array.isArray(v.types)) v.types = [];
  return v;
}

function loadTypeOrder(jobTypes) {
  const saved = (loadJSON("jobs.typeOrder") || []).filter(t => jobTypes.includes(t));
  return [...saved, ...jobTypes.filter(t => !saved.includes(t))];
}

// null = empty (no date, no score, no type): always sorted last
function sortValue(j, key, typeOrder) {
  if (key === "posted") return j.posted || null;
  if (key === "deadline") return j.deadline || null;
  if (key === "match") return j.match.score || null;
  if (!j.category) return null;
  const i = typeOrder.indexOf(j.category);
  return i < 0 ? typeOrder.length : i;
}

function sortJobs(jobs, sort, typeOrder) {
  return [...jobs].sort((a, b) => {
    for (const { key, dir } of sort) {
      const va = sortValue(a, key, typeOrder), vb = sortValue(b, key, typeOrder);
      if (va === vb) continue;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va < vb ? -1 : 1) * dir;
    }
    return 0;
  });
}

const daysAgo = n => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };

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

    const filters = { status: store("jobs.status") || "", blocked: store("jobs.blocked") === "1" };
    let view = loadView();          // sort + column filters, saved as one preference
    let typeOrder = loadTypeOrder(state.job_types);
    let typeOrderOpen = false;
    let jobs = [];
    const saveView = () => store("jobs.view", JSON.stringify(view));

    async function load() {
      const data = await api("/api/jobs");
      jobs = data.jobs;
      const c = data.latest_check;
      const newCount = jobs.filter(j => j.is_new).length;
      if (!checkBtn.disabled) status.textContent = c
        ? `Last checked: ${c.finished_at.replace("T", " ")}, ${newCount} new` + (c.error ? ` (error: ${c.error})` : "")
        : "Not checked yet.";
      draw();
    }

    // skip: leave one filter out (the Type chips count jobs that pass every other filter)
    function passes(j, skip) {
      const d = j.days_left;
      return (!filters.status || (filters.status === "none" ? !j.status : j.status === filters.status)) &&
        (!filters.blocked || !j.blockers.length) &&
        (!view.posted || (j.posted && j.posted >= daysAgo(+view.posted))) &&
        (view.deadline !== "none" || !j.deadline) &&
        (!(+view.deadline) || (d != null && d >= 0 && d <= +view.deadline)) &&
        (!view.hideExpired || d == null || d >= 0) &&
        (skip === "type" || !view.types.length || view.types.includes(j.category)) &&
        (!view.minMatch || j.match.score >= view.minMatch);
    }

    function clickSort(key, shift) {
      const i = view.sort.findIndex(s => s.key === key);
      if (i >= 0) {
        if (view.sort[i].dir === 1) view.sort[i].dir = -1;
        else view.sort.splice(i, 1);
      } else if (shift) {
        if (view.sort.length >= MAX_LEVELS) view.sort.pop();
        view.sort.push({ key, dir: 1 });
      } else view.sort = [{ key, dir: 1 }];
      saveView(); update();
    }

    function moveSort(from, to) {
      if (to < 0 || to >= view.sort.length || from === to) return;
      const [s] = view.sort.splice(from, 1);
      view.sort.splice(to, 0, s);
      saveView(); update();
    }

    function moveType(i, step) {
      [typeOrder[i], typeOrder[i + step]] = [typeOrder[i + step], typeOrder[i]];
      store("jobs.typeOrder", JSON.stringify(typeOrder));
      update();
    }

    // The filter controls are built once (and on Reset) so a dragged slider keeps focus;
    // update() redraws the sort chips, Type chips and table around them.
    const controls = h("div"), typeChips = h("div", { class: "row" }), sortChips = h("div", { class: "row" }), tableArea = h("div");
    listArea.replaceChildren(controls, typeChips, sortChips, tableArea);

    function draw() {
      const sel = (value, onchange, options) => h("select", { onchange: e => { onchange(e.target.value); update(); } },
        options.map(([v, t]) => h("option", { value: v, selected: value === v }, t)));
      const setView = key => v => { view[key] = v; saveView(); };
      const matchOut = h("output", null, view.minMatch);
      controls.replaceChildren(h("div", { class: "row" },
        h("label", { class: "check" }, "Posted ", sel(view.posted, setView("posted"),
          [["", "Any time"], ["3", "Last 3 days"], ["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"]])),
        h("label", { class: "check" }, "Deadline ", sel(view.deadline, setView("deadline"),
          [["", "Any"], ["3", "Closing in 3 days"], ["7", "Closing in 7 days"], ["14", "Closing in 14 days"], ["none", "No deadline"]])),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: view.hideExpired,
          onchange: e => { view.hideExpired = e.target.checked; saveView(); update(); } }), "Hide expired"),
        h("label", { class: "check" }, "Match at least ", h("input", { type: "range", min: 0, max: 100, step: 5, value: view.minMatch,
          oninput: e => { view.minMatch = +e.target.value; matchOut.textContent = view.minMatch; saveView(); update(); } }), matchOut),
        h("label", { class: "check" }, "Status ", sel(filters.status, v => { filters.status = v; store("jobs.status", v); },
          [["", "All"], ["none", "Not saved"], ...state.statuses.map(s => [s, s])])),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: filters.blocked,
          onchange: e => { filters.blocked = e.target.checked; store("jobs.blocked", e.target.checked ? "1" : "0"); update(); } }), "Hide blocked"),
        h("button", { class: "secondary", onclick: () => {
          view = defaultView(); filters.status = ""; filters.blocked = false;
          saveView(); store("jobs.status", ""); store("jobs.blocked", "0"); draw();
        } }, "Reset")));
      update();
    }

    function update() {
      // Re-rendering replaces the buttons, so put keyboard focus back on the same one
      const focusKey = document.activeElement && document.activeElement.dataset.focus;

      const counts = {};
      for (const j of jobs) if (j.category && passes(j, "type")) counts[j.category] = (counts[j.category] || 0) + 1;
      const present = [...new Set(jobs.map(j => j.category).filter(Boolean))];
      const types = [...typeOrder.filter(t => present.includes(t)), ...present.filter(t => !typeOrder.includes(t)).sort()];
      typeChips.replaceChildren(h("span", { class: "muted small" }, "Type"),
        ...types.map(t => h("button", { class: "chip toggle", "aria-pressed": view.types.includes(t) ? "true" : "false", "data-focus": "type:" + t,
          onclick: () => {
            view.types = view.types.includes(t) ? view.types.filter(x => x !== t) : [...view.types, t];
            saveView(); update();
          } }, `${t} (${counts[t] || 0})`)),
        h("details", { class: "menu", open: typeOrderOpen, ontoggle: e => { typeOrderOpen = e.target.open; } },
          h("summary", { class: "small" }, "Type sort order"),
          h("ol", { class: "small" }, typeOrder.map((t, i) => h("li", null, t, " ",
            h("button", { class: "link", disabled: i === 0, "aria-label": `Move ${t} up`, "data-focus": "up:" + t, onclick: () => moveType(i, -1) }, "↑"), " ",
            h("button", { class: "link", disabled: i === typeOrder.length - 1, "aria-label": `Move ${t} down`, "data-focus": "down:" + t,
              onclick: () => moveType(i, 1) }, "↓"))))));

      const arrow = s => s.dir === 1 ? "↑" : "↓";
      sortChips.replaceChildren(h("span", { class: "muted small" }, "Sort"),
        ...(view.sort.length ? view.sort : [null]).map((s, i) => !s
          ? h("span", { class: "muted small" }, "None. Click a column header to sort; Shift-click adds a level.")
          : h("span", { class: "chip", draggable: "true", tabindex: 0, "data-focus": "sort:" + s.key,
          title: "Drag to change priority (or Alt + ← / →)",
          ondragstart: e => { e.dataTransfer.setData("text/plain", String(i)); e.dataTransfer.effectAllowed = "move"; },
          ondragover: e => e.preventDefault(),
          ondrop: e => { e.preventDefault(); moveSort(+e.dataTransfer.getData("text/plain"), i); },
          onkeydown: e => {
            if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); moveSort(i, i + (e.key === "ArrowLeft" ? -1 : 1)); }
          } },
          h("b", null, i + 1), ` ${SORTABLE[s.key]} ${arrow(s)}`,
          h("button", { class: "chip-x", "aria-label": `Remove ${SORTABLE[s.key]} sort`,
            onclick: () => { view.sort.splice(i, 1); saveView(); update(); } }, "×"))));

      const shown = sortJobs(jobs.filter(j => passes(j)), view.sort, typeOrder);
      const header = t => {
        const key = Object.keys(SORTABLE).find(k => SORTABLE[k] === t);
        if (!key) return h("th", null, t);
        const i = view.sort.findIndex(s => s.key === key), s = view.sort[i];
        return h("th", { "aria-sort": i === 0 ? (s.dir === 1 ? "ascending" : "descending") : null },
          h("button", { class: "sort", "data-focus": "th:" + key, title: "Click to sort; Shift-click to add a sort level",
            onclick: e => clickSort(key, e.shiftKey) }, t, s ? ` ${arrow(s)}${view.sort.length > 1 ? i + 1 : ""}` : ""));
      };

      const rows = shown.map(j => h("tr", null,
        h("td", null, j.is_new ? h("div", null, h("span", { class: "tag new" }, "NEW")) : "",
          j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener" }, j.title) : j.title,
          j.source !== "Jobly" || j.manual ? h("div", { class: "muted small" }, j.manual ? "added by hand" : j.source) : ""),
        h("td", null, j.company, j.location ? h("div", { class: "muted small" }, places(j.location)) : ""),
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
        h("td", null, !j.use_cv ? "" : !j.cv_ready
            ? h("span", { class: "tag warn", title: `roles/${j.use_cv} doesn't exist in the cv repo yet` }, "CV not ready")
            : [h("a", { href: j.use_cv_link, target: "_blank", rel: "noopener" }, j.use_cv),
               j.use_cv_language && j.use_cv_language !== "fi-first"
                 ? h("div", { class: "muted small", title: `The employer page and the PDF to send open in English (${j.use_cv_language})` },
                     j.use_cv_language === "en-only" ? "EN only" : "EN first") : ""],
          h("div", null, h("a", { class: "small", href: `#/prompt?job=${j.id}` }, "CV prompt")),
          h("div", null, h("a", { class: "small", href: `#/prompt?job=${j.id}&kind=email` }, "Email prompt")),
          h("div", null, h("a", { class: "small", href: `#/prep?job=${j.id}` }, "Prep"))),
        h("td", null, h("select", { class: "status", "data-status": j.status || "", "aria-label": `Status for ${j.title}`, onchange: async e => {
            await api(`/api/jobs/${j.id}/status`, { method: "POST", body: { status: e.target.value } });
            load();
          } }, h("option", { value: "" }, "—"), state.statuses.map(s => h("option", { value: s, selected: j.status === s }, s))))));

      tableArea.replaceChildren(
        h("p", { class: "muted small" }, `${shown.length} of ${jobs.length} jobs. ` +
          "Match and Blockers read the title, company and place, plus the ad text when there is one. " +
          "For Jobly jobs, “read full ad” fetches the ad page for a better check."),
        h("div", { class: "scroll" }, h("table", null,
          h("thead", null, h("tr", null, ["Job", "Company", "Posted", "Deadline", "Type", "Match", "Blockers", "Use CV", "Status"].map(header))),
          h("tbody", null, rows.length ? rows : h("tr", null, h("td", { colspan: 9, class: "empty" },
            jobs.length ? "No jobs match these filters." : "No jobs yet. Press “Check for new jobs” or add one by hand."))))));

      const again = focusKey && [...listArea.querySelectorAll("[data-focus]")].find(el => el.dataset.focus === focusKey);
      if (again) again.focus();
    }

    await load();
    poll();
  },
});
