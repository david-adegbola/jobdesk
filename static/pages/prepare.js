// Prepare: for one of my jobs, a tailored CV, a cover letter and a short application email, as a workspace:
// the documents on the left, the letter being edited in the middle, a live preview of the page on the right.
// The master profile (main CV + practical details) is set once and used for every job.
import { api, h, register, message, getState } from "../core.js";

const LANGUAGE = { en: "English", fi: "Finnish" };
const WRITER = { llm: "Written by AI from your CV facts", mock: "Copied from your CV facts (mock mode)", copy: "Copied from your CV facts" };

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
    h("summary", null, "My master profile: main CV and practical details"),
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
      : h("p", null, "Add a CV first: ", h("a", { href: "#/cvs" }, "My CV"), "."));
}

// The checks for one document, as a compact summary with the sentence-by-sentence list folded away
function checksView(doc) {
  const c = doc.checks || {};
  const letter = (c.letter_sentences || []).flat(), summary = (c.summary_sentences || []).flat();
  const all = letter.concat(summary);
  const written = all.filter(s => s.status !== "template");
  const supported = written.filter(s => s.status === "supported").length;
  return h("section", { class: "prep-checks", "aria-label": "Checks" },
    h("p", { class: "overline" }, "Checked against your CV"),
    h("div", { class: "prep-check-tags" },
      supported ? h("span", { class: "tag strength" }, `${supported} sentence${supported === 1 ? "" : "s"} supported`) : "",
      c.unsupported ? h("span", { class: "tag gap" }, `${c.unsupported} need${c.unsupported === 1 ? "s" : ""} a source`) : "",
      written.length ? h("span", { class: "tag ai" }, `${written.length} written ${doc.method === "llm" ? "by AI" : "from CV facts"}`) : "",
      (c.style || []).length ? h("span", { class: "tag warn" }, `Machine-sounding: ${c.style.join(", ")}`) : ""),
    (c.ad_blockers || []).length ? h("p", { class: "small" }, "The ad asks for things your CV doesn't show, so the documents don't claim them: " +
      c.ad_blockers.join(", ") + ". Say honestly whether you're working towards them.") : "",
    c.notice ? h("p", { class: "muted small" }, c.notice) : "",
    h("details", { class: "small" }, h("summary", null, "How each sentence was checked"),
      h("ol", { class: "draft-sentences" }, all.map(s => h("li", { class: s.status },
        s.status === "unsupported" ? h("strong", null, "UNSUPPORTED: ") : "", s.text,
        s.status === "template" ? h("div", { class: "muted" }, "Standard wording, not from the AI") : "",
        (s.reasons || []).length ? h("ul", null, s.reasons.map(r => h("li", null, r))) : "",
        (s.fact_ids || []).length ? h("div", { class: "muted" }, "Based on: " + s.fact_ids.join(", ")) : "")))));
}

// A textarea that grows with its text, so the letter reads like a page instead of a stack of boxes
function grow(el) {
  const fit = () => { el.style.height = "auto"; el.style.height = `${el.scrollHeight + 2}px`; };
  el.addEventListener("input", fit);
  requestAnimationFrame(fit);
  return el;
}

function documentView(doc) {
  const L = doc.letter, out = h("div", { "aria-live": "polite" });
  const heading = h("span", { class: "tag warn" }, "Edited by you: kept when you write again");
  heading.hidden = !doc.edited;
  const input = (label, value, attrs = {}) => {
    const el = h(attrs.rows ? "textarea" : "input", { ...attrs, "aria-label": label });
    el.value = value || "";
    return attrs.rows ? grow(el) : el;
  };
  const date = input("Date", L.date, { class: "letter-date" });
  const recipient = input("Recipient", L.recipient, { rows: 2, class: "letter-recipient" });
  const subject = input("Subject", L.subject, { class: "letter-subject" });
  const greeting = input("Greeting", L.greeting, { class: "letter-greeting" });
  const closing = input("Closing", L.closing, { class: "letter-closing" });
  const sentenceGroups = (doc.checks?.letter_sentences || []);
  const paragraphs = L.paragraphs.map((p, i) => {
    const sentences = sentenceGroups[i] || [];
    const unsupported = sentences.filter(s => s.status === "unsupported");
    const written = sentences.some(s => s.status !== "template");
    const el = input(`Paragraph ${i + 1}`, p, { rows: 2, class: "letter-paragraph" });
    const box = h("div", { class: "letter-block" + (unsupported.length ? " is-unsupported" : written ? " is-ai" : "") },
      written ? h("span", { class: "tag ai" }, WRITER[doc.method] || WRITER.copy, " · edit freely") : "",
      el,
      unsupported.length ? h("p", { class: "letter-note small" },
        unsupported.length === 1 ? `“${unsupported[0].text}” isn't in your CV.` : `${unsupported.length} sentences here aren't in your CV.`,
        " Add it to your CV, or change the sentence before sending.") : "");
    return [box, el];
  });
  const to = input("To", doc.email.to, { type: "text", placeholder: "the address in the ad, if any" });
  const esubject = input("Email subject", doc.email.subject);
  const ebody = input("Email", doc.email.body, { rows: 10 });

  // Live preview of the letter page, redrawn as the member types
  const preview = h("div", { class: "letter-page", "aria-hidden": "true" });
  function drawPreview() {
    preview.replaceChildren(
      h("div", { class: "lp-head" }, h("div", null, h("strong", null, L.name || ""), h("span", null, L.job_title || "")),
        h("div", { class: "lp-contact" }, [L.location, L.phone, L.email].filter(Boolean).map(x => h("span", null, x)))),
      h("p", null, date.value),
      h("p", { class: "lp-pre" }, recipient.value),
      h("p", null, h("strong", null, subject.value)),
      h("p", null, greeting.value),
      ...paragraphs.map(([, el]) => h("p", null, el.value)),
      h("p", { class: "lp-pre" }, closing.value),
      h("p", { class: "lp-pre" }, [L.name, L.phone, L.email].filter(Boolean).join("\n")));
  }
  for (const el of [date, recipient, subject, greeting, closing, ...paragraphs.map(([, el]) => el)]) el.addEventListener("input", drawPreview);
  drawPreview();

  async function save() {
    try {
      await api(`/api/documents/${doc.id}`, { method: "POST", body: {
        letter: { date: date.value, subject: subject.value, recipient: recipient.value, greeting: greeting.value,
                  closing: closing.value, paragraphs: paragraphs.map(([, el]) => el.value) },
        email: { to: to.value, subject: esubject.value, body: ebody.value } } });
      out.replaceChildren(message("Saved. Your edits are kept if you write the documents again for another language."));
      heading.hidden = false;
      return true;
    } catch (err) { out.replaceChildren(message(err.message, true)); return false; }
  }
  const copy = h("button", { type: "button", class: "secondary", onclick: async () => {
    try { await navigator.clipboard.writeText(ebody.value); copy.textContent = "Copied"; }
    catch (e) { copy.textContent = "Select the text and copy it"; }
  } }, "Copy email");
  const mailto = () => `mailto:${encodeURIComponent(to.value.trim()).replace(/%2C/g, ",").replace(/%40/g, "@")}` +
    `?subject=${encodeURIComponent(esubject.value)}&body=${encodeURIComponent(ebody.value)}`;
  const pdfLink = h("a", { class: "btn secondary", href: `/api/documents/${doc.id}/letter.pdf`, target: "_blank", rel: "noopener",
    onclick: async e => { e.preventDefault(); if (await save()) window.open(`/api/documents/${doc.id}/letter.pdf`, "_blank", "noopener"); } },
    "Letter as PDF");

  // Three documents, one shown at a time
  const panes = {
    letter: h("div", { class: "prep-pane letter-editor" },
      h("div", { class: "letter-meta" }, date, recipient), subject, greeting, paragraphs.map(([box]) => box), closing,
      h("p", { class: "muted small" }, "The header and signature use the name, phone and email in your CV."),
      h("div", { class: "row" }, h("button", { type: "button", onclick: save }, "Save letter and email"), pdfLink,
        h("a", { class: "btn secondary", href: `/api/documents/${doc.id}/letter.txt` }, "Letter as text"))),
    cv: h("div", { class: "prep-pane" },
      h("h3", null, "Tailored CV"),
      doc.tailored_cv ? [h("p", null, `“${doc.tailored_cv.title}”: a copy of your main CV with a summary written for this job, and the skills the ad asks for first. Nothing is added or removed.`),
        h("div", { class: "row" }, h("a", { class: "btn", href: `/api/cvs/${doc.tailored_cv.id}/formatted.pdf`, target: "_blank", rel: "noopener" }, "CV as PDF"),
          h("a", { class: "btn secondary", href: "#/cvs" }, "Edit it in My CV"))]
        : h("p", { class: "muted" }, "The tailored CV is made in your main CV's language. Write the documents in that language to get one.")),
    email: h("div", { class: "prep-pane" },
      h("h3", null, "Application email"),
      h("p", { class: "muted small" }, "A short note to send after you've applied, or with the application if the ad asks for email."),
      h("label", { class: "field" }, "To", to), h("label", { class: "field" }, "Subject", esubject), h("label", { class: "field" }, "Email", ebody),
      h("div", { class: "row" }, h("button", { type: "button", onclick: save }, "Save letter and email"), copy,
        h("a", { class: "btn secondary", href: "#", onclick: e => { e.preventDefault(); location.href = mailto(); } }, "Open in email"))),
  };
  const tabs = h("div", { class: "prep-tabs", role: "tablist", "aria-label": "Documents" });
  const notes = { letter: `${L.paragraphs.length} paragraphs`, cv: doc.tailored_cv ? "summary rewritten" : "main CV's language only", email: "ready to copy" };
  function show(id) {
    for (const [key, pane] of Object.entries(panes)) pane.hidden = key !== id;
    for (const b of tabs.children) b.setAttribute("aria-selected", b.dataset.pane === id ? "true" : "false");
  }
  tabs.append(...[["letter", "Cover letter"], ["cv", "Tailored CV"], ["email", "Application email"]].map(([id, label]) =>
    h("button", { type: "button", role: "tab", class: "prep-tab", "data-pane": id, onclick: () => show(id) },
      h("strong", null, label), h("span", null, notes[id]))));
  show("letter");

  return h("section", { class: "prep-workspace", "aria-label": `${LANGUAGE[doc.language]} documents` },
    h("aside", { class: "prep-side" }, tabs, checksView(doc), h("p", { class: "small" }, heading)),
    h("div", { class: "prep-editor" }, ...Object.values(panes), out),
    h("aside", { class: "prep-preview" }, h("p", { class: "overline" }, "Preview · A4"), preview,
      h("p", { class: "muted small" }, `Saves as ${doc.letter_file}`)));
}

register({
  id: "prepare", title: "Prepare",
  async render(main, query) {
    const state = await getState();
    const data = await api("/api/prepare");
    const params = new URLSearchParams(query || "");
    let jobId = Number(params.get("job")) || data.jobs[0]?.id;
    const titleJob = h("span", { class: "serif" });
    const head = h("div", { class: "page-head" },
      h("div", null, h("p", { class: "overline" }, "Applications · Prepare"), h("h1", null, "Prepare: ", titleJob),
        h("p", { class: "muted" }, "A tailored CV, a cover letter and an email, written from your CV. Every sentence is checked against your CV; read and edit everything before you send it.")));
    const area = h("div");
    main.append(head, area, profileCard(data, () => getState(true)));
    if (!data.jobs.length) {
      titleJob.textContent = "pick a job";
      area.append(h("div", { class: "empty-state" }, h("p", { class: "empty-title" }, "No jobs to prepare for yet"),
        h("p", null, "Save one from ", h("a", { href: "#/jobs" }, "Discover"), " or add one under ", h("a", { href: "#/myjobs" }, "My jobs"), ".")));
      return;
    }
    if (!data.jobs.some(j => j.id === jobId)) jobId = data.jobs[0].id;
    const picker = h("select", { "aria-label": "Job", onchange: () => { jobId = Number(picker.value); history.replaceState(null, "", `#/prepare?job=${jobId}`); load(); } },
      data.jobs.map(j => h("option", { value: j.id, selected: j.id === jobId }, `${j.title}${j.company ? ` – ${j.company}` : ""}${j.status ? ` (${j.status})` : ""}`)));
    head.append(h("div", { class: "page-head-side" }, h("label", { class: "field" }, "Job", picker)));
    const jobInfo = h("p", { class: "muted" }), progress = h("div", { "aria-live": "polite" }), docsArea = h("div");
    const lang = Object.fromEntries(["en", "fi"].map(l => [l, h("input", { type: "checkbox", name: `lang-${l}` })]));
    const master = data.cvs.find(c => c.id === data.master_cv_id);
    lang[master?.language || "en"].checked = true;
    const r = { name: h("input", { name: "contact_name", maxlength: 200 }), title: h("input", { name: "contact_title", maxlength: 200 }),
      address: h("textarea", { name: "address", rows: 3 }), email: h("input", { name: "email_to", maxlength: 200, placeholder: "name@company.fi" }) };
    const aiNote = state.llm.mode !== "live" ? "This server is in mock mode: the documents copy facts from your CV, so you can try the steps."
      : state.llm_opt_in ? "The AI writes the text from your CV facts (never your name or contact details); code then checks every sentence."
      : "“AI with your CV” is off (Profile), so facts from your CV are copied in for you to rewrite. Nothing is sent to an AI service.";
    const writeBtn = h("button", { type: "submit" }, "Write my documents");
    const form = h("form", { class: "grid", onsubmit: e => { e.preventDefault(); write(false); } },
      h("fieldset", { style: "grid-column: 1 / -1" }, h("legend", null, "Languages"),
        Object.entries(lang).map(([l, el]) => h("label", { class: "check" }, el, ` ${LANGUAGE[l]}`))),
      h("p", { class: "muted small", style: "grid-column: 1 / -1" }, "Who to address, if the ad names someone. Copy it from the ad or the employer's website; leave it empty for “Hello,”."),
      h("label", { class: "field" }, "Contact name", r.name), h("label", { class: "field" }, "Their title", r.title),
      h("label", { class: "field" }, "Email for the application (optional)", r.email),
      h("label", { class: "field", style: "grid-column: 1 / -1" }, "Employer's postal address (optional)", r.address),
      h("p", { class: "muted small", style: "grid-column: 1 / -1" }, aiNote),
      h("div", { class: "row", style: "grid-column: 1 / -1" }, writeBtn));
    const writer = h("details", { class: "card prep-write" }, h("summary", null, "Write the documents"), form);
    area.append(jobInfo, writer, progress, docsArea);

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

    let shownLanguage = null;
    async function load() {
      const id = jobId;
      const d = await api(`/api/prepare/${id}`);
      if (id !== jobId) return;
      const j = d.job;
      titleJob.textContent = j.title;
      jobInfo.replaceChildren(...[[j.company, j.location].filter(Boolean).join(", "),
        j.url ? [" · ", h("a", { href: j.url, target: "_blank", rel: "noopener" }, "the ad")] : "",
        j.status ? [" · ", h("span", { class: "tag status", "data-status": j.status }, j.status)] : ""].flat());
      if (!j.has_text) jobInfo.append(message("This job has no description yet, so there's nothing to write from. Add it under My jobs.", true));
      writer.open = !d.documents.length;
      const t = d.task;
      if (t && (t.status === "queued" || t.status === "running")) {
        writeBtn.disabled = true;
        progress.replaceChildren(h("div", { class: "prep-progress", role: "status" },
          h("strong", null, t.status === "queued" ? "Waiting in the queue…" : "Writing your documents…"),
          h("span", null, "The letter is written, then every sentence is checked against your CV. You can leave this page; it keeps going.")));
        setTimeout(() => { if (main.isConnected) load(); }, 1500);
      } else {
        writeBtn.disabled = false;
        progress.replaceChildren(t && t.status === "failed" ? message(`Writing failed: ${t.error}`, true) : "");
      }
      if (!d.documents.length) { docsArea.replaceChildren(); return; }
      const docs = Object.fromEntries(d.documents.map(doc => [doc.language, doc]));
      if (!docs[shownLanguage]) shownLanguage = d.documents[0].language;
      const views = Object.fromEntries(d.documents.map(doc => [doc.language, documentView(doc)]));
      const switcher = d.documents.length > 1 ? h("fieldset", { class: "segmented prep-language" }, h("legend", null, "Language"),
        d.documents.map(doc => h("label", null,
          h("input", { type: "radio", name: "prep-language", value: doc.language, checked: doc.language === shownLanguage,
            onchange: () => { shownLanguage = doc.language; for (const [l, v] of Object.entries(views)) v.hidden = l !== shownLanguage; } }),
          h("span", null, LANGUAGE[doc.language])))) : "";
      for (const [l, v] of Object.entries(views)) v.hidden = l !== shownLanguage;
      docsArea.replaceChildren(switcher, ...Object.values(views));
    }
    load();
  },
});
