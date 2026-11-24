import { api, getState, h, message, mountNav, register } from "../core.js";

function dateLabel(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(date);
}

register({
  id: "account", title: "Account",
  async render(main) {
    const state = await getState();
    const feedback = h("div", { "aria-live": "polite" });
    main.append(h("h1", null, "Account"),
      h("p", null, h("strong", null, state.user.name), " · ", state.user.email),
      h("p", { class: "muted" }, "Your CVs, applications, reading list and focus preferences are private to your account. Shared job ads are visible to members in the same field; news is visible to all members."),
      feedback);

    const LEVELS = [["none", "None yet"], ["basic", "Basic (A1–A2)"], ["intermediate", "Intermediate (B1–B2)"], ["fluent", "Fluent (C1 or native)"]];
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
        await mountNav();          // pages such as the forestry News desk follow the chosen fields
        fieldsFeedback.replaceChildren(message("Saved. Jobs, Match and What to study now use these fields."));
      } catch (error) { fieldsFeedback.replaceChildren(message(error.message, true)); }
    } },
      h("fieldset", null, h("legend", null, "Fields you are looking for work in"),
        ...state.fields.map(field => h("label", { class: "check" },
          h("input", { type: "checkbox", name: "fields", value: field.id, checked: state.user_fields.includes(field.id) }),
          ` ${field.label_en} (${field.label_fi})`))),
      h("label", { class: "field" }, "Your Finnish",
        h("select", { name: "finnish_level" }, LEVELS.map(([value, label]) =>
          h("option", { value, selected: state.finnish_level === value }, label)))),
      h("p", { class: "muted small" }, "Your Finnish level is used by the ranked shortlist: if you choose Fluent, ads that require Finnish aren't moved to the end. Nothing here is sent to an AI service."),
      h("button", { type: "submit" }, "Save fields"), fieldsFeedback);
    main.append(h("section", { class: "card account-section" }, h("h2", null, "Fields and Finnish"), fieldsForm));

    const aiFeedback = h("div", { "aria-live": "polite" });
    const aiToggle = h("input", { type: "checkbox", checked: state.llm_opt_in, onchange: async () => {
      try {
        const saved = await api("/api/account/ai", { method: "POST", body: { llm_opt_in: aiToggle.checked } });
        aiToggle.checked = saved.llm_opt_in;
        await getState(true);
        aiFeedback.replaceChildren(message(saved.llm_opt_in ? "AI drafting is on." : "AI drafting is off."));
      } catch (error) {
        aiToggle.checked = !aiToggle.checked;
        aiFeedback.replaceChildren(message(error.message, true));
      }
    } });
    main.append(h("section", { class: "card account-section" }, h("h2", null, "AI drafting"),
      h("p", null, "When this is on, drafting an application answer sends the question, the job ad and the facts from " +
        "the CV you choose (your education, experience, projects, skills, certificates, languages and hobbies; never your " +
        "name, email, phone, location or links) to an AI service (Anthropic's Claude API) to write a first draft. " +
        "Every sentence is then checked against your CV here, and nothing is sent to an employer."),
      h("p", { class: "muted small" }, state.llm.mode === "live"
        ? "This server has AI drafting available."
        : "This server runs in mock mode: drafts are made locally from your CV and nothing is sent to an AI service, whatever you choose here."),
      h("label", { class: "check" }, aiToggle, " Allow AI drafting with my CV facts (off by default)"), aiFeedback));

    const passwordFeedback = h("div", { "aria-live": "polite" });
    const passwordForm = h("form", { class: "account-form", onsubmit: async event => {
      event.preventDefault();
      const current = passwordForm.elements.current_password.value;
      const next = passwordForm.elements.new_password.value;
      if (next !== passwordForm.elements.confirm_password.value) {
        passwordFeedback.replaceChildren(message("The new passwords don't match.", true));
        return;
      }
      try {
        await api("/api/account/password", { method: "POST", body: {
          current_password: current, new_password: next,
        } });
        passwordForm.reset();
        passwordFeedback.replaceChildren(message("Password updated. Other active sessions have been signed out."));
      } catch (error) { passwordFeedback.replaceChildren(message(error.message, true)); }
    } },
      h("label", { class: "field" }, "Current password",
        h("input", { name: "current_password", type: "password", autocomplete: "current-password", required: true })),
      h("label", { class: "field" }, "New password (at least 12 characters)",
        h("input", { name: "new_password", type: "password", autocomplete: "new-password", minlength: 12, maxlength: 256, required: true })),
      h("label", { class: "field" }, "Confirm new password",
        h("input", { name: "confirm_password", type: "password", autocomplete: "new-password", minlength: 12, maxlength: 256, required: true })),
      h("button", { type: "submit" }, "Change password"), passwordFeedback);
    main.append(h("section", { class: "card account-section" },
      h("h2", null, "Change password"), passwordForm));

    if (state.user.is_admin) {
      const invitationArea = h("div");
      const invitationList = h("div", { class: "invite-list" });
      const codeArea = h("div", { "aria-live": "polite" });
      const createInvite = h("button", { onclick: async () => {
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
      invitationArea.append(
        h("p", { class: "muted" }, "Each invitation is single-use and expires after seven days. The code is displayed once; share it directly with a classmate."),
        createInvite, codeArea, invitationList);
      main.append(h("section", { class: "card account-section" },
        h("h2", null, "Invite classmates"), invitationArea));
      await loadInvitations();

      async function loadInvitations() {
        try {
          const { invitations } = await api("/api/account/invitations");
          invitationList.replaceChildren(...(invitations.length
            ? invitations.map(invite => h("p", { class: "invite-row" },
              h("strong", null, invite.used ? "Used" : new Date(invite.expires_at) < new Date() ? "Expired" : "Available"),
              ` · expires ${dateLabel(invite.expires_at)}`,
              invite.used_at ? ` · used ${dateLabel(invite.used_at)}` : ""))
            : [h("p", { class: "muted" }, "No invitations created yet.")]));
        } catch (error) { invitationList.replaceChildren(message(error.message, true)); }
      }
    }

    main.append(h("section", { class: "card account-section" },
      h("h2", null, "Your data"),
      h("p", { class: "muted" }, "Download a copy of your CVs, applications, preferences and saved/read news state."),
      h("a", { class: "btn secondary", href: "/api/account/export", download: "jobdesk-account-data.json" }, "Download my data")));

    const deleteFeedback = h("div", { "aria-live": "polite" });
    const deleteForm = h("form", { class: "account-form", onsubmit: async event => {
      event.preventDefault();
      try {
        await api("/api/account/delete", { method: "POST", body: { password: deleteForm.elements.delete_password.value } });
        window.location.reload();
      } catch (error) { deleteFeedback.replaceChildren(message(error.message, true)); }
    } },
      h("p", null, "Deletes your account, CVs, applications, settings, reading list and feedback, straight away. " +
        "Job ads you shared stay visible to others, without your name. This can't be undone; download your data first if you want a copy."),
      h("label", { class: "field" }, "Your password, to confirm",
        h("input", { name: "delete_password", type: "password", autocomplete: "current-password", required: true })),
      h("button", { type: "submit", class: "danger secondary" }, "Delete my account"), deleteFeedback);
    if (!state.user.is_admin || state.user.id !== 1) {
      main.append(h("section", { class: "card account-section" }, h("h2", null, "Delete my account"), deleteForm));
    }

    main.append(h("div", { class: "row" },
      h("button", { class: "secondary", onclick: async () => {
        try {
          await api("/api/auth/logout", { method: "POST", body: {} });
          window.location.reload();
        } catch (error) { feedback.replaceChildren(message(error.message, true)); }
      } }, "Sign out")));
  },
});
