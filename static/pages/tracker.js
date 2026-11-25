// Applications → Tracker. Each stage is a stack of cards (empty stages are slim rails); a stack opens into a
// focused view of all its cards, and a card opens a side drawer with everything about the application. On small
// screens the stages are chips over one vertical list. Cards move by drag and drop, or with "Move to" in the
// card's ⋯ menu or the drawer (keyboard and screen readers); a move shows at once and is undone if saving fails.
// The rules (deadlines, sorting, filtering, stack or rail) are in ../tracker-model.js.
import { api, h, register, message, getState } from "../core.js";
import * as M from "../tracker-model.js";

const RATING = { strong: ["✓✓", "Strong fit"], possible: ["✓", "Possible fit"], stretch: ["≈", "A stretch"], weak: ["✗", "Weak fit"] };
const EMPTY = { Saved: "Save jobs from Discover.", Shortlisted: "Shortlist a job to check your fit.", Applied: "Drop a card here once you've applied.",
  Interview: "Interviews come after applying.", Offer: "No offers yet. Keep going.", Rejected: "Nothing here, and that's fine.", "Not a fit": "Nothing set aside." };
const SMALL = window.matchMedia("(max-width: 900px)");
const STACK_PEEK = 3;
const PAGE = 60;            // a long stage shows this many cards, then "Show more"

// The one next step: the member's own, else a follow-up reminder, else what usually comes next
function nextStep(a) {
  if (a.next_action || a.next_action_date) return { text: `${a.overdue ? "Overdue: " : ""}${a.next_action || "Next step"}${a.next_action_date ? ` · ${M.formatDay(a.next_action_date)}` : ""}`, overdue: a.overdue };
  if (a.follow_up) return { text: a.follow_up };
  if (a.closed && (a.status === "Saved" || a.status === "Shortlisted")) return { text: "The ad has closed." };
  if (a.status === "Saved" || a.status === "Shortlisted") return { text: "Prepare your CV and letter", href: `#/prepare?job=${a.job_id}` };
  if (a.status === "Applied") return { text: a.date_applied ? `Applied ${M.formatDay(a.date_applied)}. No news yet.` : "Waiting to hear back." };
  if (a.status === "Interview") return { text: "Practise your answers", href: "#/draft" };
  return null;
}

register({
  id: "tracker", title: "Tracker",
  async render(main, query) {
    const state = await getState();
    const params = new URLSearchParams(query || "");
    let { applications: apps, statuses, preferences: prefs } = await api("/api/applications");
    const view = { stage: statuses.includes(params.get("stage")) ? params.get("stage") : null, query: "", filter: "all",
      phoneStage: statuses.includes(params.get("stage")) ? params.get("stage") : "Saved" };
    let openApp = Number(params.get("app")) || null;
    let lastFocus = null;

    // ---- page frame
    const summaryLine = h("p", { class: "trk-summary", "aria-live": "polite" });
    const search = h("input", { type: "search", placeholder: "Search my applications", "aria-label": "Search my applications",
      oninput: () => { view.query = search.value; draw(); } });
    const filter = h("select", { "aria-label": "Filter by deadline", onchange: () => { view.filter = filter.value; draw(); } },
      h("option", { value: "all" }, "All deadlines"), h("option", { value: "week" }, "Closing this week"), h("option", { value: "closed" }, "Closed"));
    const sort = h("select", { "aria-label": "Sort cards", onchange: () => savePrefs({ sort: sort.value }) },
      h("option", { value: "deadline" }, "Sort: deadline"), h("option", { value: "added" }, "Sort: date added"), h("option", { value: "match" }, "Sort: fit"));
    const densityName = "trk-density-" + Math.random().toString(36).slice(2);
    const density = h("fieldset", { class: "segmented trk-density" }, h("legend", { class: "visually-hidden" }, "Card density"),
      ...[["comfortable", "Comfortable"], ["compact", "Compact"]].map(([value, text]) => h("label", null,
        h("input", { type: "radio", name: densityName, value, onchange: () => savePrefs({ density: value }) }), h("span", null, text))));
    const hideClosed = h("label", { class: "check small" }, h("input", { type: "checkbox", onchange: e => savePrefs({ hide_closed: e.target.checked }) }), " Hide closed");
    const board = h("div", { class: "trk-board" });
    const toast = h("div", { class: "trk-toast", role: "status", "aria-live": "polite" });
    const backdrop = h("div", { class: "trk-backdrop", hidden: true, onclick: () => closeDrawer() });
    const drawer = h("aside", { class: "trk-drawer", role: "dialog", "aria-modal": "true", "aria-labelledby": "trk-drawer-title", hidden: true, tabindex: -1 });
    main.append(
      h("div", { class: "page-head" },
        h("div", null, h("h1", null, "Applications"), summaryLine),
        h("div", { class: "page-head-side" }, h("a", { class: "btn secondary small", href: "/api/calendar.ics", download: "jobdesk.ics" }, "Add dates to my calendar"))),
      h("div", { class: "trk-toolbar" }, search, filter, sort, density, hideClosed),
      board, backdrop, drawer, toast);

    // ---- helpers
    const options = () => ({ query: view.query, filter: view.filter, sort: prefs.sort, hideClosed: prefs.hide_closed });
    const total = status => apps.filter(a => a.status === status).length;
    const setURL = () => {
      const p = new URLSearchParams();
      if (view.stage) p.set("stage", view.stage);
      if (openApp) p.set("app", String(openApp));
      history.replaceState(null, "", `#/tracker${p.toString() ? `?${p}` : ""}`);
    };
    let toastTimer;
    function say(text, isError) {
      toast.replaceChildren(message(text, isError));
      toast.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove("show"), 6000);
    }
    async function savePrefs(change) {
      prefs = { ...prefs, ...change };
      draw();
      try { prefs = (await api("/api/account/tracker", { method: "POST", body: change })).preferences; }
      catch (error) { say(`Your view settings weren't saved: ${error.message}`, true); }
    }

    // A move shows at once; if the server refuses, the card goes back and a message says so
    async function move(id, status) {
      const app = apps.find(a => a.id === id);
      if (!app || app.status === status) return;
      const { before, after } = M.moved(apps, id, status);
      apps = after;
      if ((prefs.collapsed || []).includes(status)) prefs = { ...prefs, collapsed: prefs.collapsed.filter(s => s !== status) };   // a rail opens when a card lands
      draw();
      if (openApp === id) drawDrawer();
      try {
        await api(`/api/applications/${id}`, { method: "POST", body: { status } });
        say(`Moved “${app.title}” to ${M.stageLabel(status)}.`);
        refresh();
      } catch (error) {
        apps = before;
        draw();
        if (openApp === id) drawDrawer();
        say(`Couldn't move “${app.title}”: ${error.message}`, true);
      }
    }
    async function refresh() {
      try {
        const data = await api("/api/applications", { fresh: true });
        if (!board.isConnected) return;
        apps = data.applications;
        draw();
        if (openApp) drawDrawer();
      } catch { /* the page keeps what it shows */ }
    }

    function dropTarget(el, status) {
      el.addEventListener("dragover", e => { e.preventDefault(); el.classList.add("over"); });
      el.addEventListener("dragleave", e => { if (!el.contains(e.relatedTarget)) el.classList.remove("over"); });
      el.addEventListener("drop", e => {
        e.preventDefault();
        el.classList.remove("over");
        const id = Number(e.dataTransfer.getData("text/plain"));
        if (id) move(id, status);
      });
      return el;
    }

    // ---- a card
    let openMenu = null;
    function closeMenu(returnFocus) {
      if (!openMenu) return;
      const { menu, button } = openMenu;
      menu.hidden = true;
      button.setAttribute("aria-expanded", "false");
      openMenu = null;
      if (returnFocus) button.focus();
    }
    function card(a, { peek = false } = {}) {
      const compact = prefs.density === "compact";
      const chip = M.deadlineChip(a);
      const step = nextStep(a);
      const menuId = `trk-menu-${a.id}-${Math.random().toString(36).slice(2, 7)}`;
      const menuButton = h("button", { type: "button", class: "trk-more", "aria-haspopup": "true", "aria-expanded": "false",
        "aria-controls": menuId, "aria-label": `Actions for ${a.title}`, onclick: e => {
          e.stopPropagation();
          const isOpen = openMenu?.menu === menu;
          closeMenu();
          if (!isOpen) {
            menu.hidden = false;
            menuButton.setAttribute("aria-expanded", "true");
            openMenu = { menu, button: menuButton };
            menu.querySelector("button")?.focus();
          }
        } }, "⋯");
      const menu = h("div", { class: "trk-menu", id: menuId, hidden: true,
        onkeydown: e => { if (e.key === "Escape") { e.stopPropagation(); closeMenu(true); } } },
        h("button", { type: "button", onclick: () => { closeMenu(); openDrawer(a.id); } }, "Open details"),
        h("p", { class: "trk-menu-label" }, "Move to"),
        ...statuses.filter(s => s !== a.status).map(s => h("button", { type: "button", class: "status", "data-status": s,
          onclick: () => { closeMenu(); move(a.id, s); } }, M.stageLabel(s))));
      const rating = a.rating && RATING[a.rating];
      return h("article", { class: `trk-card${compact ? " compact" : ""}${a.closed ? " is-closed" : ""}${peek ? " peek" : ""}`,
          "data-id": a.id, draggable: SMALL.matches ? null : "true",
          ondragstart: e => { e.dataTransfer.setData("text/plain", String(a.id)); e.dataTransfer.effectAllowed = "move"; e.currentTarget.classList.add("dragging"); },
          ondragend: e => e.currentTarget.classList.remove("dragging") },
        h("div", { class: "trk-card-top" },
          h("button", { type: "button", class: "trk-title", title: a.title, "data-open": a.id, onclick: () => openDrawer(a.id) },
            h("span", { class: "trk-title-text" }, a.title)),
          peek ? "" : menuButton),
        h("p", { class: "trk-employer" }, a.company || "Employer not given"),
        compact || peek ? "" : [
          M.placeText(a) ? h("p", { class: "trk-place muted small" }, M.placeText(a)) : "",
          chip || rating ? h("p", { class: "trk-chips" },
            chip ? h("span", { class: `trk-chip ${chip.kind}` }, chip.text) : "",
            rating ? h("span", { class: `trk-rating ${a.rating}`, title: rating[1] }, h("span", { "aria-hidden": "true" }, rating[0]), ` ${rating[1]}`) : "") : "",
          step ? h("p", { class: `trk-next small${step.overdue ? " overdue" : ""}` },
            step.href ? h("a", { href: step.href }, step.text) : step.text) : ""],
        peek ? "" : menu);
    }

    // ---- the overview: stacks and rails
    function rail(status) {
      const count = M.stageCards(apps, status, options());
      const n = count.open.length + count.closed.length;
      return dropTarget(h("button", { type: "button", class: "trk-rail status", "data-status": status,
        "aria-label": `${M.stageLabel(status)}: ${n}. ${total(status) ? "Unfold" : "Open"}`,
        onclick: () => {
          if (total(status) && (prefs.collapsed || []).includes(status)) savePrefs({ collapsed: prefs.collapsed.filter(s => s !== status) });
          else focusStage(status);
        } }, h("span", { class: "trk-rail-name" }, M.stageLabel(status)), h("span", { class: "trk-count" }, String(n))), status);
    }
    function stack(status) {
      const { open, closed } = M.stageCards(apps, status, options());
      const cards = [...open, ...closed];
      const shown = cards.slice(0, STACK_PEEK);
      const deck = h("div", { class: "trk-deck" }, ...shown.map((a, i) => card(a, { peek: i < shown.length - 1 && shown.length > 1 })));
      return dropTarget(h("section", { class: "trk-stack status", "data-status": status, "aria-label": `${M.stageLabel(status)}: ${cards.length}` },
        h("header", { class: "trk-stack-head" },
          h("button", { type: "button", class: "trk-stack-open", onclick: () => focusStage(status) },
            h("span", null, M.stageLabel(status)), h("span", { class: "trk-count" }, String(cards.length))),
          h("button", { type: "button", class: "trk-fold", "aria-label": `Fold ${M.stageLabel(status)} into a rail`, title: "Fold",
            onclick: () => savePrefs({ collapsed: [...(prefs.collapsed || []), status] }) }, "⇤")),
        cards.length ? deck : h("p", { class: "trk-empty" }, EMPTY[status] || "Drop a card here."),
        cards.length > shown.length || cards.length > 1 ? h("button", { type: "button", class: "trk-more-cards link small", onclick: () => focusStage(status) },
          cards.length > shown.length ? `+${cards.length - shown.length} more · see all` : "See all") : ""), status);
    }
    function overview() {
      // the row scrolls sideways when many stages are filled, so it takes keyboard focus (WCAG 2.1.1)
      return h("div", { class: "trk-stacks", role: "region", "aria-label": "Applications by stage", tabindex: 0 },
        ...statuses.map(status => (M.layoutFor(status, total(status), prefs) === "rail" ? rail(status) : stack(status))));
    }

    // A long list in pieces: the first PAGE cards, then a button for the next ones (150 cards stay quick)
    let shownCount = PAGE;
    function limited(cards) {
      return { cards: cards.slice(0, shownCount), rest: Math.max(0, cards.length - shownCount) };
    }
    function showMore(rest) {
      return rest ? h("button", { type: "button", class: "secondary small trk-show-more",
        onclick: () => { shownCount += PAGE; draw(); } }, `Show ${Math.min(rest, PAGE)} more (${rest} left)`) : "";
    }

    // ---- one stage, all its cards
    function focused(status) {
      const all = M.stageCards(apps, status, options());
      const page = limited([...all.open, ...all.closed]);
      const open = page.cards.filter(a => !a.closed), closed = page.cards.filter(a => a.closed);
      const totalShown = all.open.length + all.closed.length;
      const region = dropTarget(h("section", { class: "trk-focus status entering", "data-status": status, "aria-labelledby": "trk-focus-title" },
        h("nav", { class: "trk-crumbs", "aria-label": "Breadcrumb" },
          h("button", { type: "button", class: "link", onclick: () => focusStage(null) }, "← All stages"), " / ",
          h("h2", { id: "trk-focus-title", tabindex: -1 }, `${M.stageLabel(status)} (${totalShown})`)),
        open.length ? h("div", { class: "trk-grid" }, ...open.map(a => card(a)))
          : !closed.length ? h("p", { class: "trk-empty" }, view.query || view.filter !== "all" ? "No cards match." : EMPTY[status] || "Drop a card here.") : "",
        closed.length ? [h("h3", { class: "trk-closed-head" }, `Closed (${all.closed.length})`),
          h("div", { class: "trk-grid closed" }, ...closed.map(a => card(a)))] : "",
        showMore(page.rest)), status);
      return region;
    }
    function focusStage(status) {
      shownCount = PAGE;
      view.stage = status;
      if (status) view.phoneStage = status;
      setURL();
      draw();
      (status ? board.querySelector("#trk-focus-title") : board.querySelector(`.trk-stack-open, .trk-rail`))?.focus();
    }

    // ---- phones and tablets: stage chips over one vertical list
    function phone() {
      const status = view.phoneStage;
      const all = M.stageCards(apps, status, options());
      const page = limited([...all.open, ...all.closed]);
      const open = page.cards.filter(a => !a.closed), closed = page.cards.filter(a => a.closed);
      return h("div", { class: "trk-phone" },
        h("div", { class: "trk-chips-row", role: "group", "aria-label": "Stage" }, ...statuses.map(s => h("button", {
          type: "button", class: "chip status", "data-status": s, "aria-pressed": s === status ? "true" : "false",
          onclick: () => { view.phoneStage = s; view.stage = s; shownCount = PAGE; setURL(); draw(); } },
          M.stageLabel(s), h("span", { class: "toggle-count" }, ` ${total(s)}`)))),
        open.length || closed.length ? h("div", { class: "trk-list" }, ...open.map(a => card(a)),
          closed.length ? h("h3", { class: "trk-closed-head" }, `Closed (${all.closed.length})`) : "", ...closed.map(a => card(a)),
          showMore(page.rest))
          : h("p", { class: "trk-empty" }, EMPTY[status] || "Nothing here."));
    }

    // ---- the drawer
    function openDrawer(id) {
      lastFocus = document.activeElement;
      openApp = id;
      setURL();
      drawDrawer();
    }
    function closeDrawer() {
      if (!openApp) return;
      const id = openApp;
      openApp = null;
      drawer.hidden = true;
      backdrop.hidden = true;
      setURL();
      (lastFocus?.isConnected ? lastFocus : board.querySelector(`[data-open="${id}"]`))?.focus();
    }
    function drawDrawer() {
      const a = apps.find(x => x.id === openApp);
      if (!a) { openApp = null; drawer.hidden = true; backdrop.hidden = true; setURL(); return; }
      const f = {};
      const feedback = h("div", { "aria-live": "polite" });
      const input = (name, label, type = "text") => h("label", { class: "field" }, label, f[name] = h("input", { type, value: a[name] || "" }));
      const chip = M.deadlineChip(a);
      const step = nextStep(a);
      const rating = a.rating && RATING[a.rating];
      const fact = (label, value) => value ? [h("dt", null, label), h("dd", null, value)] : [];
      drawer.replaceChildren(
        h("header", { class: "trk-drawer-head" },
          h("div", null, h("p", { class: "eyebrow" }, M.stageLabel(a.status)), h("h2", { id: "trk-drawer-title" }, a.title),
            h("p", { class: "muted" }, [a.company, M.placeText(a)].filter(Boolean).join(" · "))),
          h("button", { type: "button", class: "secondary small", onclick: closeDrawer, "aria-label": "Close details" }, "Close")),
        h("p", { class: "trk-chips" }, chip ? h("span", { class: `trk-chip ${chip.kind}` }, chip.text) : "",
          rating ? h("span", { class: `trk-rating ${a.rating}` }, `${rating[0]} ${rating[1]}`) : ""),
        h("label", { class: "field" }, "Stage", h("select", { class: "status", "data-status": a.status, onchange: e => move(a.id, e.target.value) },
          statuses.map(s => h("option", { value: s, selected: s === a.status }, M.stageLabel(s))))),
        step ? h("p", { class: `trk-next${step.overdue ? " overdue" : ""}` }, h("strong", null, "Next: "), step.href ? h("a", { href: step.href }, step.text) : step.text) : "",
        a.follow_up && step?.text !== a.follow_up ? h("p", { class: "trk-next" }, a.follow_up) : "",
        h("div", { class: "row" },
          a.url ? h("a", { class: "btn secondary small", href: a.url, target: "_blank", rel: "noopener" }, "Open the ad") : "",
          h("a", { class: "btn secondary small", href: `#/prepare?job=${a.job_id}` }, "CV and cover letter"),
          h("a", { class: "btn secondary small", href: "#/draft" }, "Draft an answer")),
        h("dl", { class: "trk-facts" },
          ...fact("Deadline", a.deadline ? `${M.formatDay(a.deadline)}${a.closed ? " (closed)" : ""}` : ""),
          ...fact("Added", a.created_at ? M.formatDay(a.created_at) : ""),
          ...fact("Stage since", a.status_changed_at ? M.formatDay(a.status_changed_at) : ""),
          ...fact("Applied", a.date_applied ? M.formatDay(a.date_applied) : ""),
          ...fact("Place", a.location || "")),
        h("form", { class: "trk-form", onsubmit: async e => {
            e.preventDefault();
            const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
            try {
              await api(`/api/applications/${a.id}`, { method: "POST", body });
              feedback.replaceChildren(message("Saved."));
              refresh();
            } catch (err) { feedback.replaceChildren(message(err.message, true)); }
          } },
          input("next_action", "Next step"), input("next_action_date", "Next step date", "date"),
          input("date_applied", "Date applied", "date"),
          h("label", { class: "field" }, "CV used", f.cv_role = h("select", null, h("option", { value: "" }, "—"),
            state.roles.map(r => h("option", { value: r.slug, selected: r.slug === a.cv_role }, r.title)))),
          input("employer_link", "Link you sent the employer", "url"), input("contact", "Contact"),
          h("label", { class: "field" }, "Notes", f.notes = h("textarea", { rows: 4 }, a.notes || "")),
          h("div", { class: "row" }, h("button", { type: "submit" }, "Save"), feedback)));
      drawer.hidden = false;
      backdrop.hidden = false;
      const heading = drawer.querySelector("h2");
      heading.setAttribute("tabindex", "-1");
      if (!drawer.contains(document.activeElement)) {
        heading.focus();
        // opened from a link, the page is still being drawn out of sight: focus once it is shown
        if (document.activeElement !== heading) setTimeout(() => { if (openApp && !drawer.hidden) heading.focus(); }, 0);
      }
    }
    // Keyboard: Esc closes the open menu, else the drawer (wherever focus is); Tab stays inside the drawer
    const onEscape = e => {
      if (!board.isConnected) { document.removeEventListener("keydown", onEscape); return; }
      if (e.key !== "Escape") return;
      if (openMenu) { closeMenu(true); return; }
      if (openApp) { e.preventDefault(); closeDrawer(); }
    };
    document.addEventListener("keydown", onEscape);
    drawer.addEventListener("keydown", e => {
      if (e.key !== "Tab") return;
      const items = [...drawer.querySelectorAll("a[href], button, input, select, textarea")].filter(el => !el.disabled);
      if (!items.length) return;
      if (e.shiftKey && document.activeElement === items[0]) { e.preventDefault(); items.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === items.at(-1)) { e.preventDefault(); items[0].focus(); }
    });
    const outside = e => { if (openMenu && !openMenu.menu.contains(e.target) && e.target !== openMenu.button) closeMenu(); };
    document.addEventListener("click", outside);

    // ---- drawing
    function draw() {
      summaryLine.textContent = M.summary(apps);
      sort.value = prefs.sort;
      density.querySelectorAll("input").forEach(i => { i.checked = i.value === prefs.density; });
      hideClosed.querySelector("input").checked = prefs.hide_closed;
      openMenu = null;
      board.replaceChildren(SMALL.matches ? phone() : view.stage ? focused(view.stage) : overview());
    }
    const onResize = () => { if (!board.isConnected) { SMALL.removeEventListener("change", onResize); document.removeEventListener("click", outside); return; } draw(); };
    SMALL.addEventListener("change", onResize);
    draw();
    if (openApp) drawDrawer();
  },
});
