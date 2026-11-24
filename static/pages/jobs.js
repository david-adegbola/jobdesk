import { api, h, register, store, message, getState } from "../core.js";
import { sourceAttrs, translateSwitch } from "../translate.js";
import { FINNISH, METHOD, feedbackControls } from "../finnish.js";
import { gettingStarted } from "../getting-started.js";
import { fitBadge, fitPanel, evaluate } from "../fit.js";

function places(text) {
  const p = (text || "").split(", ").filter(Boolean);
  return p.length > 3 ? h("span", { title: p.join(", ") }, p.slice(0, 3).join(", ") + ` +${p.length - 3} more`) : p.join(", ");
}

const daysText = d => d == null ? "" : d < 0 ? "closed" : d === 0 ? "today" : `${d} d`;

function finnishCell(j) {
  const f = j.finnish || { level: "unclear", evidence: [] };
  const [label, cls] = FINNISH[f.level] || FINNISH.unclear;
  const quote = (f.evidence || [])[0];
  return h("td", null, h("span", { class: cls }, label),
    quote ? h("div", { class: "small" }, h("q", sourceAttrs(j), quote.length > 160 ? quote.slice(0, 157) + "…" : quote)) : "",
    h("div", { class: "muted small", title: f.explanation_en || "" }, METHOD[f.method] || ""),
    feedbackControls(f, j.id));
}

// Sortable columns -> header text. Sort is a list of levels, most important first: [{key, dir: 1 | -1}]
const SORTABLE = { posted: "Posted", deadline: "Deadline", category: "Type", match: "Match" };
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

// "Add a job": paste a link and JobDesk reads the ad's details for you to check, or fill them in by hand.
// prefill comes from the bookmarklet: {url, title, text} (text = what was selected on the page)
function addCard(state, onAdded, prefill) {
  const f = {};
  const field = (name, label, attrs = {}) =>
    h("label", { class: "field" }, label, f[name] = h(attrs.tag || "input", { name, ...attrs, tag: null }));
  const out = h("div", { role: "status" });
  const share = h("input", { type: "checkbox" });
  const link = h("input", { type: "url", name: "link", placeholder: "https://…", required: true, "aria-label": "Link to the job ad",
    style: "flex: 1 1 24rem; min-width: 0" });
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
    `window.open(${JSON.stringify(location.origin + location.pathname)}+'#/jobs?add='+encodeURIComponent(location.href)` +
    `+'&title='+encodeURIComponent(document.title.slice(0,200))+'&text='+encodeURIComponent(t))})()`;
  const card = h("section", { class: "card" },
    h("h2", null, "Add a job"),
    h("form", { class: "row", onsubmit: read }, link, readBtn,
      h("button", { type: "button", class: "link", onclick: () => { details.reset(); fill({ url: link.value.trim() }); out.replaceChildren(); } },
        "Fill in by hand")),
    h("p", { class: "muted small" }, "Jobs you add are private: only you see them. Most job sites describe their ads in a " +
      "standard format that JobDesk reads; for others, check the details. Don't paste private contact details."),
    h("details", { class: "menu small" }, h("summary", null, "Add jobs from any site with one click (bookmarklet)"),
      h("p", { class: "small" }, "Drag this button to your bookmarks bar: ",
        h("a", { class: "btn secondary", href: code, onclick: e => e.preventDefault() }, "Save to JobDesk")),
      h("p", { class: "muted small" }, "On a job ad, click it. JobDesk opens with the link filled in. If the site can't be read " +
        "(for example LinkedIn, which needs a sign-in), select the ad's text before clicking, and it is copied into the description.")),
    out, details);

  if (prefill?.url) { link.value = prefill.url; read(); }
  return card;
}

register({
  id: "jobs", title: "Jobs",
  async render(main, query) {
    const state = await getState();
    const params = new URLSearchParams(query || "");
    const prefill = params.get("add") ? { url: params.get("add"), title: params.get("title") || "", text: params.get("text") || "" } : null;
    if (prefill) history.replaceState(null, "", "#/jobs");
    const status = h("span", { class: "muted", role: "status" });
    const checkBtn = state.user.is_admin ? h("button", { onclick: startCheck }, "Check for new jobs") : null;
    const classifyStatus = h("span", { class: "muted small", role: "status" });
    const classifyBtn = state.user.is_admin && state.llm.mode === "live"
      ? h("button", { class: "secondary", onclick: startClassify }, "Check Finnish requirements (AI)") : null;
    const fieldNames = state.fields.filter(f => state.user_fields.includes(f.id)).map(f => f.label_en);
    const listArea = h("div");
    let tab = prefill ? "mine" : (store("jobs.tab") || "mine");
    const tabs = h("div", { class: "row", role: "group", "aria-label": "Which jobs" });
    const summary = h("p", { class: "muted small" });
    main.append(await gettingStarted(), h("h1", null, "Jobs"),
      h("p", { class: "muted" }, "My jobs: the ads you've saved or added, and where each application stands. " +
        `Discover: shared Finland-wide ads in your fields (${fieldNames.join(", ")}; change them on the Account page). ` +
        "Your jobs, applications and CV matches are private to your account."),
      state.user.is_admin ? h("p", { class: "muted small" }, "Administrator view: jobs tagged “Only you” (industrial, construction, warehouse and IT) come from your own searches and are never shown to members.") : "",
      addCard(state, load, prefill),
      h("div", { class: "row" }, checkBtn || "", status),
      classifyBtn ? h("div", { class: "row" }, classifyBtn, classifyStatus) : "",
      tabs, summary, listArea);

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
    let view = loadView();          // sort + column filters, saved as one preference
    let typeOrder = loadTypeOrder(state.job_types);
    let typeOrderOpen = false;
    let jobs = [];
    const saveView = () => store("jobs.view", JSON.stringify(view));

    async function load(restoreKey) {
      const data = await api("/api/jobs");
      jobs = data.jobs;
      const c = data.latest_check;
      const newCount = jobs.filter(j => j.is_new).length;
      if (!checkBtn?.disabled) status.textContent = c
        ? `Last checked: ${c.finished_at.replace("T", " ")}, ${newCount} new` + (c.error ? ` (error: ${c.error})` : "")
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
    // update() redraws the sort chips, Type chips and table around them.
    const translation = translateSwitch(() => tableArea);
    const controls = h("div"), typeChips = h("div", { class: "row" }), sortChips = h("div", { class: "row" }), tableArea = h("div");
    listArea.replaceChildren(controls, typeChips, sortChips, tableArea);

    function draw(restoreKey) {
      const sel = (value, onchange, options) => h("select", { onchange: e => { onchange(e.target.value); update(); } },
        options.map(([v, t]) => h("option", { value: v, selected: value === v }, t)));
      const setView = key => v => { view[key] = v; saveView(); };
      const matchOut = h("output", null, view.minMatch);
      controls.replaceChildren(translation.element,
        h("div", { class: "row" },
        h("label", { class: "check" }, "Posted ", sel(view.posted, setView("posted"),
          [["", "Any time"], ["3", "Last 3 days"], ["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"]])),
        h("label", { class: "check" }, "Deadline ", sel(view.deadline, setView("deadline"),
          [["", "Any"], ["3", "Closing in 3 days"], ["7", "Closing in 7 days"], ["14", "Closing in 14 days"], ["none", "No deadline"]])),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: view.hideExpired,
          onchange: e => { view.hideExpired = e.target.checked; saveView(); update(); } }), "Hide expired"),
        h("label", { class: "check" }, "Match at least ", h("input", { type: "range", min: 0, max: 100, step: 5, value: view.minMatch,
          oninput: e => { view.minMatch = +e.target.value; matchOut.textContent = view.minMatch; saveView(); update(); } }), matchOut),
        h("label", { class: "check" }, "Finnish ", sel(view.finnish, setView("finnish"),
          [["", "Any"], ["hide-required", "Hide “Finnish required”"], ["open", "Only “not needed” or “an advantage”"]])),
        h("label", { class: "check" }, "Status ", sel(filters.status, v => { filters.status = v; store("jobs.status", v); },
          [["", "All"], ...state.statuses.map(s => [s, s])])),
        h("button", { class: "secondary", "data-focus": "reset", onclick: () => {
          view = defaultView(); filters.status = "";
          saveView(); store("jobs.status", ""); draw("reset");
        } }, "Reset")));
      update(restoreKey);
    }

    function update(restoreKey) {
      // Re-rendering replaces the buttons, so put keyboard focus back on the same one
      const focusKey = restoreKey || (document.activeElement && document.activeElement.dataset.focus);

      const mine = jobs.filter(isMine);
      tabs.replaceChildren(...[["mine", `My jobs (${mine.length})`], ["discover", `Discover (${jobs.length - mine.length})`]].map(([id, label]) =>
        h("button", { class: "chip toggle", "aria-pressed": tab === id ? "true" : "false", "data-focus": "tab:" + id,
          onclick: () => { tab = id; store("jobs.tab", id); update(); } }, label)));
      const byStatus = state.statuses.map(st => [st, mine.filter(j => j.status === st).length]).filter(([, n]) => n);
      const unsaved = mine.filter(j => !j.status).length;
      summary.textContent = tab !== "mine" ? "Save an ad to move it to My jobs." : !mine.length ? "" :
        [...byStatus.map(([st, n]) => `${st}: ${n}`), unsaved ? `No status yet: ${unsaved}` : ""].filter(Boolean).join(" · ");

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

      const fitCell = j => {
        if (tab !== "mine") return "";
        const toggle = label => h("button", { class: "link small", "aria-expanded": openFit.has(j.id) ? "true" : "false",
          "data-focus": `fit:${j.id}`, onclick: () => { openFit.has(j.id) ? openFit.delete(j.id) : openFit.add(j.id); update(`fit:${j.id}`); } }, label);
        if (j.fit) return h("div", null, fitBadge(j.fit), " ", toggle(openFit.has(j.id) ? "Hide" : "Why?"));
        if (!j.status || j.status === "Saved") return h("div", null, h("button", { class: "secondary small", "data-focus": `fit:${j.id}`,
          title: "Move to Shortlisted and compare this job with your CV",
          onclick: async e => {
            e.target.disabled = true;
            try { const r = await evaluate(j.id, true); fitNotes[j.id] = r.message || ""; }
            catch (err) { fitNotes[j.id] = err.message; }
            openFit.add(j.id); load(`fit:${j.id}`);
          } }, "Shortlist"));
        return h("div", null, toggle(openFit.has(j.id) ? "Hide fit" : "Check fit"));
      };
      const rows = shown.flatMap(j => [h("tr", null,
        h("td", null, j.is_new ? h("div", null, h("span", { class: "tag new" }, "NEW")) : "",
          j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener", ...sourceAttrs(j) }, j.title)
            : h("span", sourceAttrs(j), j.title),
          j.personal || j.private ? h("div", null, h("span", { class: "tag" }, "Only you")) : "",
          j.source !== "Jobly" || j.manual ? h("div", { class: "muted small" },
            j.source === "Community" ? "shared by a member" : j.manual ? "added by hand" : j.source) : ""),
        h("td", null, j.company, j.location ? h("div", { class: "muted small" }, places(j.location)) : ""),
        h("td", { class: "nowrap" }, j.posted),
        h("td", { class: "nowrap" + (j.days_left != null && j.days_left <= 3 && j.days_left >= 0 ? " overdue" : "") },
          j.deadline, j.deadline ? h("div", { class: "small" }, daysText(j.days_left)) : ""),
        h("td", { class: "nowrap" }, j.category),
        finnishCell(j),
        h("td", null, h("span", { class: "score" }, j.match.score), " ", h("span", { class: "small" }, j.match.score ? j.match.slug : "–"),
          j.match.words.length ? h("div", { class: "muted small" }, j.match.words.join(", ")) : "",
          !j.has_ad_text && j.url ? h("div", null, h("button", { class: "link small", "data-focus": `fetch:${j.id}`, onclick: async e => {
            e.target.disabled = true; e.target.textContent = "reading…";
            try { await api(`/api/jobs/${j.id}/fetch`, { method: "POST" }); load(`fetch:${j.id}`); }
            catch (err) {
              e.target.disabled = false;
              e.target.textContent = `Retry: ${err.message}`;
              e.target.focus();
            }
          } }, "read full ad")) : ""),
        h("td", null, !j.use_cv ? "" : !j.cv_ready
            ? ""
            : h("span", null, j.use_cv, h("div", { class: "muted small" }, j.use_cv_language.toUpperCase())),
          h("div", null, h("a", { class: "small", href: "#/cvs" }, "Create or edit your CV"))),
        h("td", null, tab === "discover" ? h("button", { class: "secondary small", "data-focus": `save:${j.id}`, "aria-label": `Save ${j.title} to my jobs`,
            onclick: async () => { await api(`/api/jobs/${j.id}/status`, { method: "POST", body: { status: "Saved" } }); load(`tab:discover`); } }, "Save") :
          h("select", { class: "status", "data-status": j.status || "", "data-focus": `status:${j.id}`, "aria-label": `Status for ${j.title}`, onchange: async e => {
            await api(`/api/jobs/${j.id}/status`, { method: "POST", body: { status: e.target.value } });
          load(`status:${j.id}`);
          } }, h("option", { value: "" }, "—"), state.statuses.map(s => h("option", { value: s, selected: j.status === s }, s))), fitCell(j))),
        tab === "mine" && openFit.has(j.id) ? h("tr", { class: "fit-row" }, h("td", { colspan: 9 },
          fitPanel(j.id, () => load(`fit:${j.id}`), fitNotes[j.id]))) : null].filter(Boolean));

      tableArea.replaceChildren(
        h("p", { class: "muted small" }, `${shown.length} of ${jobs.length} jobs. ` +
          "Match compares the listing with skills and experience in your own CVs. For Jobly jobs, “read full ad” fetches the description to improve matching. " +
          "Finnish shows what the ad says about Finnish, with the sentence it is based on; “keyword rule” results can't tell “an advantage” from “not needed”, so check the ad."),
        h("div", { class: "scroll" }, h("table", null,
          h("thead", null, h("tr", null, ["Job", "Company", "Posted", "Deadline", "Type", "Finnish", "Match", "Use CV", "Status"].map(header))),
          h("tbody", null, rows.length ? rows : h("tr", null, h("td", { colspan: 9, class: "empty" },
            tab === "mine" && !jobs.some(isMine) ? "No jobs yet. Add one by link above, or save one from Discover."
              : jobs.length ? "No jobs match these filters." : "No jobs in your fields yet. Add one by link above."))))));

      const focusTargets = [...listArea.querySelectorAll("[data-focus]")];
      const again = focusKey && focusTargets.find(el => el.dataset.focus === focusKey);
      const fetchFallback = focusKey?.startsWith("fetch:")
        ? focusTargets.find(el => el.dataset.focus === `status:${focusKey.slice("fetch:".length)}`)
        : null;
      (again || fetchFallback)?.focus();
      translation.apply();      // swaps in English titles when the switch is on English
    }

    await load();
    if (state.user.is_admin) poll();
    if (classifyBtn) pollClassify();
  },
});
