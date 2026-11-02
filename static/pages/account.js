import { api, getState, h, message, register } from "../core.js";

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
      h("p", { class: "muted" }, "Your CVs, applications, reading list and focus preferences are private to your account. Shared forestry opportunities and news are visible to all members."),
      feedback);

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
        finally { createInvite.disabled = false; }
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

    main.append(h("div", { class: "row" },
      h("button", { class: "secondary", onclick: async () => {
        try {
          await api("/api/auth/logout", { method: "POST", body: {} });
          window.location.reload();
        } catch (error) { feedback.replaceChildren(message(error.message, true)); }
      } }, "Sign out")));
  },
});
