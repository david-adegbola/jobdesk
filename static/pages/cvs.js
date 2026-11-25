// My CV: the member's CVs on the left (main, other languages, tailored copies), the chosen CV in a section
// editor in the middle, and a live preview of the page on the right. The PDF itself comes from the LaTeX template.
import { api, h, register, message } from "../core.js";

const fields = [
  ["full_name", "Name", "Nimi", "text"],
  ["email", "Email", "Sähköposti", "email"],
  ["phone", "Phone", "Puhelin", "tel"],
  ["location", "Location", "Sijainti", "text"],
  ["target_role", "Target role", "Tavoiteltu tehtävä", "text"],
  ["summary", "Profile", "Profiili", "textarea"],
  ["education", "Education", "Koulutus", "textarea"],
  ["experience", "Experience", "Työkokemus", "textarea"],
  ["skills", "Skills", "Osaaminen", "textarea"],
  ["projects", "Projects and research", "Projektit ja tutkimus", "textarea"],
  ["hobbies", "Hobbies", "Harrastukset", "textarea"],
  ["certifications", "Certifications", "Sertifikaatit", "textarea"],
  ["languages", "Languages", "Kielitaito", "textarea"],
  ["links", "Links", "Linkit", "textarea"],
];
const ABOUT = ["full_name", "target_role", "email", "phone", "location"];
const SECTIONS = ["summary", "experience", "education", "skills", "projects", "languages", "certifications", "hobbies", "links"];
const LANGUAGE = { en: "English", fi: "Finnish" };

// Set by the What to study page: an unsaved draft for one type of role
const DRAFT_KEY = "jobdesk:cv-draft";

function takeDraft() {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    sessionStorage.removeItem(DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (error) { return null; }
}

const fieldGuidance = {
  summary: "2–3 sentences in your own words. Leave a blank line between paragraphs.",
  education: "One row per qualification: dates: qualification, institution.",
  experience: "Start each entry with dates, e.g. Aug 2025--Oct 2025: Job title — Employer. One detail per line; a blank line between entries. Optional last row: Tags: tag-one, tag-two.",
  skills: "One row per group: label: skills or knowledge. Tailored CVs move the ad's skills first.",
  projects: "The same dated format as Experience.",
  hobbies: "Optional; shown after Projects.",
  certifications: "Shown as a Cards row under Skills.",
  languages: "Shown as a Languages row under Skills.",
  links: "One link per row: label: https://example.com",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function updated(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
  if (!m) return "recently";
  const d = new Date(+m[1], +m[2] - 1, +m[3]), today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((today - d) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : days < 7 ? `${days} days ago` : `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
}

function grow(el) {
  const fit = () => { el.style.height = "auto"; el.style.height = `${el.scrollHeight + 3}px`; };
  el.addEventListener("input", fit);
  requestAnimationFrame(fit);
  return el;
}

register({
  id: "cvs", title: "My CV",
  async render(main) {
    const heading = h("h1", { tabindex: "-1", "data-focus": "cv-heading" }, "My CV, ", h("span", { class: "serif" }, "the master copy"));
    const headActions = h("div", { class: "page-head-side" });
    main.append(h("div", { class: "page-head" },
      h("div", null, heading, h("p", { class: "muted" }, "Private to your account. Your main CV is what fit checks, tailored CVs and letters are written from.")),
      headActions));
    let cvs = [];
    let example = null;
    let editor = null;
    let roles = { master: null, tailored: new Set() };
    const status = h("div", { role: "status" });
    const layout = h("div", { class: "cv-layout" });
    main.append(status, layout);

    async function refresh(selectId) {
      try {
        const [cvList, exampleResult, prep] = await Promise.all([
          api("/api/cvs"), api("/api/cvs/example"), api("/api/prepare").catch(() => null)]);
        cvs = cvList.cvs;
        example = exampleResult.cv;
        const untailored = new Set((prep?.cvs || cvs).map(c => c.id));
        roles = { master: prep?.master_cv_id ?? null, tailored: new Set(cvs.filter(c => !untailored.has(c.id)).map(c => c.id)) };
        editor = null;
        const draft = takeDraft();
        if (draft) {
          editor = createEditorState(draft, "create");
          editor.fromPlan = draft.based_on || true;
        } else {
          const pick = cvs.find(c => c.id === selectId) || cvs.find(c => c.id === roles.master) || cvs[0];
          if (pick) editor = createEditorState(pick, "edit");
        }
        draw();
      } catch (err) {
        status.replaceChildren(message(err.message, true));
      }
    }

    // Leaving an editor with unsaved changes asks first
    let isDirty = () => false;
    function leave(next) {
      if (isDirty() && !window.confirm("Discard your unsaved changes?")) return;
      next();
    }
    const startNew = () => leave(() => { editor = createEditorState(example, "create"); editor.fromExample = true; draw(); });

    function versionsList() {
      const order = [...cvs].sort((a, b) => (b.id === roles.master) - (a.id === roles.master) || roles.tailored.has(a.id) - roles.tailored.has(b.id));
      return h("nav", { class: "cv-versions", "aria-label": "Your CVs" },
        h("p", { class: "overline" }, "Your CVs"),
        order.map(cv => h("button", { type: "button", class: "cv-version", "aria-current": editor?.id === cv.id ? "true" : null,
          "data-focus": `cv-edit:${cv.id}`, onclick: () => leave(() => { editor = createEditorState(cv, "edit"); draw(); }) },
          h("span", { class: "cv-version-title" }, h("strong", null, cv.title),
            cv.id === roles.master ? h("span", { class: "tag strength" }, "Main") : "",
            roles.tailored.has(cv.id) ? h("span", { class: "tag ai" }, "Tailored") : ""),
          h("span", { class: "muted small" }, `${LANGUAGE[cv.language] || cv.language} · edited ${updated(cv.updated_at)}`))),
        h("button", { type: "button", class: "secondary", "data-focus": "cv-create", onclick: startNew }, "+ New CV"),
        h("p", { class: "muted small" }, "New CVs start from a two-page example with fictional details. ",
          h("a", { href: "/api/cvs/example.pdf", target: "_blank", rel: "noopener" }, "See the example PDF"), "."));
    }

    function draw() {
      headActions.replaceChildren();
      if (!editor) {
        isDirty = () => false;
        layout.replaceChildren(h("div", { class: "empty-state cv-empty" },
          h("p", { class: "empty-title" }, "Start with your CV"),
          h("p", null, "Fill it in once: about you, experience, skills. Fit scores, tailored CVs and letters are all written from it."),
          h("div", { class: "row", style: "justify-content: center" },
            h("button", { type: "button", "data-focus": "cv-create", onclick: startNew }, "Fill in my CV"),
            h("a", { class: "btn secondary", href: "/api/cvs/example.pdf", target: "_blank", rel: "noopener" }, "See the example CV"))));
        return;
      }
      renderEditor();
    }

    function renderEditor() {
      const current = editor;
      const values = current.content || (current.content = {});
      const controls = {};
      const textChanged = () => controls.title.value.trim() !== current.original.title
        || fields.some(([key]) => controls[key].value.trim() !== (current.original.content[key] || ""));
      isDirty = () => textChanged() || controls.language.value !== current.original.language;
      const languageNote = h("p", { class: "muted small", role: "status" }, current.languageNote || "");
      // Choosing a language opens this CV's version in that language when there is one
      // (imported role CVs come in Finnish/English pairs); otherwise the text stays as written.
      async function switchLanguage(lang) {
        const other = (current.versions || {})[lang];
        const target = other && other !== current.id ? cvs.find(cv => cv.id === other) : null;
        const replaces = current.role_id || target;
        if (replaces && textChanged() && !window.confirm(
          `Open the ${LANGUAGE[lang]} version? Your unsaved changes here will be lost.`)) {
          controls.language.value = current.language;
          return;
        }
        if (current.role_id) {
          try {
            const { cv } = await api(`/api/skills/draft/${encodeURIComponent(current.role_id)}/${lang}`);
            editor = createEditorState(cv, "create");
            editor.fromPlan = cv.based_on || true;
            editor.languageNote = cv.based_on
              ? `Showing the ${LANGUAGE[lang]} draft, based on “${cv.based_on}”.`
              : `Showing the ${LANGUAGE[lang]} draft.`;
          } catch (err) {
            controls.language.value = current.language;
            status.replaceChildren(message(err.message, true));
            return;
          }
        } else if (target && current.mode === "edit") {
          editor = createEditorState(target, "edit");
          editor.languageNote = `Now editing the ${LANGUAGE[lang]} version, “${target.title}”.`;
        } else if (target) {
          editor = createEditorState({ ...target, id: undefined, title: `${target.title} (copy)` }, "copy");
          editor.languageNote = `Now copying the ${LANGUAGE[lang]} version, “${target.title}”.`;
        } else {
          current.language = lang;
          languageNote.textContent = `There is no ${LANGUAGE[lang]} version of this CV, so the text stays as written; ` +
            `only the PDF headings change to ${LANGUAGE[lang]}. Translate the text before saving` +
            (current.mode === "edit" ? ", or use Make a copy first to keep both versions." : ".");
          return;
        }
        draw();
        layout.querySelector(".cv-editor select")?.focus();
      }

      for (const [key, , , type] of fields) {
        controls[key] = type === "textarea"
          ? grow(h("textarea", { name: key, rows: key === "summary" ? 3 : 4, maxlength: 12000, value: values[key] || "" }))
          : h("input", { name: key, type, maxlength: 500, value: values[key] || "" });
      }
      controls.title = h("input", { value: current.title || "", required: true, maxlength: 120 });
      controls.language = h("select", { onchange: () => switchLanguage(controls.language.value) },
        h("option", { value: "en", selected: current.language === "en" }, "English"),
        h("option", { value: "fi", selected: current.language === "fi" }, "Suomi"));
      const label = key => fields.find(f => f[0] === key)[1];

      // Live preview of the page
      const preview = h("div", { class: "cv-page", "aria-hidden": "true" });
      function drawPreview() {
        const v = key => controls[key].value.trim();
        preview.replaceChildren(
          h("div", { class: "cvp-head" }, h("strong", null, v("full_name") || "Your name"), h("span", null, v("target_role"))),
          h("p", { class: "cvp-contact" }, [v("location"), v("phone"), v("email")].filter(Boolean).join(" · ")),
          ...SECTIONS.filter(key => v(key)).map(key => h("div", { class: "cvp-section" },
            h("p", { class: "cvp-title" }, (current.language === "fi" ? fields.find(f => f[0] === key)[2] : label(key)).toUpperCase()),
            h("p", { class: "cvp-text" }, v(key)))));
      }
      for (const el of Object.values(controls)) el.addEventListener("input", drawPreview);
      drawPreview();

      const form = h("form", { class: "cv-editor", onsubmit: async event => {
        event.preventDefault();
        current.title = controls.title.value.trim();
        current.language = controls.language.value;
        current.content = Object.fromEntries(fields.map(([key]) => [key, controls[key].value.trim()]));
        let saved;
        try {
          saved = await api(current.mode === "edit" ? `/api/cvs/${current.id}` : "/api/cvs", {
            method: "POST",
            body: { title: current.title, language: current.language, content: current.content },
          });
        } catch (err) {
          status.replaceChildren(message(err.message, true));
          return;
        }
        isDirty = () => false;
        status.replaceChildren(message("CV saved."));
        await refresh(saved.id);
        layout.querySelector(`[data-focus="cv-edit:${saved.id}"]`)?.focus();
      } },
        h("div", { class: "cv-editor-head" },
          h("h2", { tabindex: "-1" }, current.mode === "edit" ? current.title
            : current.mode === "copy" ? `Copy of ${current.title.replace(/ \(copy\)$/, "")}` : "New CV"),
          current.mode === "edit" && current.id === roles.master ? h("span", { class: "tag strength" }, "Main CV") : ""),
        current.mode === "copy" ? h("p", { class: "muted" }, "This will be saved as a separate CV; the original will not change.") : "",
        current.fromExample ? h("p", { class: "cv-note" }, "This draft starts with fictional sample details. Replace them with your own before saving.") : "",
        current.fromPlan ? h("p", { class: "cv-note" }, (typeof current.fromPlan === "string"
          ? `This draft is a copy of “${current.fromPlan}” aimed at the role from What to study. `
          : "This draft was started from What to study. ") +
          "The skills to study are on the “Want to learn” row under Skills; move each one to a skills row only once you have it. Rewrite the profile for this role before saving.") : "",
        h("div", { class: "cv-grid" },
          h("label", { class: "field" }, "CV title", controls.title),
          h("label", { class: "field" }, "Language", controls.language, languageNote)),
        h("section", { class: "cv-section" }, h("div", { class: "cv-section-head" }, h("h3", null, "About you")),
          h("div", { class: "cv-grid" }, ABOUT.map(key => h("label", { class: "field" }, label(key), controls[key])))),
        SECTIONS.map(key => h("section", { class: "cv-section" },
          h("div", { class: "cv-section-head" }, h("h3", null, label(key)), fieldGuidance[key] ? h("span", { class: "muted small" }, fieldGuidance[key]) : ""),
          h("label", { class: "field" }, h("span", { class: "visually-hidden" }, label(key)), controls[key]))),
        h("div", { class: "row cv-actions" },
          h("button", { type: "submit" }, current.mode === "edit" ? "Save changes" : "Create CV")));

      if (current.mode === "edit") headActions.append(
        h("a", { class: "btn secondary", href: `/api/cvs/${current.id}/formatted.pdf`, target: "_blank", rel: "noopener",
          title: "Opens the PDF in a new tab (saved changes only)" }, "Preview PDF"),
        h("a", { class: "btn secondary", href: `/api/cvs/${current.id}/formatted.pdf?download=1`,
          title: "Saves the PDF, named after you (e.g. Aino_Makela_CV.pdf)" }, "Download PDF"),
        h("button", { type: "button", class: "secondary", "data-focus": `cv-copy:${current.id}`, onclick: () => leave(() => {
          editor = createEditorState({ ...current, id: undefined, title: `${current.title} (copy)` }, "copy"); draw();
        }) }, "Make a copy"),
        h("button", { type: "button", class: "danger secondary", "data-focus": `cv-delete:${current.id}`, onclick: async () => {
          if (!window.confirm(`Delete "${current.title}"? This cannot be undone.`)) return;
          try {
            await api(`/api/cvs/${current.id}/delete`, { method: "POST" });
            isDirty = () => false;
            await refresh();
            heading.focus();
          } catch (err) { status.replaceChildren(message(err.message, true)); }
        } }, "Delete"));

      layout.replaceChildren(versionsList(), form,
        h("aside", { class: "cv-preview" }, h("p", { class: "overline" }, "Preview"), preview,
          h("p", { class: "muted small" }, current.mode === "edit"
            ? "A rough preview. “CV as PDF” shows the real page, in the same LaTeX style as your other CVs."
            : "A rough preview. Save to see the real PDF.")));
    }

    function createEditorState(cv, mode) {
      const content = Object.fromEntries(fields.map(([key]) => [key, cv.content?.[key] || ""]));
      const editorState = { ...cv, content, mode };
      editorState.original = {
        title: cv.title || "",
        language: cv.language || "en",
        content: { ...content },
      };
      return editorState;
    }

    await refresh();
  },
});
