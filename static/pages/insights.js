import { api, h, register } from "../core.js";

register({
  id: "insights", title: "Insights",
  async render(main) {
    const d = await api("/api/insights");
    const top = Math.max(1, ...d.skills_gap.map(g => g.jobs));     // bars are relative to the most common blocker
    const bar = n => h("div", { style: `background: var(--bad-fg); height: 8px; border-radius: 4px; width: ${Math.max(2, 100 * n / top)}%` });
    main.append(h("h1", null, "Insights"),
      h("h2", null, "Skills gap"),
      h("p", { class: "muted" }, `How often each blocker appears across all ${d.total_jobs} jobs saved here, most common first: ` +
        `the course or licence to get next is at the top. Only ${d.jobs_with_ad_text} of them ${d.jobs_with_ad_text === 1 ? "has" : "have"} the full ad text; ` +
        "the rest are checked by title only, so the real numbers are higher. Use “read full ad” on the Jobs page to improve them."),
      h("div", { class: "scroll" }, h("table", null,
        h("thead", null, h("tr", null, ["Blocker", "Jobs", "Share", ""].map(t => h("th", null, t)))),
        h("tbody", null, d.skills_gap.length ? d.skills_gap.map(g => h("tr", null,
          h("td", null, h("span", { class: "tag bad" }, g.blocker)), h("td", null, g.jobs),
          h("td", null, `${g.percent}%`), h("td", { style: "width: 40%" }, bar(g.jobs))))
          : h("tr", null, h("td", { colspan: 4, class: "empty" }, "No blockers found yet."))))),
      h("h2", null, "Funnel per CV"),
      h("p", { class: "muted" }, "How far applications got with each CV. A job counts at every stage it reached, even if rejected later."),
      h("div", { class: "scroll" }, h("table", null,
        h("thead", null, h("tr", null, ["CV", "Saved", "Applied", "Interview", "Offer", "Rejected"].map(t => h("th", null, t)))),
        h("tbody", null, d.funnel.length ? d.funnel.map(f => h("tr", null,
          h("td", null, f.role), h("td", null, f.saved), h("td", null, f.applied), h("td", null, f.interview),
          h("td", null, f.offer), h("td", null, f.rejected)))
          : h("tr", null, h("td", { colspan: 6, class: "empty" }, "No applications yet. Set a status on the Jobs page."))))));
  },
});
