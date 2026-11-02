import { api, h, register, message } from "../core.js";

// Plain-text call script for the clipboard: each Finnish line with its English underneath
const scriptText = lines => lines.map(l => `${l.fi}\n(${l.en})`).join("\n\n");

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch (e) {                     // older browsers or a page that isn't https
    const ta = h("textarea", { class: "offscreen", "aria-hidden": "true" }, text);
    document.body.append(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok;
  }
}

// A question or blocker answer: Finnish and English text, with Edit / Save / Back to draft
function answer(item, type, reload) {
  const box = h("div", { class: "answer" });
  const view = () => box.replaceChildren(...[
    item.a_fi || item.a_en
      ? [h("p", { class: "fi" }, item.a_fi), h("p", { class: "en" }, item.a_en)]
      : h("p", { class: "muted hint" }, item.hint || "No answer yet."),
    h("div", { class: "answer-actions no-print" },
      item.edited ? h("span", { class: "tag status", "data-status": "Applied" }, "your edit") : "",
      h("button", { class: "link small", onclick: edit }, item.a_fi || item.a_en ? "Edit" : "Write answer"))].flat());
  const save = async (fi, en) => {
    await api("/api/prep/answer", { method: "POST", body: { type, id: item.id, a_fi: fi, a_en: en } });
    reload();
  };
  function edit() {
    const fi = h("textarea", { rows: 3 }, item.a_fi), en = h("textarea", { rows: 3 }, item.a_en);
    const err = h("div");
    box.replaceChildren(h("form", { class: "answer-form", onsubmit: async e => {
        e.preventDefault();
        try { await save(fi.value, en.value); } catch (x) { err.replaceChildren(message(x.message, true)); }
      } },
      h("label", { class: "field" }, "Suomeksi", fi),
      h("label", { class: "field" }, "In English", en),
      h("div", { class: "row" },
        h("button", { type: "submit", class: "small" }, "Save"),
        h("button", { type: "button", class: "secondary small", onclick: view }, "Cancel"),
        item.edited ? h("button", { type: "button", class: "link small", onclick: () => save("", "") }, "Back to draft") : "",
        h("span", { class: "muted small" }, "Saved answers are reused for every job of this type.")),
      err));
    fi.focus();
  }
  view();
  return box;
}

register({
  id: "prep", title: "Prep",
  async render(main, query) {
    const params = new URLSearchParams(query);
    const jobId = params.get("job");
    if (!jobId) {
      const { jobs } = await api("/api/jobs");
      const rank = j => ({ Interview: 0, Applied: 1, Saved: 2 }[j.status] ?? 3);
      jobs.sort((a, b) => rank(a) - rank(b) || (b.posted || "").localeCompare(a.posted || ""));
      main.append(h("h1", null, "Prep"),
        h("p", { class: "muted" }, "Call script and interview answers for one job. Pick the job, or use the Prep link on the Jobs page or a tracker card."),
        h("label", { class: "field narrow" }, "Job",
          h("select", { onchange: e => { if (e.target.value) location.hash = `#/prep?job=${e.target.value}`; } },
            h("option", { value: "" }, "Choose a job…"),
            jobs.map(j => h("option", { value: j.id }, `${j.status ? `[${j.status}] ` : ""}${j.title}${j.company ? ` – ${j.company}` : ""}`)))));
      return;
    }

    let type = params.get("type") || "";
    const body = h("div");
    main.append(body);

    async function load() {
      const p = await api(`/api/prep/${jobId}${type ? "/" + type : ""}`);
      type = p.type;
      const j = p.job;
      const copied = h("span", { class: "muted small", role: "status" });
      body.replaceChildren(...[
        h("p", { class: "eyebrow" }, `Prep · ${p.type_label}`),
        h("h1", null, j.url ? h("a", { href: j.url, target: "_blank", rel: "noopener" }, j.title) : j.title),
        h("p", { class: "muted" }, [j.company, j.location].filter(Boolean).join(" · "),
          j.contact_name || j.contact_phone ? [" · ", j.contact_name, " ",
            j.contact_phone ? h("a", { class: "nowrap", href: `tel:${j.contact_phone.replace(/\s/g, "")}` }, j.contact_phone) : ""] : "",
          p.status ? [" ", h("span", { class: "tag status", "data-status": p.status }, p.status)] : ""),
        h("div", { class: "row no-print" },
          h("button", { onclick: async () => { copied.textContent = await copy(scriptText(p.script)) ? "Call script copied." : "Couldn't copy."; } },
            "Copy call script"),
          h("button", { class: "secondary", onclick: () => window.print() }, "Print"),
          h("label", { class: "field inline" }, "Job type",
            h("select", { onchange: e => { type = e.target.value; load(); } },
              Object.entries(p.types).map(([k, label]) => h("option", { value: k, selected: k === p.type }, label)))),
          copied),

        h("h2", null, "Call script"),
        h("ol", { class: "script card" }, p.script.map(l => h("li", null, h("p", { class: "fi" }, l.fi), h("p", { class: "en" }, l.en)))),

        p.blockers.length ? [
          h("h2", null, "Honest answers to blockers"),
          h("p", { class: "muted small no-print" }, "What this ad asks for that you don't have yet."),
          h("div", { class: "qa" }, p.blockers.map(b => h("section", { class: "qa-item" },
            h("h3", null, h("span", { class: "tag bad" }, b.label)), answer(b, type, load))))] : "",

        h("h2", null, "Likely questions"),
        h("div", { class: "qa" }, p.questions.map((q, i) => h("section", { class: "qa-item" },
          h("h3", null, h("span", { class: "num" }, `${i + 1}.`), " ", q.q_fi, h("span", { class: "en" }, q.q_en)),
          answer(q, type, load)))),

        h("h2", null, "Questions to ask them"),
        h("ol", { class: "script card" }, p.ask.map(a => h("li", null, h("p", { class: "fi" }, a.fi), h("p", { class: "en" }, a.en))))].flat());
      document.title = `Prep: ${j.title} · Woodesk`;
    }
    await load();
  },
});
