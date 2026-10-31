import { api, h, register, message, getState } from "../core.js";

register({
  id: "prompt", title: "New CV prompt",
  async render(main, query) {
    const params = new URLSearchParams(query);
    const { jobs } = await api("/api/jobs");
    const rank = j => (j.status ? 0 : 1);
    jobs.sort((a, b) => rank(a) - rank(b) || (b.posted || "").localeCompare(a.posted || ""));

    const area = h("div");
    const picker = h("select", { onchange: () => choose() },
      h("option", { value: "" }, "Choose a job…"),
      h("option", { value: "paste" }, "Paste an ad instead"),
      jobs.map(j => h("option", { value: j.id, selected: String(j.id) === params.get("job") },
        `${j.status ? `[${j.status}] ` : ""}${j.title}${j.company ? ` – ${j.company}` : ""}`)));
    main.append(h("h1", null, "New CV prompt"),
      h("p", { class: "muted" }, "Builds the prompt for Claude Code from your rules. It asks first about anything the ad raises that " +
        "your facts don't answer, and makes no prompt until you've answered."),
      h("label", { class: "field" }, "Job", picker), area);

    let pasted = null;
    async function choose() {
      area.textContent = "";
      if (picker.value === "paste") return pasteForm();
      if (!picker.value) return;
      const analysis = await api(`/api/email-prompt/${picker.value}`, { method: "POST", body: { analyse_only: true } });
      showForm(analysis, `/api/prompt/${picker.value}`, Number(picker.value));
    }

    function pasteForm() {
      const f = {};
      const field = (n, label, tag = "input") => h("label", { class: "field" }, label, f[n] = h(tag, { name: n }));
      area.append(h("form", { class: "card grid", onsubmit: async e => {
          e.preventDefault();
          pasted = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value]));
          const analysis = await api("/api/email-prompt", { method: "POST", body: { job: pasted, analyse_only: true } });
          area.querySelector(".prompt-form")?.remove();
          showForm(analysis, "/api/prompt", null);
        } },
        field("title", "Job title"), field("company", "Company"), field("location", "Place"), field("url", "Link"),
        h("label", { class: "field", style: "grid-column: 1 / -1" }, "Ad text", f.ad_text = h("textarea", { name: "ad_text" })),
        h("div", null, h("button", { type: "submit" }, "Read the ad"))));
    }

    async function showForm(an, endpoint, jobId) {
      const out = h("div");
      const inputs = {};
      const emailOnly = params.get("kind") === "email";      // opened from a job row's "Email prompt" link
      const emailEndpoint = jobId ? `/api/email-prompt/${jobId}` : "/api/email-prompt";
      const { roles } = await getState();
      const sendCv = an.suggested_cv || an.closest;
      inputs.cv_role = h("select", null, roles.map(r => h("option", { value: r.slug, selected: r.slug === sendCv, title: r.title }, r.slug)));
      async function run(url) {
        const answers = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
        const r = await api(url, { method: "POST", body: { answers, job: pasted } });
        if (r.missing && r.missing.length) {
          out.replaceChildren(h("div", { class: "msg err", role: "alert" }, "Still needed:", h("ul", null, r.missing.map(x => h("li", null, x)))));
          return;
        }
        const copyBtn = h("button", { onclick: async () => {
            try { await navigator.clipboard.writeText(r.prompt); copyBtn.textContent = "Copied"; }
            catch (err) { copyBtn.textContent = "Select the text and copy it"; }
          } }, "Copy prompt");
        out.replaceChildren(h("div", { class: "row" }, copyBtn,
            r.saved ? h("span", { class: "muted small" }, "Saved in this job's tracker notes.") : ""),
          h("pre", { class: "prompt" }, r.prompt));
      }
      const text = (id, label, value) => h("label", { class: "field" }, label, inputs[id] = h("input", { value: value || "" }));
      const mode = h("select", null,
        h("option", { value: "new" }, "Make a new tailored CV"),
        h("option", { value: "existing" }, `Use the existing CV: ${an.closest}`));
      inputs.mode = mode;
      const languageNotes = { "fi-first": "Finnish main", "en-first": "English main", "en-only": "English only" };
      const language = h("select", null, Object.entries(languageNotes).map(([v, note]) =>
        h("option", { value: v, selected: v === an.defaults.language }, `${v} (${note})`)));
      inputs.language = language;
      const questions = an.questions.map(q => q.kind === "yesno"
        ? h("label", { class: "field" }, q.question, inputs[q.id] = h("select", null,
            h("option", { value: "" }, "Choose…"), h("option", { value: "yes" }, "Yes"), h("option", { value: "no" }, "No")))
        : text(q.id, q.question, ""));
      area.append(h("div", { class: "prompt-form" },
        !an.has_ad_text ? h("p", { class: "msg err" }, "Only the job title is known, so keywords and blockers are thin. ",
          jobId ? h("button", { class: "link", onclick: async e => {
            e.target.textContent = "Reading the ad…";
            try { await api(`/api/jobs/${jobId}/fetch`, { method: "POST" }); choose(); }
            catch (err) { e.target.textContent = err.message; }
          } }, "Read the full ad first") : "Paste the ad text.") : "",
        h("div", { class: "card" },
          h("p", null, h("strong", null, "Closest existing role: "), `${an.closest} (match ${an.closest_score})`),
          h("p", null, h("strong", null, "Keywords from the ad that match your facts: "), an.keywords.join(", ") || "none"),
          h("p", null, h("strong", null, "Blockers: "), an.blockers.length ? an.blockers.map(b => h("span", { class: "tag bad" }, b)) : "none"),
          h("p", null, h("strong", null, "Tags: "), an.tags.join(", ") || "none")),
        h("h2", null, "Answer before the prompt is made"),
        h("form", { class: "grid", onsubmit: e => { e.preventDefault(); run(emailOnly ? emailEndpoint : endpoint); } },
          emailOnly ? "" : [
            h("label", { class: "field" }, "What to do", mode),
            h("label", { class: "field" }, "Language (new CV; an existing CV keeps its own: " + an.closest_language + ")", language),
            text("slug", "New role folder (job type, not the employer)", an.defaults.slug),
            text("role_fi", "Finnish role title (footer; not needed for en-only)", an.defaults.role_fi),
            text("role_en", "English role title (footer)", an.defaults.role_en)],
          questions,
          h("label", { class: "field" }, "CV to send (for the application email)", inputs.cv_role),
          h("div", { class: "row", style: "grid-column: 1 / -1" },
            emailOnly ? "" : h("button", { type: "submit" }, "Make the prompt"),
            h("button", { type: emailOnly ? "submit" : "button", class: emailOnly ? "" : "secondary",
              onclick: emailOnly ? null : () => run(emailEndpoint) }, "Application email prompt"))),
        out));
    }

    if (picker.value) choose();
  },
});
