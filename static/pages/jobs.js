import { api, h, register, store, message, getState } from "../core.js";
import { sourceAttrs, translateSwitch } from "../translate.js";
import { FINNISH, METHOD, feedbackControls } from "../finnish.js";
import { gettingStarted } from "../getting-started.js";
import { fitBadge, fitPanel, fitRing, fitScore, evaluate } from "../fit.js";

function places(text) {
  const p = (text || "").split(", ").filter(Boolean);
  return p.length > 3 ? h("span", { title: p.join(", ") }, p.slice(0, 3).join(", ") + ` +${p.length - 3} more`) : p.join(", ");
}

const daysText = d => d == null ? "" : d < 0 ? "closed" : d === 0 ? "closes today" : d === 1 ? "closes tomorrow" : `closes in ${d} days`;

// What the ad says about Finnish: the label as a tag, and the quote, method and "Was this right?" in a fold-out
function finnishInfo(j) {
  const f = j.finnish || { level: "unclear", evidence: [] };
  const [label, cls] = FINNISH[f.level] || FINNISH.unclear;
  const quote = (f.evidence || [])[0];
  const tag = h("span", { class: cls }, label);
  const more = h("details", { class: "job-finnish small" }, h("summary", null, `Why “${label}”?`),
    quote ? h("p", null, h("q", sourceAttrs(j), quote.length > 220 ? quote.slice(0, 217) + "…" : quote)) : h("p", { class: "muted" }, "The ad doesn't mention Finnish."),
    h("p", { class: "muted", title: f.explanation_en || "" }, METHOD[f.method] || ""),
    feedbackControls(f, j.id));
  return { tag, more };
}

// Sortable fields -> label. Sort is a list of levels, most important first: [{key, dir: 1 | -1}]
const SORTABLE = { deadline: "Deadline", match: "Match", posted: "Posted", category: "Type" };
const MAX_LEVELS = 3;
const defaultView = () => ({ sort: [{ key: "deadline", dir: 1 }, { key: "match", dir: -1 }],
  posted: "", deadline: "", hideExpired: true, types: [], minMatch: 0, finnish: "" });

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
  if (key === "match") return fitScore(j) || null;       // the same order as the rings show
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

// The fit ring (fit.js): the CV comparison's rating when there is a current one, otherwise the keyword match

// "Add a job": paste a link and JobDesk reads the ad's details for you to check, or fill them in by hand.
// prefill comes from the bookmarklet or the Home page's paste bar: {url, title, text} (text = what was selected on the page)
function addCard(state, onAdded, prefill) {
  const f = {};
  const field = (name, label, attrs = {}) =>
    h("label", { class: "field" }, label, f[name] = h(attrs.tag || "input", { name, ...attrs, tag: null }));
  const out = h("div", { role: "status" });
  const share = h("input", { type: "checkbox" });
  const link = h("input", { type: "url", name: "link", placeholder: "Paste a job link: JobDesk reads the ad for you", required: true,
    "aria-label": "Link to the job ad", style: "flex: 1 1 24rem; min-width: 0" });
  const readBtn = h("button", { type: "submit" }, "Read this link");
  const details = h("form", { class: "grid", hidden: true, onsubmit: save },
    field("url", "Link to the ad", { type: "url", placeholder: "https://…" }),
    field("title", "Job title", { required: true }),
    field("company", "Company"),
    field("location", "Place"),
    field("deadline", "Deadline", { type: "date" }),
    field("posted", "Posted", { type: "date" }),
    h("label", { class: "field" }, "Type",
      f.category = h("select", { name: "category" }, h("option", { value: "" }, "Work it out from the text"),
        state.job_types.map(t => h("option", { value: t }, t)))),
    h("label", { class: "field", style: "grid-column: 1 / -1" }, "Job description (for CV matching and the Finnish check)",
      f.ad_text = h("textarea", { name: "ad_text" })),
    h("label", { class: "check", style: "grid-column: 1 / -1" }, share,
      " Share this public ad with students in my field (otherwise only you see it)"),
    h("div", { class: "row", style: "grid-column: 1 / -1" }, h("button", { type: "submit" }, "Save to my jobs"),
      h("button", { type: "button", class: "secondary", onclick: () => { details.hidden = true; out.replaceChildren(); } }, "Cancel")));

  function fill(values) {
    for (const [k, el] of Object.entries(f)) if (values[k] != null) el.value = values[k];
    details.hidden = false;
    f.title.focus();
  }

  async function read(e) {
    e?.preventDefault();
    readBtn.disabled = true; readBtn.textContent = "Reading…";
    out.replaceChildren();
    try {
      const r = await api("/api/jobs/preview", { method: "POST", body: { url: link.value.trim() } });
      if (r.duplicate) {
        details.hidden = true;
        out.replaceChildren(message(`${r.reason} (“${r.duplicate.title}”${r.duplicate.status ? `, ${r.duplicate.status}` : ""})`));
      } else if (r.readable) {
        details.reset();
        fill({ ...r, ad_text: r.ad_text || prefill?.text || "" });
        out.replaceChildren(message(r.method === "jsonld"
          ? "Read from the ad's structured data. Check the details, then save."
          : "This page has no structured job data, so only the title and page text were read. Check and complete the details."));
      } else {
        details.reset();
        fill({ url: link.value.trim(), title: prefill?.title || "", ad_text: prefill?.text || "" });
        out.replaceChildren(message(r.reason, true));
      }
    } catch (err) {     // e.g. not a public address: still let the member type the details in
      details.reset();
      fill({ url: link.value.trim(), title: prefill?.title || "", ad_text: prefill?.text || "" });
      out.replaceChildren(message(err.message, true));
    }
    readBtn.disabled = false; readBtn.textContent = "Read this link";
  }

  async function save(e) {
    e.preventDefault();
    const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
    body.share = share.checked;
    try {
      const r = await api("/api/jobs", { method: "POST", body });
      details.reset(); details.hidden = true; link.value = "";
      out.replaceChildren(message(r.existing ? "It was already listed, so that one is now in your jobs."
        : share.checked ? "Saved and shared with students in your field." : "Saved to your jobs. Only you see it."));
      onAdded();
    } catch (err) { out.replaceChildren(message(err.message, true)); }
  }

  // The bookmarklet opens JobDesk on this page with the ad's address, title and any selected text
  const code = `javascript:(()=>{const t=String(getSelection()).slice(0,6000);` +
    `window.open(${JSON.stringify(location.origin + location.pathname)}+'#/myjobs?add='+encodeURIComponent(location.href)` +
    `+'&title='+encodeURIComponent(document.title.slice(0,200))+'&text='+encodeURIComponent(t))})()`;
  const card = h("section", { class: "card add-job" },
    h("h2", null, "Add a job"),
    h("form", { class: "add-job-bar", onsubmit: read }, link, readBtn),
    h("p", { class: "muted small" }, "Jobs you add are private: only you see them. Most job sites describe their ads in a " +
      "standard format that JobDesk reads; for others, check the details. Don't paste private contact details. ",
      h("button", { type: "button", class: "link", onclick: () => { details.reset(); fill({ url: link.value.trim() }); out.replaceChildren(); } },
        "Fill in by hand instead")),
    h("details", { class: "menu small" }, h("summary", null, "Add jobs from any site with one click (bookmarklet)"),
      h("p", { class: "small" }, "Drag this button to your bookmarks bar: ",
        h("a", { class: "btn secondary", href: code, onclick: e => e.preventDefault() }, "Save to JobDesk")),
      h("p", { class: "muted small" }, "On a job ad, click it. JobDesk opens with the link filled in. If the site can't be read " +
        "(for example LinkedIn, which needs a sign-in), select the ad's text before clicking, and it is copied into the description.")),
    out, details);

  if (prefill?.url) { link.value = prefill.url; read(); }
  return card;
}

// One page body for both views. mode "discover": the shared listings in the member's fields (Discover → Jobs).
// mode "mine": the jobs the member saved or added, with status, the fit check and the add form (My jobs → Saved jobs).
async function renderJobs(main, query, mode) {
  const state = await getState();
  const params = new URLSearchParams(query || "");
  if (mode === "discover" && params.get("add")) {      // old bookmarklets and links: adding is part of My jobs
    location.replace(`#/myjobs?${query}`);
    return;
  }
  const prefill = params.get("add") ? { url: params.get("add"), title: params.get("title") || "", text: params.get("text") || "" } : null;
  if (prefill) history.replaceState(null, "", "#/myjobs");
  const tab = mode;
  const status = h("span", { class: "muted small", role: "status" });
  const checkBtn = state.user.is_admin && mode === "discover" ? h("button", { class: "secondary", onclick: startCheck }, "Check for new jobs") : null;
  const classifyStatus = h("span", { class: "muted small", role: "status" });
  const classifyBtn = state.user.is_admin && mode === "discover" && state.llm.mode === "live"
    ? h("button", { class: "secondary", onclick: startClassify }, "Check Finnish requirements (AI)") : null;
  const fieldNames = state.fields.filter(f => state.user_fields.includes(f.id)).map(f => f.label_en);
  const listArea = h("div");
  const summary = h("div", { class: "job-summary", "aria-live": "polite" });
  const title = mode === "mine" ? h("h1", null, "Saved ", h("span", { class: "serif" }, "jobs"))
    : h("h1", null, "Jobs in ", h("span", { class: "serif" }, "your fields"));
  main.append(await gettingStarted(),
    h("div", { class: "page-head" },
      h("div", null, title,
        h("p", { class: "muted" }, mode === "mine"
          ? "The ads you saved or added, and where each application stands. Only you see them."
          : `Shared Finland-wide ads in ${fieldNames.join(", ") || "your fields"}. Change your fields under Profile. Save one to move it to your jobs.`)),
      h("div", { class: "page-head-side" }, status)),
    state.user.is_admin && mode === "discover" ? h("p", { class: "muted small" }, "Administrator view: jobs tagged “Only you” (industrial, construction, warehouse and IT) come from your own searches and are never shown to members.") : "",
    mode === "mine" ? addCard(state, load, prefill) : "",
    checkBtn || classifyBtn ? h("div", { class: "row" }, checkBtn || "", classifyBtn || "", classifyStatus) : "",
    summary, listArea);

  async function startCheck() {
    await api("/api/scrape", { method: "POST" });
    poll();
  }
  async function startClassify() {
    try { await api("/api/jobs/classify", { method: "POST", body: {} }); pollClassify(); }
    catch (err) { classifyStatus.textContent = err.message; }
  }
  async function pollClassify() {
    const c = await api("/api/jobs/classify");
    classifyBtn.disabled = c.running;
    classifyStatus.textContent = c.running
      ? `${c.message} (${c.done}/${c.total}). Only the ads' own text is sent to the AI.`
      : c.result ? `Done: ${c.result.classified} ads checked${c.result.failed ? `, ${c.result.failed} failed` : ""}; ${c.waiting} still waiting.`
      : `${c.waiting} ads with saved text are waiting to be checked.`;
    if (c.running) setTimeout(pollClassify, 3000);
    else if (c.result) load();
  }
  async function poll() {
    const s = await api("/api/scrape");
    checkBtn.disabled = s.running;
    status.textContent = s.running
      ? `${s.message} (${s.done}/${s.total} sources; Jobly asks for 10 s between pages)`
      : (s.result ? `Finished: ${s.result.found} jobs, ${s.result.new} new.` : "");
    if (s.running) setTimeout(poll, 3000);
    else if (s.result) {
      load();
      checkBtn.focus();
    }
  }

  const filters = { status: store("jobs.status") || "" };
  let view = loadView();          // sort + filters, saved as one preference
  let typeOrder = loadTypeOrder(state.job_types);
  let typeOrderOpen = false;
  let jobs = [];
  const saveView = () => store("jobs.view", JSON.stringify(view));

  async function load(restoreKey) {
    const data = await api("/api/jobs?scope=mine");
    jobs = data.jobs;
    const c = data.latest_check;
    const newCount = jobs.filter(j => j.is_new).length;
    if (mode === "discover" && !checkBtn?.disabled) status.textContent = c
      ? `Updated ${c.finished_at.replace("T", " ").slice(0, 16)} · ${newCount} new` + (c.error ? ` (error: ${c.error})` : "")
      : "Not checked yet.";
    draw(restoreKey);
  }

  // skip: leave one filter out (the Type chips count jobs that pass every other filter)
  const isMine = j => Boolean(j.private || j.status);
  const openFit = new Set(), fitNotes = {};      // jobs whose fit panel is open; messages for them
  function passes(j, skip) {
    const d = j.days_left;
    return ((tab === "mine") === isMine(j)) && (tab !== "mine" || !filters.status || (filters.status === "none" ? !j.status : j.status === filters.status)) &&
      (!view.posted || (j.posted && j.posted >= daysAgo(+view.posted))) &&
      (view.deadline !== "none" || !j.deadline) &&
      (!(+view.deadline) || (d != null && d >= 0 && d <= +view.deadline)) &&
      (!view.hideExpired || d == null || d >= 0) &&
      (skip === "type" || !view.types.length || view.types.includes(j.category)) &&
      (!view.minMatch || j.match.score >= view.minMatch) &&
      (view.finnish !== "hide-required" || j.finnish?.level !== "required") &&
      (view.finnish !== "open" || ["not_needed", "preferred"].includes(j.finnish?.level));
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
  // update() redraws the sort chips, Type chips and the list around them.
  const translation = translateSwitch(() => tableArea);
  const controls = h("div", { class: "job-filters" }), typeChips = h("div", { class: "row chip-row" }), sortChips = h("div", { class: "row chip-row" }), tableArea = h("div");
  listArea.replaceChildren(controls, typeChips, sortChips, tableArea);

  function draw(restoreKey) {
    const sel = (value, onchange, options, label) => h("select", { "aria-label": label, onchange: e => { onchange(e.target.value); update(); } },
      options.map(([v, t]) => h("option", { value: v, selected: value === v }, t)));
    const setView = key => v => { view[key] = v; saveView(); };
    const matchOut = h("output", null, view.minMatch);
    controls.replaceChildren(translation.element,
      h("div", { class: "row" },
      h("label", { class: "field" }, "Posted", sel(view.posted, setView("posted"),
        [["", "Any time"], ["3", "Last 3 days"], ["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"]])),
      h("label", { class: "field" }, "Deadline", sel(view.deadline, setView("deadline"),
        [["", "Any"], ["3", "Closing in 3 days"], ["7", "Closing in 7 days"], ["14", "Closing in 14 days"], ["none", "No deadline"]])),
      h("label", { class: "field" }, "Finnish", sel(view.finnish, setView("finnish"),
        [["", "Any"], ["hide-required", "Hide “Finnish required”"], ["open", "Only “not needed” or “an advantage”"]])),
      tab === "mine" ? h("label", { class: "field" }, "Status", sel(filters.status, v => { filters.status = v; store("jobs.status", v); },
        [["", "All"], ["none", "No status yet"], ...state.statuses.map(s => [s, s])])) : "",
      h("label", { class: "field match-filter" }, h("span", null, "Match at least ", matchOut), h("input", { type: "range", min: 0, max: 100, step: 5, value: view.minMatch,
        oninput: e => { view.minMatch = +e.target.value; matchOut.textContent = view.minMatch; saveView(); update(); } })),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: view.hideExpired,
        onchange: e => { view.hideExpired = e.target.checked; saveView(); update(); } }), "Hide expired"),
      h("button", { class: "secondary small", "data-focus": "reset", onclick: () => {
        view = defaultView(); filters.status = "";
        saveView(); store("jobs.status", ""); draw("reset");
      } }, "Reset")));
    update(restoreKey);
  }

  function statusSummary(mine) {
    if (tab !== "mine" || !mine.length) return [];
    const unsaved = mine.filter(j => !j.status).length;
    return [...state.statuses.map(st => [st, mine.filter(j => j.status === st).length]).filter(([, n]) => n)
      .map(([st, n]) => h("span", { class: "tag status", "data-status": st }, `${st} ${n}`)),
      unsaved ? h("span", { class: "tag" }, `No status yet ${unsaved}`) : ""];
  }

  function update(restoreKey) {
    // Re-rendering replaces the buttons, so put keyboard focus back on the same one
    const focusKey = restoreKey || (document.activeElement && document.activeElement.dataset.focus);

    const mine = jobs.filter(isMine);
    summary.replaceChildren(...statusSummary(mine));

    const counts = {};
    for (const j of jobs) if (j.category && passes(j, "type")) counts[j.category] = (counts[j.category] || 0) + 1;
    const present = [...new Set(jobs.filter(j => (tab === "mine") === isMine(j)).map(j => j.category).filter(Boolean))];
    const types = [...typeOrder.filter(t => present.includes(t)), ...present.filter(t => !typeOrder.includes(t)).sort()];
    typeChips.replaceChildren(h("span", { class: "chip-label" }, "Type"),
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
    sortChips.replaceChildren(h("span", { class: "chip-label" }, "Sort by"),
      ...Object.entries(SORTABLE).map(([key, label]) => {
        const i = view.sort.findIndex(s => s.key === key), s = view.sort[i];
        return h("button", { class: "chip toggle", "aria-pressed": s ? "true" : "false", "data-focus": "sortkey:" + key,
          title: "Click to sort; click again to reverse or remove; Shift-click to add a sort level",
          onclick: e => clickSort(key, e.shiftKey) }, label, s ? ` ${arrow(s)}${view.sort.length > 1 ? ` ${i + 1}` : ""}` : "");
      }),
      view.sort.length > 1 ? h("span", { class: "chip-label" }, "Priority") : "",
      ...(view.sort.length > 1 ? view.sort.map((s, i) => h("span", { class: "chip", draggable: "true", tabindex: 0, "data-focus": "sort:" + s.key,
        title: "Drag to change priority (or Alt + ← / →)",
        ondragstart: e => { e.dataTransfer.setData("text/plain", String(i)); e.dataTransfer.effectAllowed = "move"; },
        ondragover: e => e.preventDefault(),
        ondrop: e => { e.preventDefault(); moveSort(+e.dataTransfer.getData("text/plain"), i); },
        onkeydown: e => {
          if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); moveSort(i, i + (e.key === "ArrowLeft" ? -1 : 1)); }
        } },
        h("b", null, i + 1), ` ${SORTABLE[s.key]} ${arrow(s)}`,
        h("button", { class: "chip-x", "aria-label": `Remove ${SORTABLE[s.key]} sort`,
          onclick: () => { view.sort.splice(i, 1); saveView(); update(); } }, "×"))) : []));

    const shown = sortJobs(jobs.filter(j => passes(j)), view.sort, typeOrder);

    const fitActions = j => {
      const toggle = label => h("button", { class: "link small", "aria-expanded": openFit.has(j.id) ? "true" : "false",
        "data-focus": `fit:${j.id}`, onclick: () => { openFit.has(j.id) ? openFit.delete(j.id) : openFit.add(j.id); update(`fit:${j.id}`); } }, label);
      if (j.fit) return [fitBadge(j.fit), toggle(openFit.has(j.id) ? "Hide" : "Why?")];
      if (!j.status || j.status === "Saved") return [h("button", { class: "accent small", "data-focus": `fit:${j.id}`,
        title: "Move to Shortlisted and compare this job with your CV",
        onclick: async e => {
          e.target.disabled = true; e.target.textContent = "Checking…";
          try { const r = await evaluate(j.id, true); fitNotes[j.id] = r.message || ""; }
          catch (err) { fitNotes[j.id] = err.message; }
          openFit.add(j.id); load(`fit:${j.id}`);
        } }, "Shortlist")];
      return [toggle(openFit.has(j.id) ? "Hide fit" : "Check fit")];
    };

    const jobCard = j => {
      const fin = finnishInfo(j);
      const words = [];
      for (const w of j.match.words || []) if (words.length < 3 && !words.some(x => x.slice(0, 5) === w.slice(0, 5))) words.push(w);
      const soon = j.days_left != null && j.days_left >= 0 && j.days_left <= 3 && (!j.status || ["Saved", "Shortlisted"].includes(j.status));
      const meta = [j.company, j.location ? places(j.location) : "", j.posted ? `posted ${j.posted}` : "",
        j.deadline ? h("span", { class: soon ? "overdue" : "" }, `${j.deadline} · ${daysText(j.days_left)}`) : ""].filter(Boolean);
      const actions = tab === "discover"
        ? [h("button", { class: "secondary", "data-focus": `save:${j.id}`, "aria-label": `Save ${j.title} to my jobs`,
            onclick: async () => { await api(`/api/jobs/${j.id}/status`, { method: "POST", body: { status: "Saved" } }); load(`save:${j.id}`); } }, "Save")]
        : [h("select", { class: "status", "data-status": j.status || "", "data-focus": `status:${j.id}`, "aria-label": `Status for ${j.title}`, onchange: async e => {
            await api(`/api/jobs/${j.id}/status`, { method: "POST", body: { status: e.target.value } });
            load(`status:${j.id}`);
          } }, h("option", { value: "" }, "No status"), state.statuses.map(s => h("option", { value: s, selected: j.status === s }, s))),
          ...fitActions(j),
          j.status && j.status !== "Rejected" ? h("a", { class: "btn small", href: `#/prepare?job=${j.id}` }, "Prepare") : ""];
      return h("article", { class: "job-card" + (j.status === "Rejected" ? " is-rejected" : "") },
        fitRing(j),
        h("div", { class: "job-main" },
          h("h3", null, j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener", ...sourceAttrs(j) }, j.title)
            : h("span", sourceAttrs(j), j.title)),
          h("p", { class: "job-meta muted" }, ...meta.flatMap((m, i) => i ? [" · ", m] : [m])),
          h("p", { class: "job-tags" },
            j.is_new ? h("span", { class: "tag new" }, "New") : "",
            j.personal || j.private ? h("span", { class: "tag" }, "Only you") : "",
            j.category ? h("span", { class: "tag" }, j.category) : "",
            words.length ? h("span", { class: "tag strength", title: j.match.slug ? `Matched with ${j.match.slug}` : "" }, `✓ ${words.join(", ")}`) : "",
            fin.tag),
          fin.more,
          h("p", { class: "job-source muted small" },
            j.source === "Community" ? "Shared by a member" : j.manual ? "Added by hand" : j.source || "",
            j.use_cv && j.cv_ready ? ` · matched with ${j.use_cv} (${j.use_cv_language.toUpperCase()})` : "",
            !j.has_ad_text && j.url ? [" · ", h("button", { class: "link small", "data-focus": `fetch:${j.id}`, onclick: async e => {
              e.target.disabled = true; e.target.textContent = "reading…";
              try { await api(`/api/jobs/${j.id}/fetch`, { method: "POST" }); load(`fetch:${j.id}`); }
              catch (err) {
                e.target.disabled = false;
                e.target.textContent = `Retry: ${err.message}`;
                e.target.focus();
              }
            } }, "read the full ad to improve matching")] : "")),
        h("div", { class: "job-actions" }, ...actions.filter(Boolean)),
        tab === "mine" && openFit.has(j.id) ? h("div", { class: "job-fit" }, fitPanel(j.id, () => load(`fit:${j.id}`), fitNotes[j.id])) : "");
    };

    tableArea.replaceChildren(
      h("p", { class: "muted small job-count" }, `${shown.length} of ${jobs.filter(j => (tab === "mine") === isMine(j)).length} jobs. ` +
        "The ring shows your fit with your CV when you've shortlisted the job, otherwise how many of its words match your CV. " +
        "The Finnish tag is what the ad says about Finnish; open it for the sentence it's based on."),
      shown.length ? h("div", { class: "job-list" }, shown.map(jobCard))
        : h("div", { class: "empty-state" },
            h("p", { class: "empty-title" }, tab === "mine" && !jobs.some(isMine) ? "No saved jobs yet" : "Nothing matches these filters"),
            h("p", null, tab === "mine" && !jobs.some(isMine) ? "Paste a job link above, or save one from Discover."
              : jobs.length ? "Loosen a filter, or press Reset." : "No jobs in your fields yet. Add one by link under My jobs.")));

    const focusTargets = [...listArea.querySelectorAll("[data-focus]")];
    const again = focusKey && focusTargets.find(el => el.dataset.focus === focusKey);
    const fetchFallback = focusKey?.startsWith("fetch:")
      ? focusTargets.find(el => el.dataset.focus === `status:${focusKey.slice("fetch:".length)}`)
      : null;
    (again || fetchFallback)?.focus();
    translation.apply();      // swaps in English titles when the switch is on English
  }

  await load();
  if (checkBtn) poll();
  if (classifyBtn) pollClassify();
}

// Discover (id "jobs") is pages/discover.js, which searches on the server; this page lists the member's own jobs
register({ id: "myjobs", title: "Saved jobs", render: (main, query) => renderJobs(main, query, "mine") });
