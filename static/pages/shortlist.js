import { api, h, register, message, getState } from "../core.js";
import { FINNISH, METHOD, feedbackControls } from "../finnish.js";

// Hands one ad to the Draft page (sessionStorage, this tab only).
export const DRAFT_AD_KEY = "jobdesk:draft-ad";

// Skills from a CV's Skills field: "GIS: QGIS and map reading" -> ["QGIS", "map reading"].
// "Want to learn" rows are skipped: wanting a skill is not having it.
export function skillsFromCv(cv) {
  const rows = (cv?.content?.skills || "").split("\n").map(r => r.trim()).filter(Boolean);
  return rows.filter(r => !/^(want to learn|haluan oppia)\s*:/i.test(r))
    .flatMap(r => (r.includes(":") ? r.slice(r.indexOf(":") + 1) : r).split(/,| and | ja /))
    .map(s => s.trim()).filter(Boolean);
}

register({
  id: "shortlist", title: "Shortlist",
  async render(main) {
    const state = await getState();
    const { cvs } = await api("/api/cvs");
    const out = h("div", { "aria-live": "polite" });
    const f = {};
    const source = h("select", { "aria-label": "Where the ads come from", onchange: showSource },
      h("option", { value: "paste" }, "Paste ads"), h("option", { value: "csv" }, "Upload a CSV"),
      h("option", { value: "urls" }, "Paste links"));
    const pasteBox = h("label", { class: "field", style: "grid-column: 1 / -1" }, "Ads (separate ads with a line containing only ---)",
      f.ads = h("textarea", { rows: 12, placeholder: "Summer trainee, data analysis\nWe expect good SQL skills. Finnish is an advantage.\n---\nNext ad…" }));
    const csvBox = h("label", { class: "field", style: "grid-column: 1 / -1", hidden: true }, "CSV file (column ad_text; title and url optional)",
      f.csv = h("input", { type: "file", accept: ".csv,text/csv" }));
    const urlBox = h("label", { class: "field", style: "grid-column: 1 / -1", hidden: true }, "Links to job ads, one per line (at most 10; sites that don't allow automatic reading are skipped)",
      f.urls = h("textarea", { rows: 5, placeholder: "https://…" }));
    function showSource() {
      pasteBox.hidden = source.value !== "paste";
      csvBox.hidden = source.value !== "csv";
      urlBox.hidden = source.value !== "urls";
    }
    const cvPicker = h("select", { onchange: () => { f.skills.value = skillsFromCv(cvs.find(c => String(c.id) === cvPicker.value)).join(", "); } },
      h("option", { value: "" }, "Type them below"), cvs.map(cv => h("option", { value: cv.id }, cv.title)));
    f.skills = h("textarea", { rows: 2, placeholder: "Python, SQL, Excel, customer service" });
    if (cvs.length) { cvPicker.value = String(cvs[0].id); f.skills.value = skillsFromCv(cvs[0]).join(", "); }

    main.append(h("h1", null, "Shortlist"),
      h("p", { class: "muted" }, "Paste up to 20 job or internship ads. For each one you see what it says about Finnish, " +
        "the exact sentence it's based on, and how well it fits your skills. Ads you can realistically apply to come first."),
      state.llm.mode === "live" ? "" : h("p", { class: "muted small" },
        "AI checking is off on this server, so the keyword rule is used: it can say “required” or “unclear”, but can't tell “an advantage” from “not needed”."),
      h("form", { class: "card grid", onsubmit: submit },
        h("label", { class: "field" }, "Ads come from", source), pasteBox, csvBox, urlBox,
        h("label", { class: "field" }, "Skills from my CV", cvPicker),
        h("label", { class: "field", style: "grid-column: 1 / -1" }, "My skills (separated by commas)", f.skills),
        h("p", { class: "muted small", style: "grid-column: 1 / -1" },
          `Your Finnish: ${state.finnish_level} (change it on the Account page). Only the ads' text is sent to the AI service; your skills stay here.`),
        h("div", null, h("button", { type: "submit" }, "Check the ads"))),
      out);

    async function submit(event) {
      event.preventDefault();
      const body = { skills: f.skills.value.split(",").map(s => s.trim()).filter(Boolean).slice(0, 30) };
      if (source.value === "csv") {
        if (!f.csv.files[0]) return out.replaceChildren(message("Choose a CSV file.", true));
        body.csv_text = await f.csv.files[0].text();
      } else if (source.value === "urls") body.urls_text = f.urls.value;
      else body.ads_text = f.ads.value;
      out.replaceChildren(h("p", { class: "muted", role: "status" }, "Checking the ads…"));
      try { show(await api("/api/shortlist", { method: "POST", body })); }
      catch (error) { out.replaceChildren(message(error.message, true)); }
    }

    function show(result) {
      const errors = result.errors.length ? h("div", { class: "msg err", role: "alert" },
        h("p", null, "Some input was skipped:"), h("ul", null, result.errors.map(e => h("li", null, `${e.item}: ${e.message}`)))) : "";
      if (!result.rows.length) return out.replaceChildren(errors);
      const hide = h("input", { type: "checkbox", onchange: () => {
        for (const tr of table.querySelectorAll("tbody tr")) tr.hidden = hide.checked && tr.dataset.level === "required";
      } });
      const table = h("table", null,
        h("thead", null, h("tr", null, ["Rank", "Ad", "Finnish", "Evidence from the ad", "Your skills", ""].map(t => h("th", null, t)))),
        h("tbody", null, result.rows.map((row, i) => {
          const fin = row.finnish;
          const [label, cls] = FINNISH[fin.level] || FINNISH.unclear;
          return h("tr", { "data-level": fin.level },
            h("td", null, h("strong", null, i + 1)),
            h("td", null, row.url ? h("a", { href: row.url, target: "_blank", rel: "noopener" }, row.title) : row.title),
            h("td", null, h("span", { class: cls }, label), h("div", { class: "muted small" }, METHOD[fin.method] || ""),
              feedbackControls(fin, null)),
            h("td", null, fin.evidence?.length ? h("q", null, fin.evidence[0]) : "",
              h("div", { class: "small" }, fin.explanation_en || "")),
            h("td", null, row.matched_skills.join(", ") || "–", h("div", { class: "muted small" }, `${row.skill_score}% of your skills`)),
            h("td", null, h("button", { class: "link small", type: "button", onclick: () => {
              try { sessionStorage.setItem(DRAFT_AD_KEY, JSON.stringify({ title: row.title, text: row.ad_text })); } catch (e) { /* storage blocked */ }
              location.hash = "#/draft";
            } }, "Draft an answer")));
        })));
      out.replaceChildren(errors,
        h("p", { class: "row" }, h("label", { class: "check" }, hide, " Hide “Finnish required” ads")),
        h("div", { class: "scroll" }, table),
        h("p", { class: "muted small" }, "Order: Finnish not needed, then an advantage, then unclear, then required" +
          (result.finnish_level === "fluent" ? " (ignored, because you said your Finnish is fluent)" : "") +
          "; within each group, ads that match more of your skills come first. Always read the ad itself before applying."));
    }
  },
});
