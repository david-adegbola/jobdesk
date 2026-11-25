// The public "Post a job" form (employers.html). No account: the ad waits for an administrator's approval.
import { h, message } from "./core.js";
import { LABELS } from "./labels.js";

async function getJSON(path, options) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const field = (label, input, hint) => h("label", { class: "field" }, label, input, hint ? h("span", { class: "muted small" }, hint) : "");
const checks = (name, items) => h("div", { class: "field-checks" }, ...items.map(([value, text]) =>
  h("label", { class: "check" }, h("input", { type: "checkbox", name, value }), ` ${text}`)));
const fieldset = (legend, ...children) => h("fieldset", { class: "card employer-section" }, h("legend", null, legend), ...children);
const select = (name, options, blank = "Not stated") =>
  h("select", { name }, h("option", { value: "" }, blank), ...options.map(([v, t]) => h("option", { value: v }, t)));
const pairs = group => Object.entries(LABELS[group]).map(([code, [en]]) => [code, en]);

function townSelect(options) {
  const byRegion = new Map(options.regions.map(r => [r.code, []]));
  for (const m of options.municipalities) byRegion.get(m.region)?.push(m);
  return h("select", { name: "municipality_code" }, h("option", { value: "" }, "Remote or several places"),
    ...options.regions.map(r => h("optgroup", { label: `${r.en}${r.en !== r.fi ? ` (${r.fi})` : ""}` },
      ...byRegion.get(r.code).map(m => h("option", { value: m.code }, m.fi === m.sv ? m.fi : `${m.fi} (${m.sv})`)))));
}

function render(root, options) {
  const feedback = h("div", { "aria-live": "polite" });
  const asap = h("input", { type: "checkbox", name: "asap" });
  const form = h("form", { class: "employer-form", novalidate: true, onsubmit: async event => {
    event.preventDefault();
    const data = new FormData(form);
    const all = name => data.getAll(name);
    const num = name => (data.get(name) === "" ? null : Number(data.get(name)));
    const flag = name => (data.get(name) === "" ? null : data.get(name) === "yes");
    const body = {
      title: data.get("title"), employer: data.get("employer"), description: data.get("description"),
      apply_url: data.get("apply_url"), fields: all("fields"), municipality_code: data.get("municipality_code"),
      work_mode: data.get("work_mode") || "", levels: all("levels"), employment_types: all("employment_types"),
      deadline: data.get("deadline"), start_date: asap.checked ? "asap" : data.get("start_date"),
      salary_min: num("salary_min"), salary_max: num("salary_max"), salary_period: data.get("salary_period"),
      tes: data.get("tes"), paid: flag("paid"), internship_credits: num("internship_credits"),
      combinable_with_studies: data.get("combinable_with_studies") ? true : null,
      lang_fi: data.get("lang_fi"), lang_en: data.get("lang_en"), lang_sv: data.get("lang_sv"),
      permits: all("permits"), employer_sector: data.get("employer_sector"),
      contact_name: data.get("contact_name"), contact_email: data.get("contact_email"),
      consent: data.get("consent") === "on", website: data.get("website"),
    };
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    feedback.replaceChildren();
    try {
      const result = await getJSON("/api/employers/jobs", { method: "POST", body: JSON.stringify(body) });
      root.replaceChildren(h("section", { class: "card" }, h("h2", null, "Thank you"), message(result.message),
        h("p", null, h("a", { href: "/employers.html" }, "Post another job"))));
      root.querySelector("h2").focus?.();
    } catch (error) {
      feedback.replaceChildren(message(error.message, true));
      button.disabled = false;
    }
  } },
    fieldset("The job",
      field("Job title *", h("input", { name: "title", required: true, maxlength: 150, autocomplete: "off" })),
      field("Employer *", h("input", { name: "employer", required: true, maxlength: 120, autocomplete: "organization" })),
      h("div", { class: "field" }, h("span", null, "Career fields * (up to three)"),
        checks("fields", options.fields.map(f => [f.id, `${f.en} (${f.fi})`]))),
      field("Description *", h("textarea", { name: "description", required: true, rows: 10, maxlength: 20000 }),
        "What the work is, who you are looking for and what you offer. At least 80 characters."),
      field("Where to apply *", h("input", { name: "apply_url", required: true, maxlength: 500, inputmode: "url" }),
        "A web address (https://…) or an email address.")),
    fieldset("Place and type",
      field("Town", townSelect(options)),
      field("Work mode", select("work_mode", pairs("mode"))),
      h("div", { class: "field" }, h("span", null, "Level"), checks("levels", pairs("level"))),
      h("div", { class: "field" }, h("span", null, "Type of employment"), checks("employment_types", pairs("employment"))),
      h("div", { class: "two-col" },
        field("Application deadline", h("input", { name: "deadline", type: "date" }),
          "Without a deadline the ad is listed for 60 days."),
        h("div", { class: "field" }, h("span", null, "Start date"), h("input", { name: "start_date", type: "date", "aria-label": "Start date" }),
          h("label", { class: "check" }, asap, " As soon as possible"))),
      field("Employer type", select("employer_sector", pairs("sector")))),
    fieldset("Pay and terms",
      h("div", { class: "two-col" },
        field("Pay from (€)", h("input", { name: "salary_min", type: "number", min: 1, step: "0.01", inputmode: "decimal" })),
        field("Pay up to (€)", h("input", { name: "salary_max", type: "number", min: 1, step: "0.01", inputmode: "decimal" }))),
      field("Per", select("salary_period", pairs("period").map(([v, t]) => [v, t.replace("/ ", "")]), "Choose")),
      field("Collective agreement (TES)", h("input", { name: "tes", maxlength: 80 }), "For example KVTES or the agreement of your industry."),
      h("div", { class: "two-col" },
        field("Is an internship paid?", select("paid", [["yes", "Paid"], ["no", "Unpaid"]])),
        field("Study credits (op / ECTS)", h("input", { name: "internship_credits", type: "number", min: 1, max: 60 }))),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "combinable_with_studies" }), " Can be done alongside studies")),
    fieldset("Languages and permits",
      h("p", { class: "muted small" }, "Many international students search for jobs where Finnish isn't required. Say so if it isn't."),
      h("div", { class: "two-col" },
        field("Finnish", select("lang_fi", [["required", "Required"], ["preferred", "An advantage"], ["not_needed", "Not required"]])),
        field("English", select("lang_en", [["required", "Required"], ["preferred", "An advantage"], ["not_needed", "Not required"]]))),
      field("Swedish", select("lang_sv", [["required", "Required"], ["preferred", "An advantage"], ["not_needed", "Not required"]])),
      h("div", { class: "field" }, h("span", null, "Work permit notes"), checks("permits", pairs("permit")))),
    fieldset("Your contact details (not published)",
      h("div", { class: "two-col" },
        field("Your name", h("input", { name: "contact_name", maxlength: 100, autocomplete: "name" })),
        field("Email *", h("input", { name: "contact_email", type: "email", required: true, maxlength: 254, autocomplete: "email" }))),
      h("p", { class: "muted small" }, "We use these only to tell you about this ad, and delete them 90 days after it has been reviewed.")),
    h("label", { class: "visually-hidden", "aria-hidden": "true" }, "Website",
      h("input", { name: "website", tabindex: "-1", autocomplete: "off" })),
    h("label", { class: "check consent" }, h("input", { type: "checkbox", name: "consent", required: true }),
      " I may publish this ad, and it treats applicants equally as the Non-Discrimination Act requires (no requirements about age, origin, gender or other personal characteristics that the work doesn't need)."),
    feedback,
    h("div", { class: "row" }, h("button", { type: "submit" }, "Send for review")));
  root.replaceChildren(form);
}

const root = document.getElementById("employer-form");
getJSON("/api/employers/options").then(options => render(root, options))
  .catch(error => root.replaceChildren(message(`The form couldn't be loaded: ${error.message}`, true)));
