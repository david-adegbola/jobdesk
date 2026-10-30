import { api, h, register, message } from "../core.js";

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {          // older browsers / no permission: select-and-copy fallback
    const t = h("textarea", { style: "position:fixed;opacity:0" }, text);
    document.body.append(t); t.select();
    try { document.execCommand("copy"); } catch (e2) { /* nothing else to try */ }
    t.remove();
  }
  const old = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = old; }, 1500);
}

register({
  id: "cvs", title: "CVs",
  async render(main) {
    const { roles, pdflatex } = await api("/api/roles");
    const out = h("div");
    const buildBtn = h("button", { class: "secondary", onclick: async () => {
        buildBtn.disabled = true; buildBtn.textContent = "Building…";
        try { const r = await api("/api/build", { method: "POST" }); out.replaceChildren(message(r.message, !r.ok)); }
        catch (e) { out.replaceChildren(message(e.message, true)); }
        buildBtn.disabled = false; buildBtn.textContent = "Build PDFs";
      } }, "Build PDFs");
    main.append(h("h1", null, "CVs"),
      h("p", { class: "muted" }, "Send employers the employer link: one page with your contact details and that role's CV only. " +
        "PDF links point at the published site, so they show the version last pushed to GitHub."),
      h("div", { class: "row" }, buildBtn,
        h("span", { class: "muted small" }, pdflatex ? "Compiles every CV here with pdflatex." : "pdflatex isn't installed here: push to GitHub to build.")),
      out,
      h("div", { class: "scroll" }, h("table", null,
        h("thead", null, h("tr", null, ["Role", "PDFs", "Employer link", "Last updated", "Applications"].map(t => h("th", null, t)))),
        h("tbody", null, roles.map(r => {
          const btn = h("button", { class: "secondary small", onclick: e => copy(r.employer_link, e.target) }, "Copy employer link");
          const pdf = (key, label) => r.pdfs[key] ? h("a", { class: "tag", href: r.pdfs[key], target: "_blank", rel: "noopener" }, label) : "";
          return h("tr", null,
            h("td", null, h("strong", null, r.title), h("div", { class: "muted small" }, `roles/${r.slug}/`)),
            h("td", null, pdf("combined", "FI + EN"), pdf("fi", "FI"), pdf("en", "EN"),
              !r.pdfs.combined ? h("div", { class: "muted small" }, "No combined PDF: needs both languages") : ""),
            h("td", null, h("a", { href: r.employer_link, target: "_blank", rel: "noopener", class: "small" }, r.employer_link),
              h("div", null, btn)),
            h("td", { class: "nowrap" }, r.updated),
            h("td", null, r.applications));
        })))));
  },
});
