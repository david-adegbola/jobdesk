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
  ["certifications", "Certifications", "Sertifikaatit", "textarea"],
  ["languages", "Languages", "Kielitaito", "textarea"],
  ["links", "Links", "Linkit", "textarea"],
];

const blankCv = () => ({
  title: "Forestry CV",
  language: "en",
  content: Object.fromEntries(fields.map(([key]) => [key, ""])),
});

function printableText(value) {
  return String(value || "").split(/\r?\n/).map(line => line.trim()).filter(Boolean);
}

function preview(cv) {
  const content = cv.content || {};
  const finnish = cv.language === "fi";
  return h("article", { class: "cv-print-view" },
    h("header", { class: "cv-heading" },
      h("h1", null, content.full_name || cv.title || "Curriculum vitae"),
      content.target_role ? h("p", { class: "cv-target" }, content.target_role) : "",
      h("p", { class: "cv-contact" }, [content.email, content.phone, content.location].filter(Boolean).join(" · "))),
    ...fields.filter(([key]) => !["full_name", "email", "phone", "location", "target_role"].includes(key))
      .filter(([key]) => printableText(content[key]).length)
      .map(([key, label, labelFi]) => h("section", { class: "cv-section" },
        h("h2", null, finnish ? labelFi : label),
        ...printableText(content[key]).map(line => h("p", null, line)))));
}

register({
  id: "cvs", title: "My CVs",
  async render(main) {
    main.append(h("h1", null, "My CVs"),
      h("p", { class: "muted" }, "Private to your account. Create separate Finnish and English CVs, then print or save as PDF from your browser."));
    let cvs = [];
    let editor = null;
    const area = h("div");
    const status = h("div", { role: "status" });
    main.append(status, area);

    async function refresh() {
      try {
        cvs = (await api("/api/cvs")).cvs;
        editor = null;
        draw();
      } catch (err) {
        status.replaceChildren(message(err.message, true));
      }
    }

    function draw() {
      area.replaceChildren();
      if (editor) {
        renderEditor();
        return;
      }
      area.append(h("div", { class: "row cv-actions" },
        h("button", { onclick: () => { editor = blankCv(); draw(); } }, "Create a CV")));
      if (!cvs.length) {
        area.append(h("p", { class: "empty" }, "You haven't created a CV yet."));
        return;
      }
      area.append(h("div", { class: "grid cv-list" }, ...cvs.map(cv =>
        h("article", { class: "card cv-card" },
          h("h2", null, cv.title),
          h("p", { class: "muted small" }, `${cv.language.toUpperCase()} · Updated ${cv.updated_at || "recently"}`),
          h("div", { class: "row" },
            h("button", { onclick: () => { editor = { ...cv, content: { ...cv.content } }; draw(); } }, "Edit"),
            h("button", { class: "secondary", onclick: () => printCv(cv) }, "Print / Save PDF"),
            h("button", { class: "secondary", onclick: () => {
              editor = { ...cv, id: undefined, title: `${cv.title} (copy)`, content: { ...cv.content } };
              draw();
            } }, "Copy"),
            h("button", { class: "danger secondary", onclick: async () => {
              if (!window.confirm(`Delete "${cv.title}"? This cannot be undone.`)) return;
              try {
                await api(`/api/cvs/${cv.id}/delete`, { method: "POST" });
                await refresh();
              } catch (err) { status.replaceChildren(message(err.message, true)); }
            } }, "Delete"))))));
    }

    function renderEditor() {
      const current = editor;
      const values = current.content || (current.content = {});
      const controls = {};
      const form = h("form", { class: "cv-editor", onsubmit: async event => {
        event.preventDefault();
        current.title = controls.title.value.trim();
        current.language = controls.language.value;
        current.content = Object.fromEntries(fields.map(([key]) => [key, controls[key].value.trim()]));
        let saved;
        try {
          saved = await api(current.id ? `/api/cvs/${current.id}` : "/api/cvs", {
            method: "POST",
            body: { title: current.title, language: current.language, content: current.content },
          });
        } catch (err) {
          status.replaceChildren(message(err.message, true));
          return;
        }
        current.id = saved.id;
        status.replaceChildren(message("CV saved."));
        try {
          cvs = (await api("/api/cvs")).cvs;
          editor = null;
          draw();
        } catch (err) {
          status.replaceChildren(message(`CV saved, but the list could not be refreshed: ${err.message}`, true));
        }
      } },
      h("label", { class: "field" }, "CV title",
        controls.title = h("input", { value: current.title || "", required: true, maxlength: 120 })),
      h("label", { class: "field" }, "Language",
        controls.language = h("select", null,
          h("option", { value: "en", selected: current.language === "en" }, "English"),
          h("option", { value: "fi", selected: current.language === "fi" }, "Suomi"))),
      ...fields.map(([key, label, , type]) =>
        h("label", { class: "field" }, label,
          controls[key] = type === "textarea"
            ? h("textarea", { name: key, rows: key === "summary" ? 4 : 6, maxlength: 12000, placeholder: "One item or paragraph per line", value: values[key] || "" })
            : h("input", { name: key, type, maxlength: 500, value: values[key] || "" }))),
      h("div", { class: "row cv-actions" },
        h("button", { type: "submit" }, "Save CV"),
        h("button", { type: "button", class: "secondary", onclick: () => { editor = null; draw(); } }, "Cancel"),
        current.id ? h("button", { type: "button", class: "secondary", onclick: () => printCv(current) }, "Print / Save PDF") : ""));
      area.append(form,
        h("h2", null, "Preview"),
        h("p", { class: "muted small" }, "Use your browser’s print dialog and choose “Save as PDF” to download this CV."),
        h("div", { class: "cv-preview" }, preview(current)));
    }

    function printCv(cv) {
      const printArea = area.querySelector(".cv-preview");
      if (editor) {
        const values = editor.content || {};
        for (const [key] of fields) values[key] = area.querySelector(`[name="${key}"]`)?.value || values[key] || "";
        editor.title = area.querySelector(".cv-editor input")?.value || editor.title;
        editor.language = area.querySelector(".cv-editor select")?.value || editor.language;
        printArea?.replaceChildren(preview(editor));
      }
      const printOnly = h("div", { class: "print-only" }, preview(editor || cv));
      main.append(printOnly);
      document.body.classList.add("printing-cv");
      window.print();
      window.setTimeout(() => {
        printOnly.remove();
        document.body.classList.remove("printing-cv");
      }, 1000);
    }

    await refresh();
  },
});
