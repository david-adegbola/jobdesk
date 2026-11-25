// Profile → Account: who you are, how far you've come (from your own jobs and tracker), and the settings.
import { api, getState, h, message, mountNav, register } from "../core.js";

function dateLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(date);
}

const LEVELS = [["none", "None yet"], ["basic", "Basic (A1–A2)"], ["intermediate", "Intermediate (B1–B2)"], ["fluent", "Fluent (C1 or native)"]];
const SHORT_LEVEL = { none: "–", basic: "A2", intermediate: "B1", fluent: "C1" };

function initials(user) {
  const words = String(user?.name || user?.email || "?").split(/[\s@._-]+/).filter(Boolean);
  return words.slice(0, 2).map(w => w[0].toUpperCase()).join("") || "?";
}

// One settings row: what it is, what it does now, and its control. A fold-out row opens its form below.
function settingRow(title, description, control, body, action = "Change") {
  const row = h("div", { class: "setting" },
    h("div", { class: "setting-text" }, h("strong", null, title), h("span", { class: "muted small" }, description)),
    control || "");
  if (!body) return row;
  const details = h("details", { class: "setting-details" }, h("summary", { class: "setting" },
    h("div", { class: "setting-text" }, h("strong", null, title), h("span", { class: "muted small" }, description)),
    h("span", { class: "btn secondary small", "aria-hidden": "true" }, action)), body);
  return details;
}

register({
  id: "account", title: "Account",
  async render(main) {
    const state = await getState();
    const feedback = h("div", { "aria-live": "polite" });
    const [{ jobs }, apps] = await Promise.all([api("/api/jobs"), api("/api/applications").catch(() => ({ applications: [] }))]);
    const checked = jobs.filter(j => j.fit).length;
    const sent = jobs.filter(j => ["Applied", "Interview", "Offer"].includes(j.status)).length;
    const interviews = jobs.filter(j => j.status === "Interview").length;
    const fieldNames = state.fields.filter(f => state.user_fields.includes(f.id)).map(f => f.label_en);
    const levelName = (LEVELS.find(([v]) => v === state.finnish_level) || LEVELS[0])[1];

    main.append(
      h("div", { class: "profile-head" },
        h("span", { class: "avatar profile-avatar", "aria-hidden": "true" }, initials(state.user)),
        h("div", null, h("h1", null, state.user.name), h("p", { class: "muted" }, state.user.email))),
      feedback);

    // ---- left: progress
    const progress = h("section", { class: "profile-progress", "aria-labelledby": "progress-title" },
      h("h2", { id: "progress-title", class: "visually-hidden" }, "Your progress"),
      h("div", { class: "profile-blocks" },
        h("a", { class: "dash-block butter", href: "#/myjobs" }, h("span", { class: "dash-number" }, String(checked)),
          h("span", null, checked === 1 ? "job checked against your CV" : "jobs checked against your CV")),
        h("a", { class: "dash-block cobalt-block", href: "#/tracker" }, h("span", { class: "dash-number" }, String(sent)),
          h("span", null, `${sent === 1 ? "application" : "applications"} sent${interviews ? `, ${interviews} at interview` : ""}`)),
        h("div", { class: "dash-block coral" }, h("span", { class: "dash-number" }, SHORT_LEVEL[state.finnish_level] || "–"),
          h("span", null, `Finnish: ${levelName.toLowerCase()}`))),
      h("a", { class: "profile-study", href: "#/study" },
        h("span", null, h("strong", null, "Skills to learn next"),
          h("span", { class: "muted" }, "What to study shows the skills your saved jobs ask for that your CV doesn't show, and drafts a CV for that kind of role.")),
        h("span", { class: "btn secondary small", "aria-hidden": "true" }, "Open")),
      h("p", { class: "muted small" }, "Your CVs, applications and preferences are private to your account. Job ads you share are visible to all members."));

    // ---- right: settings
    const fieldsFeedback = h("div", { "aria-live": "polite" });
    const fieldsForm = h("form", { class: "account-form", onsubmit: async event => {
      event.preventDefault();
      const fields = [...fieldsForm.querySelectorAll("input[name=fields]:checked")].map(input => input.value);
      if (!fields.length) {
        fieldsFeedback.replaceChildren(message("Choose at least one field.", true));
        return;
      }
      try {
        await api("/api/account/fields", { method: "POST", body: { fields, finnish_level: fieldsForm.elements.finnish_level.value } });
        await getState(true);
        await mountNav();          // pages tied to a field follow the chosen fields
        fieldsFeedback.replaceChildren(message("Saved. Jobs, Match and What to study now use these fields."));
      } catch (error) { fieldsFeedback.replaceChildren(message(error.message, true)); }
    } },
      h("fieldset", null, h("legend", null, "Fields you are looking for work in"),
        h("div", { class: "field-checks" }, ...state.fields.map(field => h("label", { class: "check" },
          h("input", { type: "checkbox", name: "fields", value: field.id, checked: state.user_fields.includes(field.id) }),
          ` ${field.label_en} (${field.label_fi})`)))),
      h("label", { class: "field" }, "Your Finnish",
        h("select", { name: "finnish_level" }, LEVELS.map(([value, label]) =>
          h("option", { value, selected: state.finnish_level === value }, label)))),
      h("p", { class: "muted small" }, "Your Finnish level orders the shortlist (if you choose Fluent, ads that require Finnish aren't moved to the end) and sets the honest Finnish line in your letters. Nothing here is sent to an AI service."),
      h("button", { type: "submit" }, "Save fields"), fieldsFeedback);

    const aiFeedback = h("div", { "aria-live": "polite" });
    const aiToggle = h("input", { type: "checkbox", role: "switch", class: "switch", "aria-label": "AI with your CV", checked: state.llm_opt_in, onchange: async () => {
      try {
        const saved = await api("/api/account/ai", { method: "POST", body: { llm_opt_in: aiToggle.checked } });
        aiToggle.checked = saved.llm_opt_in;
        await getState(true);
        aiDescription.textContent = aiText(saved.llm_opt_in);
        aiFeedback.replaceChildren(message(saved.llm_opt_in ? "AI with your CV is on." : "AI with your CV is off."));
      } catch (error) {
        aiToggle.checked = !aiToggle.checked;
        aiFeedback.replaceChildren(message(error.message, true));
      }
    } });
    const aiText = on => on ? "On: CV facts (never your name or contacts) go to the AI to write and check text."
      : "Off: jobs are compared with your CV word by word, and letters copy your CV facts. Nothing goes to an AI service.";
    const aiDescription = h("span", null, aiText(state.llm_opt_in));
    const aiRow = h("div", { class: "setting-block" },
      settingRow("AI with your CV", aiDescription, aiToggle),
      h("details", { class: "small setting-more" }, h("summary", null, "What is sent, and when"),
        h("p", null, "Two things use an AI service (Anthropic's Claude API) when this is on: drafting text (answers, letters) and comparing a job with your CV when you shortlist it. " +
          "They send the job ad (and the question) with the facts from the CV you use: your education, experience, projects, skills, certificates, languages and hobbies; " +
          "never your name, email, phone, location or links. The results are checked against your CV and the ad here, and nothing is sent to an employer."),
        h("p", { class: "muted" }, state.llm.mode === "live" ? "This server has AI available."
          : "This server runs in mock mode: drafts and comparisons are made locally from your CV and nothing is sent to an AI service, whatever you choose here.")),
      aiFeedback);

    const deleteFeedback = h("div", { "aria-live": "polite" });
    const deleteForm = h("form", { class: "account-form", onsubmit: async event => {
      event.preventDefault();
      try {
        await api("/api/account/delete", { method: "POST", body: { confirm_email: deleteForm.elements.confirm_email.value } });
        window.location.reload();
      } catch (error) { deleteFeedback.replaceChildren(message(error.message, true)); }
    } },
      h("p", null, "Deletes your account, CVs, applications, settings and feedback, straight away. " +
        "Job ads you shared stay visible to others, without your name. This can't be undone; download your data first if you want a copy."),
      h("label", { class: "field" }, `Type your email address (${state.user.email}) to confirm`,
        h("input", { name: "confirm_email", type: "email", autocomplete: "off", required: true })),
      h("button", { type: "submit", class: "danger secondary" }, "Delete my account"), deleteFeedback);

    const settings = h("section", { class: "card profile-settings", "aria-labelledby": "settings-title" },
      h("h2", { id: "settings-title" }, "Settings"),
      h("div", { id: "profile-fields" }, settingRow("Fields and Finnish",
        `${fieldNames.join(", ") || "No fields yet"} · Finnish: ${levelName}`, null, fieldsForm)),
      aiRow,
      settingRow("Download my data", "Your CVs, applications and preferences (and any news stories you saved earlier), as JSON.",
        h("a", { class: "btn secondary small", href: "/api/account/export", download: "jobdesk-account-data.json" }, "Download")));

    if (state.user.is_admin) {
      const invitationList = h("div", { class: "invite-list" });
      const codeArea = h("div", { "aria-live": "polite" });
      const createInvite = h("button", { class: "small", onclick: async () => {
        createInvite.disabled = true;
        try {
          const invite = await api("/api/account/invitations", { method: "POST", body: {} });
          codeArea.replaceChildren(
            message(`Invitation created. Share this one-time code before ${dateLabel(invite.expires_at)}; it will only be shown here once.`),
            h("label", { class: "field" }, "Invitation code",
              h("input", { value: invite.code, readonly: true, "aria-label": "New invitation code" })),
            h("button", { class: "secondary", onclick: async () => {
              try {
                await navigator.clipboard.writeText(invite.code);
                codeArea.prepend(message("Invitation code copied."));
              } catch (error) {
                codeArea.prepend(message("Copy was unavailable. Select and copy the code above.", true));
              }
            } }, "Copy code"));
          await loadInvitations();
        } catch (error) { codeArea.replaceChildren(message(error.message, true)); }
        finally {
          createInvite.disabled = false;
          createInvite.focus();
        }
      } }, "Create invitation");
      settings.append(h("div", { class: "setting-block" },
        settingRow("Invite classmates", "Single-use codes that expire after seven days. Each is shown once.", createInvite), codeArea, invitationList));
      async function loadInvitations() {
        try {
          const { invitations } = await api("/api/account/invitations");
          invitationList.replaceChildren(...(invitations.length
            ? invitations.map(invite => h("p", { class: "invite-row small" },
              h("strong", null, invite.used ? "Used" : new Date(invite.expires_at) < new Date() ? "Expired" : "Available"),
              ` · expires ${dateLabel(invite.expires_at)}`,
              invite.used_at ? ` · used ${dateLabel(invite.used_at)}` : ""))
            : [h("p", { class: "muted small" }, "No invitations created yet.")]));
        } catch (error) { invitationList.replaceChildren(message(error.message, true)); }
      }
      await loadInvitations();

      // Employer ads waiting for review (the public form at /employers.html)
      const reviewList = h("div", { "aria-live": "polite" });
      settings.append(h("div", { class: "setting-block" },
        settingRow("Employer ads to review", h("span", null, "Ads sent with the public ",
          h("a", { href: "/employers.html" }, "Post a job"), " form. Nothing is published until you approve it."), null),
        reviewList));
      async function loadSubmissions() {
        try {
          const { submissions, keep_days } = await api("/api/admin/submissions");
          const pending = submissions.filter(s => s.status === "pending");
          const decide = (s, decision) => async () => {
            try {
              await api(`/api/admin/submissions/${s.id}`, { method: "POST", body: { decision } });
              await loadSubmissions();
            } catch (error) { reviewList.prepend(message(error.message, true)); }
          };
          reviewList.replaceChildren(...(pending.length ? pending.map(s => h("article", { class: "submission" },
            h("strong", null, `${s.data.title} · ${s.employer}`),
            h("span", { class: "muted small" }, [s.data.municipality || (s.data.work_mode === "remote" ? "Remote" : "No town"),
              `apply: ${s.data.apply_url}`, `contact: ${s.contact_name ? `${s.contact_name}, ` : ""}${s.contact_email}`,
              `sent ${dateLabel(s.created_at)}`].join(" · ")),
            h("div", { class: "submission-text small" }, s.data.description),
            h("div", { class: "row" },
              h("button", { class: "small", onclick: decide(s, "approve") }, "Approve and publish"),
              h("button", { class: "small secondary danger", onclick: decide(s, "reject") }, "Reject"))))
            : [h("p", { class: "muted small" }, `No ads waiting. Decided ads and the employer's contact details are deleted after ${keep_days} days.`)]));
        } catch (error) { reviewList.replaceChildren(message(error.message, true)); }
      }
      await loadSubmissions();
    }

    if (!state.user.is_admin || state.user.id !== 1) {
      const del = settingRow("Delete my account", "Removes your CVs, jobs, documents and history.", null, deleteForm, "Delete…");
      del.classList.add("is-danger");
      settings.append(del);
    }
    settings.append(h("div", { class: "row" },
      h("button", { class: "secondary", onclick: async () => {
        try {
          await api("/api/auth/logout", { method: "POST", body: {} });
          window.location.reload();
        } catch (error) { feedback.replaceChildren(message(error.message, true)); }
      } }, "Sign out")));

    main.append(h("div", { class: "profile-columns" }, progress, settings));
  },
});
