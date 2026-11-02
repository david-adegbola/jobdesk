import { api, h, register, store, message } from "../core.js";

const VIEW_KEY = "news.view";
const DEFAULT_VIEW = { query: "", category: "", region: "", state: "", days: "30", sort: "recent" };

function loadView() {
  try {
    const saved = JSON.parse(store(VIEW_KEY) || "null");
    const view = { ...DEFAULT_VIEW, ...(saved || {}) };
    if (!["", "unread", "saved"].includes(view.state)) view.state = "";
    if (!["7", "30", "90", "all"].includes(view.days)) view.days = "30";
    if (!["recent", "relevance"].includes(view.sort)) view.sort = "recent";
    return view;
  } catch (error) {
    return { ...DEFAULT_VIEW };
  }
}

function formatDate(value) {
  if (!value) return "Date not provided";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date not provided"
    : new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(date);
}

function formatChecked(value) {
  if (!value) return "Not checked yet";
  const date = new Date(value.replace(" ", "T"));
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

register({
  id: "news",
  title: "News",
  async render(main) {
    let data = await api("/api/news");
    let items = data.items;
    const view = loadView();
    const feedback = h("div");
    const itemList = h("div", { class: "news-list", "aria-live": "polite" });
    const count = h("p", { class: "muted small", role: "status" });
    const refreshButton = h("button", { onclick: refresh }, "Refresh news");

    const query = h("input", {
      type: "search",
      value: view.query,
      placeholder: "Search titles, summaries and topics",
      "aria-label": "Search forestry news",
      oninput: e => {
        view.query = e.target.value;
        saveView();
        drawItems();
      },
    });
    const category = h("select", {
      "aria-label": "Filter by topic",
      onchange: e => { view.category = e.target.value; saveView(); drawItems(); },
    });
    const region = h("select", {
      "aria-label": "Filter by feed scope",
      onchange: e => { view.region = e.target.value; saveView(); drawItems(); },
    });
    const stateFilter = h("select", {
      "aria-label": "Filter by reading status",
      onchange: e => { view.state = e.target.value; saveView(); drawItems(); },
    },
    h("option", { value: "" }, "All stories"),
    h("option", { value: "unread" }, "Unread"),
    h("option", { value: "saved" }, "Saved"));
    stateFilter.value = view.state;
    const days = h("select", {
      "aria-label": "Filter by publication date",
      onchange: e => { view.days = e.target.value; saveView(); drawItems(); },
    },
    h("option", { value: "7" }, "Last 7 days"),
    h("option", { value: "30" }, "Last 30 days"),
    h("option", { value: "90" }, "Last 90 days"),
    h("option", { value: "all" }, "Any time"));
    days.value = view.days;
    const sort = h("select", {
      "aria-label": "Sort news stories",
      onchange: e => { view.sort = e.target.value; saveView(); drawItems(); },
    },
    h("option", { value: "recent" }, "Newest first"),
    h("option", { value: "relevance" }, "Interest match"));
    sort.value = view.sort;
    const sourceList = h("ul", { class: "news-sources" });
    const sourceDetails = h("details", { class: "card news-source-details" },
      h("summary", null, "Sources and refresh status"),
      h("p", { class: "muted small" }, "Feeds are fetched when you refresh. Story summaries come from each feed; open the source for the full article."),
      sourceList);

    main.append(
      h("h1", null, "News"),
      h("p", { class: "muted news-intro" },
        "Forestry and forest-bioeconomy developments for Finland, with extra coverage of Joensuu and North Karelia. Curated for research, sustainable forest management, policy, markets and forest technology. ",
        h("a", { href: "#/jobs" }, "Browse matching jobs"), "."),
      h("p", { class: "muted small" },
        "Topic tags and the interest score are keyword-based (with a Joensuu/North Karelia feed-scope boost), not AI ratings or probabilities. Refresh is manual and respects each feed's 30–60-minute interval; RSS excerpts can be incomplete."),
      h("div", { class: "row news-refresh" }, refreshButton, h("span", { class: "muted", role: "status", "aria-live": "polite" }, refreshStatus())),
      feedback,
      h("div", { class: "news-filters" },
        h("label", { class: "field news-search" }, "Search", query),
        h("label", { class: "field" }, "Topic", category),
        h("label", { class: "field" }, "Feed scope", region),
        h("label", { class: "field" }, "Reading list", stateFilter),
        h("label", { class: "field" }, "Published", days),
        h("label", { class: "field" }, "Sort", sort)),
      count,
      itemList,
      sourceDetails,
    );

    updateSources();
    drawItems();

    function saveView() {
      store(VIEW_KEY, JSON.stringify(view));
    }

    function refreshStatus() {
      const checked = data.sources
        .map(source => source.state?.checked_at)
        .filter(Boolean)
        .sort()
        .at(-1);
      return checked ? `Last checked ${formatChecked(checked)}` : "Sources have not been checked yet.";
    }

    function updateSources() {
      const categories = [...new Set(items.map(item => item.category))].sort();
      const regions = [...new Set(items.map(item => item.region))].sort();
      category.replaceChildren(
        h("option", { value: "" }, "All topics"),
        ...categories.map(name => h("option", { value: name }, name)),
      );
      if (!categories.includes(view.category)) view.category = "";
      category.value = view.category;
      region.replaceChildren(
        h("option", { value: "" }, "All feed scopes"),
        ...regions.map(name => h("option", { value: name }, name)),
      );
      if (!regions.includes(view.region)) view.region = "";
      region.value = view.region;
      sourceList.replaceChildren(...data.sources.map(source => {
        const state = source.state;
        const detail = state
          ? `${state.found} relevant stories · checked ${formatChecked(state.checked_at)}`
          : "Not checked yet";
        return h("li", null,
          h("a", { href: source.url, target: "_blank", rel: "noopener noreferrer" }, source.name),
          h("span", { class: "muted small" }, ` — ${source.region} · ${detail}`),
          state?.error ? h("p", { class: "news-source-error", role: "status" }, `Last error: ${state.error}`) : "");
      }));
    }

    function visibleItems() {
      const cutoff = view.days === "all" || view.state === "saved"
        ? null
        : Date.now() - Number(view.days) * 24 * 60 * 60 * 1000;
      const search = view.query.trim().toLocaleLowerCase();
      const matches = items.filter(item => {
        const published = Date.parse(item.published_at);
        const haystack = `${item.title} ${item.summary} ${item.source} ${item.category} ${item.region} ${item.matched_topics}`
          .toLocaleLowerCase();
        return (!search || haystack.includes(search)) &&
          (!view.category || item.category === view.category) &&
        (!view.region || item.region === view.region) &&
          (view.state !== "unread" || !item.is_read) &&
          (view.state !== "saved" || item.is_saved) &&
          (cutoff == null || !Number.isFinite(published) || published >= cutoff);
      });
      return matches.sort((a, b) => view.sort === "relevance"
        ? b.relevance - a.relevance || (b.published_at || "").localeCompare(a.published_at || "")
        : (b.published_at || "").localeCompare(a.published_at || ""));
    }

    function drawItems() {
      const visible = visibleItems();
      count.textContent = `${visible.length} of ${items.length} stories`;
      if (!visible.length) {
        itemList.replaceChildren(h("p", { class: "empty" },
          items.length ? "No stories match these filters. Try another topic, date range or search." :
            "No news loaded yet. Refresh the feeds to bring current stories into Woodesk."));
        return;
      }
      const focused = document.activeElement?.dataset.focus;
      itemList.replaceChildren(...visible.map(item => {
        const topics = item.matched_topics.split(", ").filter(Boolean);
        return h("article", { class: `card news-card${item.is_read ? " is-read" : ""}` },
          h("div", { class: "news-card-meta" },
            h("span", { class: "tag" }, item.category),
            h("span", { class: "muted small" }, `Feed scope: ${item.region}`),
            h("span", { class: "tag" }, `Interest ${item.relevance}/100`),
            item.is_read ? h("span", { class: "tag" }, "Read") : h("span", { class: "tag new" }, "Unread")),
          h("h2", null, h("a", { href: item.url, target: "_blank", rel: "noopener noreferrer" }, item.title)),
          h("p", { class: "news-byline muted small" },
            `${item.source} · ${formatDate(item.published_at)}` +
            (item.coverage.length ? ` · ${item.coverage.length + 1} reports` : "")),
          h("p", { class: "news-summary" }, item.summary || "This feed did not include an excerpt. Open the source for the full story."),
          h("p", { class: "news-context" },
            h("strong", null, "Why it may matter: "), item.why_it_matters),
          h("p", { class: "news-career-angle" },
            h("strong", null, "Career angle: "), item.career_angle),
          item.coverage.length ? h("details", { class: "news-coverage" },
            h("summary", null, `Other coverage (${item.coverage.length})`),
            h("ul", null, ...item.coverage.map(coverage => h("li", null,
              h("a", { href: coverage.url, target: "_blank", rel: "noopener noreferrer" },
                `${coverage.source}: ${coverage.title}`))))) : "",
          topics.length ? h("div", { class: "news-topics", "aria-label": "Matched topics" },
            ...topics.map(topic => h("span", { class: "tag" }, topic))) : "",
          h("div", { class: "row news-actions" },
            h("a", { class: "btn secondary news-open", href: item.url, target: "_blank", rel: "noopener noreferrer" },
              "Open original"),
            h("button", {
              class: "secondary news-action",
              "aria-pressed": item.is_saved ? "true" : "false",
              "data-focus": `saved:${item.id}`,
              onclick: () => changeState(item, "is_saved", !item.is_saved),
            }, item.is_saved ? "Saved" : "Save for later"),
            h("button", {
              class: "secondary news-action",
              "aria-pressed": item.is_read ? "true" : "false",
              "data-focus": `read:${item.id}`,
              onclick: () => changeState(item, "is_read", !item.is_read),
            }, item.is_read ? "Mark unread" : "Mark read")));
      }));
      if (focused) {
        const button = [...itemList.querySelectorAll("[data-focus]")].find(el => el.dataset.focus === focused);
        button?.focus();
      }
    }

    async function changeState(item, field, value) {
      try {
        await api(`/api/news/${item.id}/state`, { method: "POST", body: { [field]: value } });
        item[field] = Number(value);
        drawItems();
      } catch (error) {
        feedback.replaceChildren(message(error.message, true));
      }
    }

    async function refresh() {
      refreshButton.disabled = true;
      refreshButton.textContent = "Refreshing…";
      feedback.replaceChildren();
      try {
        const result = await api("/api/news/refresh", { method: "POST" });
        data = await api("/api/news");
        items = data.items;
        updateSources();
        drawItems();
        const failed = result.errors.length;
        feedback.replaceChildren(message(
          `${result.new} new stories; ${result.found} relevant feed matches checked across ${result.checked} sources.` +
          (result.skipped ? ` ${result.skipped} sources were still within their refresh interval.` : "") +
          (failed ? ` ${failed} source${failed === 1 ? "" : "s"} could not be refreshed; see source status below.` : ""),
          failed > 0,
        ));
        main.querySelector(".news-refresh [role=status]").textContent = refreshStatus();
      } catch (error) {
        feedback.replaceChildren(message(`News refresh failed: ${error.message}`, true));
      } finally {
        refreshButton.disabled = false;
        refreshButton.textContent = "Refresh news";
      }
    }
  },
});
