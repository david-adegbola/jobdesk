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

const fieldGuidance = {
  summary: "Write in paragraphs and leave a blank line between paragraphs.",
  education: "One row per qualification: dates: qualification, institution.",
  experience: "Start each entry with dates, e.g. Aug 2025--Oct 2025: Job title — Employer. Add one detail per line; leave a blank line between entries. Optional final row: Tags: tag-one, tag-two.",
  skills: "One row per group: label: skills or knowledge.",
  projects: "Use the same dated entry format as Work Experience.",
  hobbies: "Optional section, shown after Projects and before References.",
  certifications: "These appear as a Cards row under Skills.",
  languages: "These appear as a Languages row under Skills.",
  links: "One link per row: label: https://example.com",
};

register({
  id: "cvs", title: "My CVs",
  async render(main) {
    main.append(h("h1", { tabindex: "-1", "data-focus": "cv-heading" }, "My CVs"),
      h("p", { class: "muted" }, "Private to your account. Create Finnish or English CVs and view their formatted PDFs. Use your browser's PDF viewer to download a copy."));
    let cvs = [];
    let example = null;
    let editor = null;
    let returnFocus = null;
    const area = h("div");
    const status = h("div", { role: "status" });
    main.append(status, area);

    async function refresh() {
      try {
        const [cvList, exampleResult] = await Promise.all([
          api("/api/cvs"),
          api("/api/cvs/example"),
        ]);
        cvs = cvList.cvs;
        example = exampleResult.cv;
        editor = null;
        draw();
      } catch (err) {
        status.replaceChildren(message(err.message, true));
        returnFocus = null;
      }
    }

    function draw() {
      area.replaceChildren();
      if (editor) {
        renderEditor();
        return;
      }
      const restoreFocus = () => {
        if (!returnFocus) return;
        const target = [...main.querySelectorAll("[data-focus]")].find(el => el.dataset.focus === returnFocus)
          || main.querySelector('[data-focus="cv-heading"]');
        target?.focus();
        returnFocus = null;
      };
      area.append(h("article", { class: "card cv-example" },
        h("h2", null, "Start with a two-page example"),
        h("p", null, "Preview a sample CV in the original LaTeX style. Its details are fictional; Create yours opens an editable draft with the same structure. Nothing is saved until you save it."),
        h("div", { class: "row cv-actions" },
          h("a", {
            class: "btn secondary",
            href: "/api/cvs/example.pdf",
            target: "_blank",
            rel: "noopener",
          }, "View 2-page example"),
          h("button", { "data-focus": "cv-create", onclick: () => {
            returnFocus = "cv-create";
            editor = createEditorState(example, "create");
            editor.fromExample = true;
            draw();
          } }, "Create yours"))));
      if (!cvs.length) {
        area.append(h("p", { class: "empty" }, "Your saved CVs will appear here."));
        restoreFocus();
        return;
      }
      area.append(h("h2", { "data-focus": "cv-list-heading", tabindex: "-1" }, "Your CVs"),
        h("div", { class: "grid cv-list" }, ...cvs.map(cv =>
        h("article", { class: "card cv-card" },
          h("h2", null, cv.title),
          h("p", { class: "muted small" }, `${cv.language.toUpperCase()} · Updated ${cv.updated_at || "recently"}`),
          h("p", { class: "row" },
            h("a", {
              href: `/api/cvs/${cv.id}/formatted.pdf`,
              target: "_blank",
              rel: "noopener",
            }, "View CV")),
          h("p", { class: "muted small" }, "Edit changes this CV. Make a copy creates a separate CV with the same details."),
          h("div", { class: "row" },
            h("button", { "data-focus": `cv-edit:${cv.id}`, onclick: () => {
              returnFocus = `cv-edit:${cv.id}`;
              editor = createEditorState(cv, "edit");
              draw();
            } }, "Edit"),
            h("button", { class: "secondary", "data-focus": `cv-copy:${cv.id}`, onclick: () => {
              returnFocus = `cv-copy:${cv.id}`;
              editor = createEditorState(
                { ...cv, id: undefined, title: `${cv.title} (copy)` },
                "copy",
              );
              draw();
            } }, "Make a copy"),
            h("button", { class: "danger secondary", onclick: async () => {
              if (!window.confirm(`Delete "${cv.title}"? This cannot be undone.`)) return;
              try {
                await api(`/api/cvs/${cv.id}/delete`, { method: "POST" });
                returnFocus = "cv-list-heading";
                await refresh();
              } catch (err) { status.replaceChildren(message(err.message, true)); }
            }, "data-focus": `cv-delete:${cv.id}` }, "Delete"))))));
      restoreFocus();
    }

    function renderEditor() {
      const current = editor;
      const values = current.content || (current.content = {});
      const controls = {};
      const returnToList = () => {
        const changed = controls.title.value.trim() !== current.original.title
          || controls.language.value !== current.original.language
          || fields.some(([key]) =>
            controls[key].value.trim() !== (current.original.content[key] || ""));
        if (changed && !window.confirm("Discard your unsaved changes and return to My CVs?")) return;
        editor = null;
        draw();
      };
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
        current.id = saved.id;
        current.mode = "edit";
        current.original = {
          title: current.title,
          language: current.language,
          content: { ...current.content },
        };
        status.replaceChildren(message("CV saved."));
        try {
          cvs = (await api("/api/cvs")).cvs;
          editor = null;
          returnFocus = `cv-edit:${saved.id}`;
          draw();
        } catch (err) {
          status.replaceChildren(message(`CV saved, but the list could not be refreshed: ${err.message}`, true));
        }
      } },
      h("div", { class: "row cv-actions" },
        h("button", { type: "button", class: "secondary", onclick: returnToList }, "Back to My CVs")),
      h("h2", { tabindex: "-1" }, current.mode === "edit"
        ? `Editing ${current.title}`
        : current.mode === "copy"
          ? `Create a copy of ${current.title.replace(/ \(copy\)$/, "")}`
          : "Create a CV"),
      current.mode === "copy"
        ? h("p", { class: "muted" }, "This will be saved as a separate CV; the original will not change.")
        : "",
      current.fromExample
        ? h("p", { class: "muted" }, "This draft starts with fictional sample details. Replace them with your own before saving.")
        : "",
      h("label", { class: "field" }, "CV title",
        controls.title = h("input", { value: current.title || "", required: true, maxlength: 120 })),
      h("label", { class: "field" }, "Language",
        controls.language = h("select", null,
          h("option", { value: "en", selected: current.language === "en" }, "English"),
          h("option", { value: "fi", selected: current.language === "fi" }, "Suomi"))),
      ...fields.map(([key, label, , type]) =>
        h("label", { class: "field" }, label,
          controls[key] = type === "textarea"
            ? h("textarea", {
              name: key,
              rows: key === "summary" ? 4 : 6,
              maxlength: 12000,
              value: values[key] || "",
            })
            : h("input", { name: key, type, maxlength: 500, value: values[key] || "" }),
          fieldGuidance[key] ? h("span", { class: "muted small" }, fieldGuidance[key]) : "")),
      h("div", { class: "row cv-actions" },
        h("button", { type: "submit" }, current.mode === "edit" ? "Save changes" : "Create CV"),
        h("button", { type: "button", class: "secondary", onclick: returnToList }, "Back to My CVs")));
      area.append(form);
      form.querySelector("h2")?.focus();
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
