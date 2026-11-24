// Prepare: for one of my jobs, a tailored CV, a cover letter and a short application email.
// The master profile (main CV + practical details) is set once and used for every job.
import { api, h, register, message, getState } from "../core.js";

const LANGUAGE = { en: "English", fi: "Finnish" };
const STATUS_LABEL = { supported: "", unsupported: "UNSUPPORTED: ", template: "" };

function profileCard(data, onSaved) {
  const out = h("div", { "aria-live": "polite" });
  const cv = h("select", { name: "master_cv" }, data.cvs.map(c => h("option", { value: c.id, selected: c.id === data.master_cv_id },
    `${c.title} (${LANGUAGE[c.language] || c.language})`)));
  const inputs = Object.fromEntries(Object.entries(data.profile_labels).map(([key, label]) =>
    [key, h("input", { name: key, value: data.profile[key] || "", maxlength: 200 })]));
  const hints = { available_from: "e.g. 1 February 2027, or right away", hours: "e.g. full-time; weekends; shifts",
    locations: "e.g. Helsinki region; anywhere in Finland", permit: "e.g. student residence permit: may work 30 h/week",
    licences: "e.g. B driving licence; occupational safety card" };
  return h("details", { class: "card", open: !data.cvs.length || !Object.values(data.profile).some(Boolean) },
    h("summary", null, "My master profile"),
    data.cvs.length ? h("form", { class: "grid", onsubmit: async e => {
      e.preventDefault();
      const profile = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
      try {
        await api("/api/prepare/profile", { method: "POST", body: { master_cv_id: Number(cv.value), profile } });
        out.replaceChildren(message("Saved."));
        onSaved();
      } catch (err) { out.replaceChildren(message(err.message, true)); }
    } },
      h("label", { class: "field", style: "grid-column: 1 / -1" }, "Main CV (documents are written from it)", cv),
      h("p", { class: "muted small", style: "grid-column: 1 / -1" }, "Practical details, for the letter's paragraph on start date, hours, " +
        "place and permits. Write only what is true; leave the rest empty. They are saved with your account and used only in your own documents."),
      Object.entries(inputs).map(([key, el]) => { el.placeholder = hints[key] || ""; return h("label", { class: "field" }, data.profile_labels[key], el); }),
      h("div", { class: "row", style: "grid-column: 1 / -1" }, h("button", { type: "submit" }, "Save profile")), out)
      : h("p", null, "Add a CV first: ", h("a", { href: "#/cvs" }, "My CVs"), "."));
}

function checksView(doc) {
  const c = doc.checks || {};
  const sentences = (c.letter_sentences || []).flat().concat((c.summary_sentences || []).flat());
  return h("div", null,
    c.notice ? h("p", { class: "muted small" }, c.notice) : "",
    (c.ad_blockers || []).length ? h("p", { class: "msg" }, "The ad asks for things your CV doesn't show, so the documents don't claim them: " +
      c.ad_blockers.join(", ") + ". Say honestly whether you're working towards them.") : "",
    c.unsupported ? h("p", { class: "msg err" }, `${c.unsupported} sentence${c.unsupported === 1 ? "" : "s"} couldn't be matched to your CV. ` +
      "They're marked below and kept in the text: fix or delete them before sending.") : "",
    (c.style || []).length ? h("p", { class: "msg" }, "Words that make writing sound machine-made: " + c.style.join(", ") +
      ". Consider plainer words.") : "",
    h("details", null, h("summary", { class: "small" }, "How each sentence was checked"),
      h("ol", { class: "draft-sentences small" }, sentences.map(s => h("li", { class: s.status },
        STATUS_LABEL[s.status] ? h("strong", null, STATUS_LABEL[s.status]) : "", s.text,
        s.status === "template" ? h("div", { class: "muted small" }, "Standard wording, not from the AI") : "",
        (s.reasons || []).length ? h("ul", { class: "small" }, s.reasons.map(r => h("li", null, r))) : "",
        (s.fact_ids || []).length ? h("div", { class: "muted small" }, "Based on: " + s.fact_ids.join(", ")) : "")))));
}

function documentView(doc, reload) {
  const L = doc.letter, out = h("div", { "aria-live": "polite" });
  const heading = h("h2", null, `${LANGUAGE[doc.language]}`, doc.edited ? h("span", { class: "tag" }, " edited") : "");
  const field = (label, value, { wide, ...attrs } = {}) => {
    const el = h(attrs.rows ? "textarea" : "input", { ...attrs, "aria-label": label });
    el.value = value || "";
    return [h("label", { class: "field", style: attrs.rows || wide ? "grid-column: 1 / -1" : "" }, label, el), el];
  };
  const [dateF, date] = field("Date", L.date), [subjectF, subject] = field("Subject", L.subject, { wide: true });
  const [recF, recipient] = field("Recipient", L.recipient, { rows: 3 });
  const [greetF, greeting] = field("Greeting", L.greeting), [closeF, closing] = field("Closing", L.closing);
  const paragraphs = L.paragraphs.map((p, i) => field(`Paragraph ${i + 1}`, p, { rows: 4 }));
  const [toF, to] = field("To", doc.email.to, { type: "text", placeholder: "the address in the ad, if any" });
  const [esF, esubject] = field("Email subject", doc.email.subject, { wide: true }), [ebF, ebody] = field("Email", doc.email.body, { rows: 12 });

  async function save() {
    try {
      await api(`/api/documents/${doc.id}`, { method: "POST", body: {
        letter: { date: date.value, subject: subject.value, recipient: recipient.value, greeting: greeting.value,
                  closing: closing.value, paragraphs: paragraphs.map(([, el]) => el.value) },
        email: { to: to.value, subject: esubject.value, body: ebody.value } } });
      out.replaceChildren(message("Saved. Your edits are kept if you write the documents again for another language."));
      if (!heading.querySelector(".tag")) heading.append(h("span", { class: "tag" }, " edited"));
      return true;
    } catch (err) { out.replaceChildren(message(err.message, true)); return false; }
  }
  const copy = h("button", { type: "button", class: "secondary", onclick: async () => {
    try { await navigator.clipboard.writeText(ebody.value); copy.textContent = "Copied"; }
    catch (e) { copy.textContent = "Select the text and copy it"; }
  } }, "Copy email");
  const mailto = () => `mailto:${encodeURIComponent(to.value.trim()).replace(/%2C/g, ",").replace(/%40/g, "@")}` +
    `?subject=${encodeURIComponent(esubject.value)}&body=${encodeURIComponent(ebody.value)}`;

  return h("section", { class: "card" },
    heading,
    checksView(doc),
    h("h3", null, "Tailored CV"),
    doc.tailored_cv ? h("p", null, `“${doc.tailored_cv.title}”: the summary is written for this job and the skills it asks for come first. `,
      h("a", { href: "#/cvs" }, "Edit it in My CVs"), " · ",
      h("a", { href: `/api/cvs/${doc.tailored_cv.id}/formatted.pdf`, target: "_blank", rel: "noopener" }, "PDF"))
      : h("p", { class: "muted small" }, "The tailored CV is made in your main CV's language."),
    h("h3", null, "Cover letter"),
    h("div", { class: "grid" }, dateF, subjectF, recF, greetF, paragraphs.map(([f]) => f), closeF),
    h("div", { class: "row" }, h("button", { type: "button", onclick: save }, "Save letter and email"),
      h("a", { class: "btn secondary", href: `/api/documents/${doc.id}/letter.pdf`, target: "_blank", rel: "noopener",
        onclick: async e => { e.preventDefault(); if (await save()) window.open(`/api/documents/${doc.id}/letter.pdf`, "_blank", "noopener"); } },
        "Letter as PDF"),
      h("a", { class: "btn secondary", href: `/api/documents/${doc.id}/letter.txt` }, "Letter as text")),
    h("p", { class: "muted small" }, `PDF file name: ${doc.letter_file}. The header and signature use the name, phone and email in your CV.`),
    h("h3", null, "Application email"),
    h("p", { class: "muted small" }, "A short note to send after you've applied, or with the application if the ad asks for email."),
    h("div", { class: "grid" }, toF, esF, ebF),
    h("div", { class: "row" }, copy,
      h("a", { class: "btn secondary", href: "#", onclick: e => { e.preventDefault(); location.href = mailto(); } }, "Open in email")),
    out);
}

register({
  id: "prepare", title: "Prepare",
  async render(main, query) {
    const state = await getState();
    const data = await api("/api/prepare");
    const params = new URLSearchParams(query || "");
    let jobId = Number(params.get("job")) || data.jobs[0]?.id;
    const area = h("div");
    main.append(h("h1", null, "Prepare"),
      h("p", { class: "muted" }, "A tailored CV, a cover letter and an email for one of your jobs, written from your CV. " +
        "Every sentence is checked against your CV; read and edit everything before you send it."),
      profileCard(data, () => getState(true)), area);
    if (!data.jobs.length) {
      area.append(h("p", { class: "card" }, "No jobs to prepare for yet. Save or shortlist one on the ", h("a", { href: "#/jobs" }, "Jobs"), " page."));
      return;
    }
    if (!data.jobs.some(j => j.id === jobId)) jobId = data.jobs[0].id;
    const picker = h("select", { "aria-label": "Job", onchange: () => { jobId = Number(picker.value); history.replaceState(null, "", `#/prepare?job=${jobId}`); load(); } },
      data.jobs.map(j => h("option", { value: j.id, selected: j.id === jobId }, `${j.title}${j.company ? ` – ${j.company}` : ""}${j.status ? ` (${j.status})` : ""}`)));
    const jobInfo = h("div"), progress = h("div", { "aria-live": "polite" }), docs = h("div");
    const lang = Object.fromEntries(["en", "fi"].map(l => [l, h("input", { type: "checkbox", name: `lang-${l}` })]));
    const master = data.cvs.find(c => c.id === data.master_cv_id);
    lang[master?.language || "en"].checked = true;
    const r = { name: h("input", { name: "contact_name", maxlength: 200 }), title: h("input", { name: "contact_title", maxlength: 200 }),
      address: h("textarea", { name: "address", rows: 3 }), email: h("input", { name: "email_to", maxlength: 200, placeholder: "name@company.fi" }) };
    const aiNote = state.llm.mode !== "live" ? "This server is in mock mode: the documents copy facts from your CV, so you can try the steps."
      : state.llm_opt_in ? "The AI writes the text from your CV facts (never your name or contact details); code then checks every sentence."
      : "“AI with your CV” is off (Account), so facts from your CV are copied in for you to rewrite. Nothing is sent to an AI service.";
    const form = h("form", { class: "card grid", onsubmit: e => { e.preventDefault(); write(false); } },
      h("h2", { style: "grid-column: 1 / -1" }, "Write the documents"),
      h("fieldset", { style: "grid-column: 1 / -1" }, h("legend", null, "Languages"),
        Object.entries(lang).map(([l, el]) => h("label", { class: "check" }, el, ` ${LANGUAGE[l]}`))),
      h("p", { class: "muted small", style: "grid-column: 1 / -1" }, "Who to address, if the ad names someone. Copy it from the ad or the employer's website; leave it empty for “Hello,”."),
      h("label", { class: "field" }, "Contact name", r.name), h("label", { class: "field" }, "Their title", r.title),
      h("label", { class: "field" }, "Email for the application (optional)", r.email),
      h("label", { class: "field", style: "grid-column: 1 / -1" }, "Employer's postal address (optional)", r.address),
      h("p", { class: "muted small", style: "grid-column: 1 / -1" }, aiNote),
      h("div", { class: "row", style: "grid-column: 1 / -1" }, h("button", { type: "submit" }, "Write my documents")));
    area.append(h("div", { class: "card" }, h("label", { class: "field" }, "Job", picker), jobInfo), form, progress, docs);

    async function write(replace) {
      const languages = Object.entries(lang).filter(([, el]) => el.checked).map(([l]) => l);
      if (!languages.length) { progress.replaceChildren(message("Choose at least one language.", true)); return; }
      const recipient = Object.fromEntries(Object.entries(r).map(([k, el]) => [k, el.value]));
      try {
        await api(`/api/prepare/${jobId}`, { method: "POST", body: { languages, recipient, replace_edited: replace } });
        load();
      } catch (err) {
        if (err.message.includes("edited") && confirm(`${err.message}\n\nReplace your edited documents?`)) return write(true);
        progress.replaceChildren(message(err.message, true));
      }
    }

    async function load() {
      const id = jobId;
      const d = await api(`/api/prepare/${id}`);
      if (id !== jobId) return;
      const j = d.job;
      jobInfo.replaceChildren(h("p", { class: "small" }, [j.company, j.location].filter(Boolean).join(", "),
        j.url ? [" · ", h("a", { href: j.url, target: "_blank", rel: "noopener" }, "the ad")] : "",
        j.status ? ` · ${j.status}` : ""),
        j.has_text ? "" : h("p", { class: "msg err" }, "This job has no description yet, so there's nothing to write from. Add it on the Jobs page."));
      const t = d.task;
      if (t && (t.status === "queued" || t.status === "running")) {
        progress.replaceChildren(h("p", { class: "muted", role: "status" }, t.status === "queued" ? "Waiting in the queue…" : "Writing your documents…"));
        setTimeout(() => { if (main.isConnected) load(); }, 1500);
      } else progress.replaceChildren(t && t.status === "failed" ? message(`Writing failed: ${t.error}`, true) : "");
      docs.replaceChildren(...d.documents.map(doc => documentView(doc, load)));
    }
    load();
  },
});
