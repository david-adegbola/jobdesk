import { api, h, register, message } from "../core.js";
const AUDIENCES = [
  ["student", "Bachelor's / master's student"],
  ["researcher", "PhD student / researcher"],
  ["owner", "Forest owner"],
  ["professional", "Forestry professional"],
  ["exploring", "Exploring the sector"],
];
const TOPICS = [
  { id: "bioeconomy", label: "Sustainable forest bioeconomy", terms: ["bioeconom", "biotalous", "sustainable forest", "metsätalous", "metsäteollisuus"] },
  { id: "management", label: "Forest management & ownership", terms: ["forest owner", "metsänomist", "metsänhoito", "silviculture", "wood supply", "puukauppa"] },
  { id: "research", label: "Research, thesis & doctoral work", terms: ["research", "tutkim", "thesis", "väitöskir", "doctoral", "scientific", "publication"] },
  { id: "data", label: "GIS, remote sensing & forest data", terms: ["gis", "geospatial", "paikkatieto", "remote sensing", "kaukokartoit", "laser scanning", "metsätieto", "forest data", "arbonaut"] },
  { id: "nature", label: "Biodiversity & climate", terms: ["biodiversity", "luonto", "ilmasto", "climate", "nature", "hiiliniel", "carbon", "ecosystem", "ekosysteem"] },
  { id: "materials", label: "Wood, materials & circular economy", terms: ["wood", "puu", "material", "materiaali", "circular", "kiertotalous", "pulp", "bio-based"] },
  { id: "policy", label: "Policy, markets & funding", terms: ["policy", "politiik", "market", "markkin", "funding", "rahoitus", "grant", "apuraha", "subsidy", "tuki"] },
];
const AUDIENCE_TERMS = {
  student: ["intern", "internship", "trainee", "harjoittelu", "opiskelija", "thesis", "graduate", "stipend", "apuraha"],
  researcher: ["research", "tutkim", "doctoral", "phd", "väitöskir", "publication", "dataset", "researcher"],
  owner: ["forest owner", "metsänomist", "metsänhoito", "puukauppa", "forest management"],
  professional: ["specialist", "asiantunt", "engineer", "insinööri", "manager", "project", "hanke"],
  exploring: [],
};
const DEFAULT_PROFILE = {
  audiences: ["student"],
  topics: ["bioeconomy", "research", "data"],
  region: "north-karelia",
};

function readProfile(value) {
  return {
    saved: Boolean(value && Object.keys(value).length),
    profile: {
      audiences: Array.isArray(value.audiences)
        ? value.audiences.filter(id => AUDIENCES.some(([key]) => key === id)) : [...DEFAULT_PROFILE.audiences],
      topics: Array.isArray(value.topics)
        ? value.topics.filter(id => TOPICS.some(topic => topic.id === id)) : [...DEFAULT_PROFILE.topics],
      region: ["anywhere", "finland", "north-karelia"].includes(value.region) ? value.region : DEFAULT_PROFILE.region,
    },
  };
}

function dayDelta(value) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const now = new Date();
  const todayUtc = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((Date.UTC(year, month - 1, day) - todayUtc) / 86400000);
}

function dateLabel(value) {
  const delta = dayDelta(value);
  if (delta === null) return value || "Date not listed";
  if (delta < 0) return `${Math.abs(delta)} day${delta === -1 ? "" : "s"} overdue`;
  if (delta === 0) return "Today";
  if (delta === 1) return "Tomorrow";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" })
    .format(new Date(`${value}T12:00:00Z`));
}

function recent(value, days = 7) {
  if (!value) return false;
  const delta = dayDelta(value.slice(0, 10));
  return delta !== null && delta >= 0 && delta < days;
}

function textFor(item, keys) {
  return keys.map(key => item[key] || "").join(" ").toLocaleLowerCase();
}

function matchingTopics(item, profile) {
  const text = textFor(item, ["title", "summary", "ad_text", "category", "matched_topics"]);
  return TOPICS.filter(topic => profile.topics.includes(topic.id) &&
    topic.terms.some(term => text.includes(term))).map(topic => topic.id);
}

function interestScore(item, profile) {
  const text = textFor(item, ["title", "summary", "ad_text", "category", "matched_topics"]);
  const topicMatches = matchingTopics(item, profile);
  const audienceMatch = profile.audiences.some(audience =>
    (AUDIENCE_TERMS[audience] || []).some(term => text.includes(term)));
  const placeText = textFor(item, ["location", "region", "title"]);
  const inNorthKarelia = /joensuu|north karelia|pohjois-karjala|pohjois karjala|karjala/i.test(placeText);
  const inFinland = /finland|suomi|finnish|pohjois|etelä|keski/i.test(placeText);
  const regionBonus = (profile.region === "north-karelia" && inNorthKarelia ? 4 :
    profile.region === "finland" && inFinland ? 1 : 0);
  return { score: topicMatches.length * 10 + (audienceMatch ? 3 : 0) + regionBonus,
    topicMatches, audienceMatch };
}

function profileForm(profile, isSaved, onSave) {
  const audienceInputs = [];
  const topicInputs = [];
  const status = h("div", { "aria-live": "polite" });
  let region;
  const form = h("form", { onsubmit: async event => {
    event.preventDefault();
    const updated = {
      audiences: audienceInputs.filter(([, input]) => input.checked).map(([id]) => id),
      topics: topicInputs.filter(([, input]) => input.checked).map(([id]) => id),
      region: region.value,
    };
    try { await onSave(updated); }
    catch (error) { status.replaceChildren(message(error.message, true)); }
  } },
    h("p", { class: "muted" }, "Pick more than one if it fits. These choices shape your weekly picks; you can change them any time."),
    h("fieldset", { class: "home-fieldset" },
      h("legend", null, "I am interested as a…"),
      h("div", { class: "home-check-grid" }, ...AUDIENCES.map(([id, label]) => {
        const input = h("input", { type: "checkbox", value: id, checked: profile.audiences.includes(id) });
        audienceInputs.push([id, input]);
        return h("label", { class: "home-check" }, input, label);
      }))),
    h("fieldset", { class: "home-fieldset" },
      h("legend", null, "Show me more about…"),
      h("div", { class: "home-check-grid" }, ...TOPICS.map(topic => {
        const input = h("input", { type: "checkbox", value: topic.id, checked: profile.topics.includes(topic.id) });
        topicInputs.push([topic.id, input]);
        return h("label", { class: "home-check" }, input, topic.label);
      }))),
    h("label", { class: "field home-region" }, "Location",
      region = h("select", null,
        h("option", { value: "anywhere", selected: profile.region === "anywhere" }, "Any location"),
        h("option", { value: "finland", selected: profile.region === "finland" }, "Finland"),
        h("option", { value: "north-karelia", selected: profile.region === "north-karelia" }, "Joensuu / North Karelia")),
      h("span", { class: "muted small" }, "Local matches are prioritized; other listings remain visible.")),
    h("div", { class: "row" }, h("button", { type: "submit" }, "Save my focus"),
      isSaved ? h("span", { class: "muted small" }, "Saved to your account.") : ""),
    status);
  return form;
}

function recommendationCard(item, kind, score, action) {
  const topicLabels = score.topicMatches.map(id => TOPICS.find(topic => topic.id === id)?.label).filter(Boolean);
  const href = item.url;
  const subtitle = kind === "job"
    ? [item.company, item.location].filter(Boolean).join(" · ")
    : [item.source, item.published_at?.slice(0, 10)].filter(Boolean).join(" · ");
  return h("article", { class: "home-item" },
    h("div", { class: "home-item-main" },
      h("h3", null, href ? h("a", { href, target: "_blank", rel: "noopener" }, item.title) : item.title),
      subtitle ? h("p", { class: "muted small" }, subtitle) : "",
      item.deadline ? h("p", { class: "home-deadline" }, "Deadline: ", dateLabel(item.deadline)) : "",
      item.summary ? h("p", { class: "home-summary" }, item.summary) : "",
      topicLabels.length ? h("p", { class: "home-topics" }, topicLabels.join(" · ")) : ""),
    h("div", { class: "home-item-actions" }, action));
}

function planForm(application, onSave) {
  const task = h("input", { value: application.next_action || "", maxlength: 180, "aria-label": "Next step",
    placeholder: "e.g. Follow up with the hiring manager" });
  const due = h("input", { type: "date", value: application.next_action_date || "", "aria-label": "Follow-up date" });
  const status = h("span", { "aria-live": "polite" });
  return h("details", { class: "home-plan" },
    h("summary", null, application.next_action ? "Edit next step" : "Plan a next step"),
    h("form", { class: "home-plan-form", onsubmit: async event => {
      event.preventDefault();
      const button = event.submitter;
      button.disabled = true;
      try {
        await api(`/api/applications/${application.id}`, {
          method: "POST", body: { next_action: task.value, next_action_date: due.value },
        });
        await onSave();
      } catch (error) {
        status.replaceChildren(message(error.message, true));
        button.disabled = false;
      }
    } },
      h("label", { class: "field" }, "Next step", task),
      h("label", { class: "field" }, "Remind me", due),
      h("button", { type: "submit", class: "secondary home-action" }, "Save reminder"),
      status));
}

function deadlineEntry(item) {
  const overdue = item.delta < 0;
  return h("li", { class: "home-deadline-item" },
    h("div", null,
      h("strong", null, item.title),
      h("p", { class: "muted small" }, item.kind === "deadline" ? "Opportunity deadline" : item.action || "Follow-up"),
      item.url ? h("a", { href: item.url, target: "_blank", rel: "noopener" }, "Open opportunity") : ""),
    h("span", { class: "home-date" + (overdue ? " overdue" : "") }, dateLabel(item.date)));
}

register({
  id: "home", title: "For you",
  async render(main) {
    const root = h("div");
    main.append(root);
    const storedProfile = await api("/api/account/profile");
    let { profile, saved } = readProfile(storedProfile.preferences);

    async function load() {
      const [jobData, newsData, applicationData] = await Promise.all([
        api("/api/jobs"), api("/api/news"), api("/api/applications"),
      ]);
      const jobs = jobData.jobs;
      const activeApps = applicationData.applications.filter(application => application.status !== "Rejected");
      const jobRecommendations = jobs.map(item => ({
        item, match: interestScore(item, profile),
      })).filter(({ item, match }) => !item.status && match.score > 0 &&
        (item.days_left == null || item.days_left >= 0) &&
        (!item.posted || dayDelta(item.posted) == null || dayDelta(item.posted) >= -60))
        .sort((a, b) => b.match.score - a.match.score ||
          (a.item.days_left ?? 9999) - (b.item.days_left ?? 9999) ||
          (b.item.posted || "").localeCompare(a.item.posted || "")).slice(0, 5);
      const newsRecommendations = newsData.items.map(item => ({
        item, match: interestScore(item, profile),
      })).filter(({ item, match }) => recent(item.published_at) && match.score > 0)
        .sort((a, b) => b.match.score - a.match.score ||
          (b.item.published_at || "").localeCompare(a.item.published_at || "")).slice(0, 5);
      const savedNews = newsData.items.filter(item => item.is_saved);
      const savedJobs = activeApps;
      const upcoming = [];
      for (const application of activeApps) {
        const deadlineDelta = dayDelta(application.deadline);
        if (deadlineDelta !== null && deadlineDelta >= 0 && deadlineDelta <= 14) {
          upcoming.push({ title: application.title, date: application.deadline, delta: deadlineDelta,
            kind: "deadline", url: application.url });
        }
        const actionDelta = dayDelta(application.next_action_date);
        if (actionDelta !== null && actionDelta <= 14) {
          upcoming.push({ title: application.title, date: application.next_action_date, delta: actionDelta,
            kind: "action", action: application.next_action, url: application.url });
        }
      }
      upcoming.sort((a, b) => a.delta - b.delta || a.title.localeCompare(b.title));
      const selectedTopics = TOPICS.filter(topic => profile.topics.includes(topic.id));
      const selectedAudiences = AUDIENCES.filter(([id]) => profile.audiences.includes(id)).map(([, label]) => label);
      const thisWeekJobs = jobRecommendations.filter(({ item }) => recent(item.posted, 7)).length;
      const thisWeekNews = newsRecommendations.length;
      const dueThisWeek = upcoming.filter(item => item.delta >= 0 && item.delta <= 7).length;
      const profileEditor = profileForm(profile, saved, async updated => {
        await api("/api/account/profile", { method: "POST", body: updated });
        profile = updated;
        saved = true;
        await load();
      });
      root.replaceChildren(
        h("header", { class: "home-heading" },
          h("div", null, h("p", { class: "home-eyebrow" }, "YOUR FORESTRY & BIOECONOMY DESK"),
            h("h1", null, "For you"),
            h("p", { class: "home-intro" }, "A focused view of opportunities, research and next steps—shaped around what you care about.")),
          h("a", { class: "btn secondary home-browse", href: "#/jobs" }, "Browse all jobs")),
        h("details", { class: "card home-preferences", open: !saved },
          h("summary", null, saved ? "Your focus" : "Set up your focus"),
          h("p", { class: "muted small" },
            `${selectedAudiences.length ? selectedAudiences.join(" · ") : "No audience selected"}${selectedTopics.length ? " — " + selectedTopics.map(topic => topic.label).join(" · ") : ""}`),
          profileEditor,
          h("p", { class: "muted small home-privacy" }, "Recommendations use transparent keyword matching, not AI. Your focus is private to your account.")),
        h("section", { class: "home-stats", "aria-label": "This week at a glance" },
          h("article", { class: "card home-stat" }, h("span", { class: "home-stat-value" }, jobRecommendations.length),
            h("span", null, "top job matches"), h("span", { class: "muted small" }, `${thisWeekJobs} posted this week`)),
          h("article", { class: "card home-stat" }, h("span", { class: "home-stat-value" }, newsRecommendations.length),
            h("span", null, "recent story matches"), h("span", { class: "muted small" }, "from the last 7 days")),
          h("article", { class: "card home-stat" }, h("span", { class: "home-stat-value" }, upcoming.length),
            h("span", null, "upcoming / overdue"), h("span", { class: "muted small" }, `${dueThisWeek} due this week`))),
        h("div", { class: "home-columns" },
          h("section", { class: "card home-section" },
            h("div", { class: "home-section-heading" }, h("div", null, h("p", { class: "home-eyebrow" }, "OPPORTUNITIES"),
              h("h2", null, "Jobs to explore")), h("a", { href: "#/jobs" }, "All jobs")),
            jobRecommendations.length ? h("div", { class: "home-list" }, jobRecommendations.map(({ item, match }) => {
              const actionArea = h("div");
              const saveButton = h("button", { type: "button", class: "secondary home-action",
                onclick: async event => {
                  event.target.disabled = true;
                  try {
                    await api(`/api/jobs/${item.id}/status`, { method: "POST", body: { status: "Saved" } });
                    await load();
                  } catch (error) {
                    actionArea.replaceChildren(message(error.message, true));
                  }
                } }, "Save job");
              actionArea.append(saveButton);
              return recommendationCard(item, "job", match, actionArea);
            })) : h("p", { class: "empty" }, "No clear job matches yet. Update your focus or browse all current listings."),
            h("div", { class: "home-section-footer" }, h("a", { href: "#/jobs" }, "Check for new jobs →"))),
          h("section", { class: "card home-section" },
            h("div", { class: "home-section-heading" }, h("div", null, h("p", { class: "home-eyebrow" }, "RESEARCH & INDUSTRY"),
              h("h2", null, "Worth a read")), h("a", { href: "#/news" }, "All news")),
            newsRecommendations.length ? h("div", { class: "home-list" }, newsRecommendations.map(({ item, match }) => {
              const actionArea = h("div");
              actionArea.append(h("button", { type: "button", class: "secondary home-action",
                "aria-pressed": item.is_saved ? "true" : "false",
                onclick: async event => {
                  event.target.disabled = true;
                  try {
                    await api(`/api/news/${item.id}/state`, {
                      method: "POST", body: { is_saved: !item.is_saved },
                    });
                    await load();
                  } catch (error) {
                    actionArea.replaceChildren(message(error.message, true));
                  }
                } }, item.is_saved ? "Saved" : "Save story"));
              return recommendationCard(item, "news", match, actionArea);
            })) : h("p", { class: "empty" }, "No recent stories match your focus. Visit News and refresh the feeds."),
            h("div", { class: "home-section-footer" }, h("a", { href: "#/news" }, "Open the News desk →")))),
        h("section", { class: "card home-section home-deadlines" },
          h("div", { class: "home-section-heading" }, h("div", null, h("p", { class: "home-eyebrow" }, "KEEP MOMENTUM"),
            h("h2", null, "Deadlines & next steps")), h("a", { href: "#/tracker" }, "Open tracker")),
          upcoming.length ? h("ul", { class: "home-deadline-list" }, upcoming.slice(0, 8).map(deadlineEntry))
            : h("p", { class: "empty" }, "No deadlines or reminders coming up. Save an opportunity and add a next step in the Tracker."),
          activeApps.length ? h("details", { class: "home-planner" },
            h("summary", null, "Plan a follow-up for a saved opportunity"),
            h("div", { class: "home-planner-list" }, activeApps.map(application =>
              h("article", { class: "home-planner-item" },
                h("strong", null, application.title),
                h("span", { class: "muted small" }, application.status),
                planForm(application, load))))) : ""),
        h("section", { class: "card home-section home-saved" },
          h("div", { class: "home-section-heading" }, h("div", null, h("p", { class: "home-eyebrow" }, "YOUR READING & JOB LIST"),
            h("h2", null, "Saved opportunities")), h("a", { href: "#/tracker" }, "Manage saved jobs")),
          savedJobs.length || savedNews.length
            ? h("div", { class: "home-saved-grid" },
              ...savedJobs.slice(0, 6).map(application => h("article", { class: "home-saved-item" },
                h("span", { class: "tag status", "data-status": application.status }, application.status),
                h("h3", null, application.url
                  ? h("a", { href: application.url, target: "_blank", rel: "noopener" }, application.title)
                  : application.title),
                h("p", { class: "muted small" }, [application.company, application.deadline ? `Deadline ${dateLabel(application.deadline)}` : ""].filter(Boolean).join(" · ")),
                application.next_action ? h("p", null, application.next_action,
                  application.next_action_date ? ` · ${dateLabel(application.next_action_date)}` : "") : "",
                planForm(application, load))),
              ...savedNews.slice(0, 6).map(item => h("article", { class: "home-saved-item" },
                h("span", { class: "tag" }, "News"),
                h("h3", null, h("a", { href: item.url, target: "_blank", rel: "noopener" }, item.title)),
                h("p", { class: "muted small" }, [item.source, item.published_at?.slice(0, 10)].filter(Boolean).join(" · ")),
                h("a", { href: "#/news" }, "Open in News"))))
            : h("p", { class: "empty" }, "Save jobs to your Tracker or stories from News and they will be collected here.")),
        h("p", { class: "muted small home-footnote" }, "This weekly view is based on your current Jobs, News and Tracker data. Keyword matching may miss relevant opportunities."));
    }

    await load();
  },
});
