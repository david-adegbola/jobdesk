import { api, h, register, message } from "../core.js";

// Hands an unsaved CV draft to the My CVs page, which opens it in the editor.
export const DRAFT_KEY = "jobdesk:cv-draft";

function skillList(items, cls, empty) {
  if (!items.length) return h("p", { class: "muted small" }, empty);
  return h("ul", { class: "skill-list" }, items.map(s => h("li", null,
    h("span", { class: "tag " + cls }, s.label),
    h("span", { class: "muted small" }, ` ${s.jobs} ad${s.jobs === 1 ? "" : "s"} (${s.percent}%)`),
    s.hint ? h("div", { class: "muted small" }, s.hint) : "")));
}

register({
  id: "study", title: "What to study",
  async render(main) {
    const d = await api("/api/skills");
    const status = h("div", { role: "status" });
    main.append(h("h1", null, "What to study"),
      h("p", { class: "muted" },
        `Skills that the ${d.total_jobs} jobs listed here ask for, grouped by type of role and compared with your ${d.cv_count} CV${d.cv_count === 1 ? "" : "s"}. ` +
        "“Study next” lists skills the ads mention that none of your CVs shows. These are keyword matches in Finnish and English, not an AI assessment; the number of ads behind each skill is shown."),
      h("p", { class: "muted small" },
        `${d.jobs_with_ad_text} of the jobs have their full ad saved; the rest are judged by title only, so skill counts are lower than in reality. ` +
        "Use “read full ad” on the Jobs page to add more."),
      d.cv_count ? "" : h("p", null, "You have no CVs yet, so every skill is listed. ", h("a", { href: "#/cvs" }, "Create a CV"), " to see what you already cover."),
      status);

    async function startCv(role, button) {
      button.disabled = true;
      try {
        const { cv } = await api(`/api/skills/draft/${encodeURIComponent(role.id)}`);
        try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(cv)); }
        catch (error) { throw new Error("Your browser blocked storing the draft. Allow site storage and try again."); }
        location.hash = "#/cvs";
      } catch (err) {
        status.replaceChildren(message(err.message, true));
        button.disabled = false;
      }
    }

    if (!d.role_types.length) {
      main.append(h("p", { class: "empty" }, "No jobs are listed yet, so there is nothing to compare."));
      return;
    }
    for (const role of d.role_types) {
      const button = h("button", { type: "button" }, "Start a CV for this role");
      button.addEventListener("click", () => startCv(role, button));
      main.append(h("section", { class: "card study-role", "aria-labelledby": `role-${role.id}` },
        h("h2", { id: `role-${role.id}` }, role.label,
          role.personal ? h("span", { class: "tag" }, "Only you") : ""),
        h("p", { class: "muted small" },
          `${role.jobs} job${role.jobs === 1 ? "" : "s"}` +
          (role.internships ? `, ${role.internships} internship or summer job${role.internships === 1 ? "" : "s"}` : "") +
          ` · ${role.with_ad_text} with the full ad`),
        h("div", { class: "grid" },
          h("div", null, h("h3", null, "Study next"),
            skillList(role.study, "warn", d.cv_count
              ? "Nothing that two or more ads ask for is missing from your CVs."
              : "Not enough ad text yet to suggest skills.")),
          h("div", null, h("h3", null, "Already in your CVs"),
            skillList(role.have, "new", "None of the skills these ads mention yet."))),
        h("p", { class: "muted small" }, "For example: ",
          ...role.examples.flatMap((job, i) => [i ? "; " : "",
            job.url ? h("a", { href: job.url, target: "_blank", rel: "noopener" }, job.title) : job.title])),
        h("div", { class: "row" }, button,
          h("span", { class: "muted small" }, role.closest_cv
            ? `Starts from your closest CV, “${role.closest_cv.title}”. Skills to study go on a “Want to learn” row; nothing is saved until you save it.`
            : "Starts an empty CV with the skills to study on a “Want to learn” row; nothing is saved until you save it."))));
    }
  },
});
