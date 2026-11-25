// Discover: search every open job a member can see (GET /api/search). The filters live in the address
// (#/jobs?q=nurse&level=internship&no_finnish=1&page=2), so a search can be bookmarked, shared or reloaded.
// "Finnish not required" and "Summer jobs" sit up front; the rest folds out under "More filters".
import { api, getState, h, message, register } from "../core.js";
import { FINNISH } from "../finnish.js";
import { sourceAttrs, translateSwitch } from "../translate.js";
import { label, LABELS, salaryText } from "../labels.js";

// "field" is special: absent means "my fields" (the server's default), field=all means every field
const LIST_KEYS = ["level", "type", "mode", "sector"];
const FLAG_KEYS = ["no_finnish", "paid", "with_studies"];

function readFilters(query) {
  const p = new URLSearchParams(query || "");
  const f = { q: p.get("q") || "", region: p.get("region") || "", sort: p.get("sort") || "newest", page: Number(p.get("page")) || 1 };
  for (const key of LIST_KEYS) f[key] = (p.get(key) || "").split(",").filter(Boolean);
  for (const key of FLAG_KEYS) f[key] = p.get(key) === "1";
  f.field = !p.has("field") ? null : p.get("field") === "all" ? [] : p.get("field").split(",").filter(Boolean);
  return f;
}

function toQuery(f) {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.field) p.set("field", f.field.length ? f.field.join(",") : "all");
  for (const key of LIST_KEYS) if (f[key].length) p.set(key, f[key].join(","));
  for (const key of FLAG_KEYS) if (f[key]) p.set(key, "1");
  if (f.region) p.set("region", f.region);
  if (f.sort !== "newest") p.set("sort", f.sort);
  if (f.page > 1) p.set("page", String(f.page));
  return p.toString();
}

const daysLeft = iso => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((new Date(+m[1], +m[2] - 1, +m[3]) - today) / 86400000);
};
const closes = iso => {
  const d = daysLeft(iso);
  return d == null ? "" : d === 0 ? "closes today" : d === 1 ? "closes tomorrow" : d < 0 ? "closed" : `closes ${iso} (${d} days)`;
};

function finnishTag(j) {
  if (j.lang_fi === "unclear" && j.finnish_not_required) return h("span", { class: "tag new" }, "No Finnish mentioned (English ad)");
  const [text, cls] = FINNISH[j.lang_fi] || FINNISH.unclear;
  return h("span", { class: cls }, text);
}

function jobCard(j, onSave) {
  const place = j.municipality || j.location || (j.work_mode === "remote" ? "Remote" : "");
  const meta = [j.company, place, j.deadline ? closes(j.deadline) : ""].filter(Boolean);
  const pay = salaryText(j);
  const saved = !!j.status;
  return h("article", { class: "job-card discover-card" },
    h("div", { class: "job-main" },
      h("h3", null, j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener", ...sourceAttrs(j) }, j.title)
        : h("span", sourceAttrs(j), j.title)),
      h("p", { class: "job-meta muted" }, meta.join(" · ")),
      h("p", { class: "job-tags" },
        j.is_new ? h("span", { class: "tag new" }, "New") : "",
        ...j.employment_types.filter(t => t === "summer").map(t => h("span", { class: "tag warn" }, label("employment", t))),
        ...j.levels.map(l => h("span", { class: "tag" }, label("level", l))),
        ...j.employment_types.filter(t => t !== "summer").map(t => h("span", { class: "tag" }, label("employment", t))),
        j.work_mode ? h("span", { class: "tag" }, label("mode", j.work_mode)) : "",
        finnishTag(j),
        pay ? h("span", { class: "tag" }, pay) : "",
        j.paid === 0 ? h("span", { class: "tag bad" }, "Unpaid") : "",
        j.internship_credits ? h("span", { class: "tag" }, `${j.internship_credits} op / ECTS`) : "",
        j.combinable_with_studies ? h("span", { class: "tag" }, "Alongside studies") : ""),
      j.permits.length ? h("p", { class: "muted small" }, j.permits.map(p => label("permit", p)).join(" · ")) : "",
      h("p", { class: "job-source muted small" },
        j.source === "Employer" ? "Posted by the employer" : j.source === "Community" ? "Shared by a member" : `From ${j.source}`,
        j.attribution ? ` ${j.attribution}` : "",
        j.url ? [" · ", h("a", { href: j.url, target: "_blank", rel: "noopener" }, "Open the original ad")] : "")),
    h("div", { class: "job-actions" },
      saved ? h("a", { class: "btn secondary small", href: "#/myjobs" }, j.status === "Saved" ? "Saved" : j.status)
        : h("button", { class: "secondary", "aria-label": `Save ${j.title} to my jobs`, onclick: e => onSave(j, e.target) }, "Save")));
}

async function renderDiscover(main, query) {
  if (new URLSearchParams(query || "").get("add")) {      // old bookmarklets and links: adding is part of My jobs
    location.replace(`#/myjobs?${query}`);
    return;
  }
  const state = await getState();
  let f = readFilters(query);
  const results = h("div", { "aria-live": "polite", "aria-busy": "false" });
  const translation = translateSwitch(() => results);      // Original / English titles, translated on the device
  const count = h("p", { class: "muted small job-count", role: "status" });
  const checkStatus = h("span", { class: "muted small", role: "status" });

  // Keep the address in step with the filters without reloading the page (so typing keeps focus)
  function apply(changes, keepPage = false) {
    f = { ...f, ...changes, page: keepPage ? (changes.page || f.page) : 1 };
    history.replaceState(null, "", `#/jobs${toQuery(f) ? `?${toQuery(f)}` : ""}`);
    syncControls();
    load();
  }

  const search = h("input", { type: "search", name: "q", value: f.q, placeholder: "Job title, skill or employer, in English or Finnish",
    "aria-label": "Search jobs", autocomplete: "off" });
  const region = h("select", { "aria-label": "Region", onchange: () => apply({ region: region.value }) },
    h("option", { value: "" }, "All of Finland"),
    ...state.regions.map(r => h("option", { value: r.code, selected: f.region === r.code }, r.en === r.fi ? r.en : `${r.en} (${r.fi})`)));
  const searchForm = h("form", { class: "discover-search", role: "search", onsubmit: e => { e.preventDefault(); apply({ q: search.value }); } },
    search, region, h("button", { type: "submit" }, "Search"));

  // Quick toggles: the two most asked-for filters, plus the student levels
  const toggles = [
    ["no_finnish", "Finnish not required", () => f.no_finnish, () => apply({ no_finnish: !f.no_finnish })],
    ["summer", "Summer jobs", () => f.type.includes("summer"), () => apply({ type: f.type.includes("summer") ? f.type.filter(t => t !== "summer") : [...f.type, "summer"] })],
    ["internship", "Internships", () => f.level.includes("internship"), () => apply({ level: toggle(f.level, "internship") })],
    ["thesis", "Thesis", () => f.level.includes("thesis"), () => apply({ level: toggle(f.level, "thesis") })],
    ["entry", "Entry level", () => f.level.includes("entry"), () => apply({ level: toggle(f.level, "entry") })],
    ["remote", "Remote", () => f.mode.includes("remote"), () => apply({ mode: toggle(f.mode, "remote") })],
  ];
  const toggle = (list, value) => list.includes(value) ? list.filter(v => v !== value) : [...list, value];
  const toggleButtons = toggles.map(([id, text, on, click]) =>
    h("button", { type: "button", class: "chip toggle" + (id === "no_finnish" ? " toggle-key" : ""), "data-toggle": id,
      "aria-pressed": on() ? "true" : "false", onclick: click }, text, h("span", { class: "toggle-count" })));

  const checks = (key, group, codes) => h("fieldset", null, h("legend", null, group),
    ...codes.map(([code, text]) => h("label", { class: "check" },
      h("input", { type: "checkbox", value: code, "data-key": key, checked: f[key].includes(code),
        onchange: e => apply({ [key]: e.target.checked ? [...f[key], code] : f[key].filter(v => v !== code) }) }), ` ${text}`)));
  const pairs = group => Object.entries(LABELS[group]).map(([code, [en]]) => [code, en]);
  // Every career field can be searched; with none ticked, all are. The member's own fields are ticked
  // until they change the selection (the server says which fields it used: defaultFields).
  let defaultFields = [];
  const shownFields = () => f.field ?? defaultFields;
  const fieldNote = h("p", { class: "muted small" });
  const fieldChecks = h("fieldset", { class: "discover-fields" }, h("legend", null, "Career field"), fieldNote,
    h("div", { class: "field-checks" }, ...state.fields.map(x => h("label", { class: "check" },
      h("input", { type: "checkbox", value: x.id, "data-field": "1", onchange: e => {
        const now = shownFields();
        apply({ field: e.target.checked ? [...now, x.id] : now.filter(v => v !== x.id) });
      } }), ` ${x.label_en}`, h("span", { class: "toggle-count", "data-field-count": x.id })))));
  const flag = (key, text) => h("label", { class: "check" }, h("input", { type: "checkbox", "data-flag": key, checked: f[key],
    onchange: e => apply({ [key]: e.target.checked }) }), ` ${text}`);
  const sort = h("select", { "aria-label": "Sort", onchange: () => apply({ sort: sort.value }) },
    h("option", { value: "newest", selected: f.sort === "newest" }, "Newest first"),
    h("option", { value: "deadline", selected: f.sort === "deadline" }, "Deadline soonest"));
  const more = h("details", { class: "discover-more" },
    h("summary", null, "More filters"),
    h("div", { class: "discover-filters" },
      fieldChecks,
      checks("level", "Level", pairs("level")),
      checks("type", "Type", pairs("employment")),
      checks("mode", "Work mode", pairs("mode")),
      checks("sector", "Employer", pairs("sector")),
      h("fieldset", null, h("legend", null, "For students"),
        flag("paid", "Only ads that say they're paid"), flag("with_studies", "Can be done alongside studies"))),
    h("div", { class: "row" }, h("label", { class: "field inline" }, "Sort ", sort),
      h("button", { type: "button", class: "secondary small", onclick: () => apply({ q: "", region: "", sort: "newest", field: [],
        ...Object.fromEntries(LIST_KEYS.map(k => [k, []])), ...Object.fromEntries(FLAG_KEYS.map(k => [k, false])) }) }, "Clear all filters")));

  function syncControls() {
    search.value = f.q;
    region.value = f.region;
    sort.value = f.sort;
    toggleButtons.forEach((b, i) => b.setAttribute("aria-pressed", toggles[i][2]() ? "true" : "false"));
    for (const input of more.querySelectorAll("input[data-key]")) input.checked = f[input.dataset.key].includes(input.value);
    for (const input of more.querySelectorAll("input[data-flag]")) input.checked = f[input.dataset.flag];
    const ticked = shownFields();
    for (const input of more.querySelectorAll("input[data-field]")) input.checked = ticked.includes(input.value);
    fieldNote.textContent = !ticked.length ? "All fields. Tick some to narrow the search."
      : f.field === null ? "Your fields from Profile. Untick them to search every field." : "";
  }

  async function save(job, button) {
    button.disabled = true;
    try {
      await api(`/api/jobs/${job.id}/status`, { method: "POST", body: { status: "Saved" } });
      button.replaceWith(h("a", { class: "btn secondary small", href: "#/myjobs" }, "Saved"));
    } catch (error) {
      button.disabled = false;
      results.prepend(message(error.message, true));
    }
  }

  let request = 0;
  async function load() {
    const mine = ++request;
    results.setAttribute("aria-busy", "true");
    let data;
    try { data = await api(`/api/search?${toQuery(f)}`); }
    catch (error) {
      results.replaceChildren(message(error.message, true));
      results.setAttribute("aria-busy", "false");
      return;
    }
    if (mine !== request) return;             // a newer search has started
    results.setAttribute("aria-busy", "false");
    defaultFields = data.filters.field_default ? data.filters.field : [];
    syncControls();
    for (const el of more.querySelectorAll("[data-field-count]")) el.textContent = ` ${data.facets.field[el.dataset.fieldCount] || 0}`;
    const facet = { no_finnish: data.facets.no_finnish, summer: data.facets.summer, internship: data.facets.level.internship,
      thesis: data.facets.level.thesis, entry: data.facets.level.entry, remote: data.facets.mode.remote };
    toggleButtons.forEach(b => {
      const n = facet[b.dataset.toggle] || 0;
      b.querySelector(".toggle-count").textContent = b.getAttribute("aria-pressed") === "true" ? "" : ` ${n}`;
    });
    count.textContent = data.total === 1 ? "1 job" : `${data.total} jobs` + (data.pages > 1 ? ` · page ${data.page} of ${data.pages}` : "");
    const c = data.latest_check;
    if (c) checkStatus.textContent = `Updated ${c.finished_at?.replace("T", " ").slice(0, 16) || ""}`;
    const pager = data.pages > 1 ? h("nav", { class: "row pager", "aria-label": "Pages" },
      h("button", { type: "button", class: "secondary small", disabled: data.page <= 1,
        onclick: () => { apply({ page: data.page - 1 }, true); main.scrollIntoView(); } }, "Previous"),
      h("span", { class: "muted small" }, `Page ${data.page} of ${data.pages}`),
      h("button", { type: "button", class: "secondary small", disabled: data.page >= data.pages,
        onclick: () => { apply({ page: data.page + 1 }, true); main.scrollIntoView(); } }, "Next")) : "";
    results.replaceChildren(...(data.jobs.length
      ? [h("div", { class: "job-list" }, data.jobs.map(j => jobCard(j, save))), pager]
      : [h("div", { class: "empty-state" }, h("p", { class: "empty-title" }, "No jobs match"),
          h("p", null, f.no_finnish ? "Few ads say outright that Finnish isn't needed. Try without “Finnish not required”, or a wider search."
            : "Try fewer filters or other words. Searches find word starts in English and Finnish."))]));
    translation.apply();
  }

  // Administrators can start a job check now (the timer runs one twice a day)
  const checkBtn = state.user.is_admin ? h("button", { type: "button", class: "secondary small", onclick: async () => {
    try { await api("/api/scrape", { method: "POST" }); pollCheck(); }
    catch (error) { checkStatus.textContent = error.message; }
  } }, "Check for new jobs") : null;
  async function pollCheck() {
    const s = await api("/api/scrape");
    checkBtn.disabled = s.running;
    if (s.running) {
      checkStatus.textContent = `${s.message} (${s.done}/${s.total} sources)`;
      setTimeout(pollCheck, 3000);
    } else if (s.result) {
      checkStatus.textContent = `Finished: ${s.result.found} jobs, ${s.result.new} new.`;
      load();
    }
  }

  const summerView = f.type.length === 1 && f.type[0] === "summer";
  main.append(
    h("div", { class: "page-head" },
      h("div", null, summerView ? h("h1", null, "Summer ", h("span", { class: "serif" }, "jobs"))
        : h("h1", null, "Find ", h("span", { class: "serif" }, "jobs")),
        h("p", { class: "muted" }, "Open jobs, internships, summer jobs and thesis positions across Finland, from public job feeds and employers. Save one to track it under My jobs.")),
      h("div", { class: "page-head-side" }, checkStatus, checkBtn || "")),
    searchForm,
    h("div", { class: "row chip-row discover-toggles", role: "group", "aria-label": "Quick filters" }, ...toggleButtons),
    more, translation.element, count, results);
  await load();
}

register({ id: "jobs", title: "Discover", render: (main, query) => renderDiscover(main, query) });
