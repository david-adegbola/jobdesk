import { api, h, register, message, getState } from "../core.js";
import { DRAFT_AD_KEY } from "./shortlist.js";

const words = text => (text.match(/\S+/g) || []).length;

register({
  id: "draft", title: "Draft an answer",
  async render(main) {
    const state = await getState();
    const [{ cvs }, { jobs }] = await Promise.all([api("/api/cvs"), api("/api/jobs")]);
    let handed = null;
    try { handed = JSON.parse(sessionStorage.getItem(DRAFT_AD_KEY) || "null"); sessionStorage.removeItem(DRAFT_AD_KEY); }
    catch (e) { handed = null; }

    main.append(h("h1", null, "Draft an answer"),
      h("p", { class: "muted" }, "Answer a free-text question in an application, such as “Tell us about your work experience”, " +
        "using only what your CV says. Every sentence is checked against your CV; sentences it can't back up are marked, " +
        "not hidden. Nothing is sent to the employer: you copy the text yourself."));
    if (!cvs.length) {
      main.append(h("p", null, "You need a CV first. ", h("a", { href: "#/cvs" }, "Create a CV")));
      return;
    }
    if (state.llm.mode === "live" && !state.llm_opt_in) {
      main.append(h("p", { class: "msg", role: "note" }, "AI drafting is off for your account, because it sends facts from your CV " +
        "to an AI service. Turn it on under ", h("a", { href: "#/account" }, "Account → AI with your CV"), " to use it."));
    } else if (state.llm.mode !== "live") {
      main.append(h("p", { class: "muted small" }, "This server runs in mock mode: the “draft” copies facts from your CV and is labelled as mock output."));
    }

    const f = {};
    const adSource = h("select", { onchange: () => { jobField.hidden = adSource.value !== "job"; pasteField.hidden = adSource.value !== "paste"; } },
      h("option", { value: "job" }, "A job from the Jobs list"), h("option", { value: "paste" }, "Paste the ad"));
    const jobField = h("label", { class: "field" }, "Job", f.job = h("select", null, jobs.map(j => h("option", { value: j.id }, j.title))));
    const pasteField = h("label", { class: "field", style: "grid-column: 1 / -1", hidden: true }, "The ad", f.ad = h("textarea", { rows: 6 }));
    if (handed || !jobs.length) {
      adSource.value = "paste"; jobField.hidden = true; pasteField.hidden = false;
      f.ad.value = handed ? handed.text : "";
    }
    f.cv = h("select", { onchange: () => { f.language.value = cvs.find(c => String(c.id) === f.cv.value)?.language || "en"; } },
      cvs.map(cv => h("option", { value: cv.id }, cv.title)));
    f.language = h("select", null, h("option", { value: "en" }, "English"), h("option", { value: "fi" }, "Finnish"));
    f.language.value = cvs[0].language || "en";
    f.question = h("input", { required: true, maxlength: 1000, placeholder: "Tell us about your previous work experience." });
    f.limit = h("input", { type: "number", min: 10, max: 1000, value: 150, required: true });
    const out = h("div", { "aria-live": "polite" });

    main.append(h("form", { class: "card grid", onsubmit: submit },
      h("label", { class: "field" }, "The ad", adSource), jobField, pasteField,
      h("label", { class: "field" }, "CV", f.cv),
      h("label", { class: "field" }, "Answer in", f.language),
      h("label", { class: "field", style: "grid-column: 1 / -1" }, "Application question", f.question),
      h("label", { class: "field" }, "Word limit", f.limit),
      h("p", { class: "muted small", style: "grid-column: 1 / -1" },
        "Tip: answer in the same language as your CV. The check compares words, so an English CV can't confirm a Finnish sentence."),
      h("div", null, h("button", { type: "submit" }, "Draft"))), out);

    async function submit(event) {
      event.preventDefault();
      const body = { cv_id: Number(f.cv.value), question: f.question.value, word_limit: Number(f.limit.value),
                     language: f.language.value };
      if (adSource.value === "job" && f.job.value) body.job_id = Number(f.job.value);
      else body.ad_text = f.ad.value;
      out.replaceChildren(h("p", { class: "muted", role: "status" }, "Drafting…"));
      try { show(await api("/api/draft", { method: "POST", body })); }
      catch (error) { out.replaceChildren(message(error.message, true)); }
    }

    function show(d) {
      const factText = Object.fromEntries(d.facts.map(fact => [fact.id, fact.text]));
      const supported = d.sentences.filter(s => s.status === "supported");
      const unsupported = d.sentences.length - supported.length;
      const editor = h("textarea", { rows: 8, "aria-label": "Your answer (edit before using it)" });
      editor.value = supported.map(s => s.text).join(" ");
      const counter = h("p", { class: "small", role: "status" });
      const count = () => {
        const n = words(editor.value);
        counter.textContent = `${n} / ${d.word_limit} words` + (n > d.word_limit ? " – over the limit" : "");
        counter.className = "small" + (n > d.word_limit ? " overdue" : "");
      };
      editor.addEventListener("input", count);
      count();
      const copy = h("button", { type: "button", class: "secondary", onclick: async () => {
        try { await navigator.clipboard.writeText(editor.value); copy.textContent = "Copied"; }
        catch (e) { copy.textContent = "Select the text and copy it"; }
      } }, "Copy answer");
      out.replaceChildren(
        d.notice ? h("p", { class: "muted small" }, d.notice) : "",
        d.ad_blockers.length ? h("p", { class: "msg" }, "The ad asks for things your CV doesn't show, so the draft must not claim them: " +
          d.ad_blockers.join(", ") + ".") : "",
        h("h2", null, "Checked sentences"),
        h("ol", { class: "draft-sentences" }, d.sentences.map(s => h("li", { class: s.status },
          s.status === "unsupported" ? h("strong", null, "UNSUPPORTED: ") : "", s.text,
          s.reasons.length ? h("ul", { class: "small" }, s.reasons.map(r => h("li", null, r))) : "",
          s.fact_ids.length ? h("div", { class: "muted small" }, "From your CV: " +
            s.fact_ids.map(id => factText[id] ? `${id} “${factText[id]}”` : id).join(" · ")) : ""))),
        h("h2", null, "Your answer"),
        unsupported ? h("p", { class: "msg err" }, `${unsupported} unsupported sentence${unsupported === 1 ? " was" : "s were"} left out of the box below. ` +
          "Add one back only if it is true and you can show it.") : "",
        editor, counter, copy);
    }
  },
});
