import { api, getState, h } from "./core.js";

// First-login setup: shown until the member has chosen fields and has at least one CV.
export async function gettingStarted() {
  const [state, { cvs }] = await Promise.all([getState(), api("/api/cvs")]);
  const hasFields = Array.isArray(state.preferences.fields) && state.preferences.fields.length > 0;
  if (hasFields && cvs.length) return "";
  const step = (done, text, link, label) => h("li", null, done ? "✓ " : "", text, " ",
    done ? h("span", { class: "muted small" }, "(done)") : h("a", { href: link }, label));
  return h("section", { class: "card", "aria-labelledby": "getting-started" },
    h("h2", { id: "getting-started" }, "Get started in three steps"),
    h("ol", null,
      step(hasFields, "Choose the fields you're looking for work in, and your Finnish level.", "#/account", "Open Account"),
      step(cvs.length > 0, "Add a CV: it's used for matching and for drafting answers, and stays private.", "#/cvs", "Create a CV"),
      step(false, "Paste some internship ads to see which ones you can apply to without Finnish.", "#/shortlist", "Open Shortlist")));
}

