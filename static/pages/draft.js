// Applications → Draft an answer: the question on the left, the answer workspace on the right. The draft uses only
// facts from the CV; every sentence is checked, and sentences the CV can't back up are shown but kept out of the answer.
import { api, h, register, message, getState } from "../core.js";
import { DRAFT_AD_KEY } from "./shortlist.js";

const words = text => (text.match(/\S+/g) || []).length;

register({
  id: "draft", title: "Draft an answer",
  async render(main) {
    const state = await getState();
    const [{ cvs }, { jobs }] = await Promise.all([api("/api/cvs"), api("/api/jobs?scope=mine")]);
    let handed = null;
    try { handed = JSON.parse(sessionStorage.getItem(DRAFT_AD_KEY) || "null"); sessionStorage.removeItem(DRAFT_AD_KEY); }
    catch (e) { handed = null; }

    main.append(h("div", { class: "page-head" }, h("div", null,
      h("h1", null, "Draft an ", h("span", { class: "serif" }, "answer")),
      h("p", { class: "muted" }, "For a free-text question in an application or an interview, such as “Tell us about your work experience”. " +
        "The draft uses only what your CV says, and every sentence is checked against it. Nothing is sent to the employer: you copy the text yourself."))));
    if (!cvs.length) {
      main.append(h("div", { class: "empty-state" }, h("p", { class: "empty-title" }, "You need a CV first"),
        h("p", null, "Answers are written only from your CV. ", h("a", { href: "#/cvs" }, "Fill in your CV"), ".")));
      return;
    }
    const modeNote = state.llm.mode === "live" && !state.llm_opt_in
      ? h("p", { class: "msg", role: "note" }, "AI drafting is off for your account, because it sends facts from your CV " +
        "to an AI service. Turn it on under ", h("a", { href: "#/account" }, "Profile → AI with your CV"), " to use it.")
      : state.llm.mode !== "live" ? h("p", { class: "muted small" }, "This server runs in mock mode: the “draft” copies facts from your CV and is labelled as mock output.") : "";

    const f = {};
    const adSource = h("select", { onchange: () => { jobField.hidden = adSource.value !== "job"; pasteField.hidden = adSource.value !== "paste"; } },
      h("option", { value: "job" }, "One of my jobs"), h("option", { value: "paste" }, "Paste the ad"));
    // Your active jobs first (not rejected or "not a fit"), then the ones you collected without a status
    const rank = j => j.status && !["Rejected", "Not a fit"].includes(j.status) ? 0 : j.status ? 2 : 1;
    const choices = jobs.filter(j => rank(j) < 2).sort((a, b) => rank(a) - rank(b));
    const jobField = h("label", { class: "field" }, "Job", f.job = h("select", null, choices.map(j => h("option", { value: j.id }, `${j.title}${j.company ? ` – ${j.company}` : ""}`))));
    const pasteField = h("label", { class: "field", hidden: true }, "The ad", f.ad = h("textarea", { rows: 6 }));
    if (handed || !choices.length) {
      adSource.value = "paste"; jobField.hidden = true; pasteField.hidden = false;
      f.ad.value = handed ? handed.text : "";
    }
    f.cv = h("select", { onchange: () => { f.language.value = cvs.find(c => String(c.id) === f.cv.value)?.language || "en"; } },
      cvs.map(cv => h("option", { value: cv.id }, cv.title)));
    f.language = h("select", null, h("option", { value: "en" }, "English"), h("option", { value: "fi" }, "Finnish"));
    f.language.value = cvs[0].language || "en";
    f.question = h("textarea", { required: true, maxlength: 1000, rows: 3, placeholder: "Tell us about your previous work experience." });
    f.limit = h("input", { type: "number", min: 10, max: 1000, value: 150, required: true });
    const draftBtn = h("button", { type: "submit" }, "Draft my answer");

    const out = h("section", { class: "answer-workspace", "aria-live": "polite", "aria-label": "Your answer" },
      h("div", { class: "empty-state" }, h("p", { class: "empty-title" }, "Your answer appears here"),
        h("p", null, "Write the question on the left, then Draft my answer. You'll get a draft from your CV facts, checked sentence by sentence, to edit and copy.")));

    main.append(h("div", { class: "draft-layout" },
      h("form", { class: "card draft-form", onsubmit: submit },
        h("label", { class: "field" }, "Application question", f.question),
        h("div", { class: "cv-grid" }, h("label", { class: "field" }, "About", adSource), jobField),
        pasteField,
        h("div", { class: "cv-grid" }, h("label", { class: "field" }, "CV", f.cv), h("label", { class: "field" }, "Answer in", f.language),
          h("label", { class: "field" }, "Word limit", f.limit)),
        h("p", { class: "muted small" }, "Answer in the same language as your CV. The check compares words, so an English CV can't confirm a Finnish sentence."),
        modeNote, h("div", null, draftBtn)),
      out));

    async function submit(event) {
      event.preventDefault();
      const body = { cv_id: Number(f.cv.value), question: f.question.value, word_limit: Number(f.limit.value),
                     language: f.language.value };
      if (adSource.value === "job" && f.job.value) body.job_id = Number(f.job.value);
      else body.ad_text = f.ad.value;
      draftBtn.disabled = true;
      out.replaceChildren(h("div", { class: "prep-progress", role: "status" }, h("strong", null, "Drafting…"),
        h("span", null, "Picking facts from your CV, writing, then checking every sentence against your CV.")));
      try { show(await api("/api/draft", { method: "POST", body }), body.question); }
      catch (error) { out.replaceChildren(message(error.message, true)); }
      finally { draftBtn.disabled = false; }
    }

    function show(d, question) {
      const factText = Object.fromEntries(d.facts.map(fact => [fact.id, fact.text]));
      const supported = d.sentences.filter(s => s.status === "supported");
      const unsupported = d.sentences.length - supported.length;
      const editor = h("textarea", { rows: 7, class: "answer-text", "aria-label": "Your answer (edit before using it)" });
      editor.value = supported.map(s => s.text).join(" ");
      const counter = h("span", { class: "tag", role: "status" });
      const count = () => {
        const n = words(editor.value);
        counter.textContent = `${n} / ${d.word_limit} words` + (n > d.word_limit ? ", over the limit" : "");
        counter.className = "tag" + (n > d.word_limit ? " gap" : "");
      };
      const fit = () => { editor.style.height = "auto"; editor.style.height = `${editor.scrollHeight + 3}px`; };
      editor.addEventListener("input", () => { count(); fit(); });
      count();
      requestAnimationFrame(fit);
      const copy = h("button", { type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(editor.value); copy.textContent = "Copied"; }
        catch (e) { copy.textContent = "Select the text and copy it"; }
      } }, "Copy answer");
      out.replaceChildren(
        h("p", { class: "overline" }, "Your answer to"),
        h("h2", { class: "answer-question" }, question),
        d.ad_blockers.length ? h("p", { class: "msg" }, "The ad asks for things your CV doesn't show, so the draft doesn't claim them: " +
          d.ad_blockers.join(", ") + ". Say honestly whether you're working towards them.") : "",
        h("div", { class: "answer-draft" },
          h("span", { class: "tag ai" }, d.notice ? "Copied from your CV facts" : "Draft from your CV · every sentence checked"),
          editor),
        h("p", { class: "prep-check-tags" },
          h("span", { class: "tag strength" }, `${supported.length} of ${d.sentences.length} sentences from your CV`), counter),
        unsupported ? h("p", { class: "msg err" }, `${unsupported} sentence${unsupported === 1 ? " wasn't" : "s weren't"} backed by your CV, so ${unsupported === 1 ? "it was" : "they were"} left out. ` +
          "Add one back only if it is true and you can show it.") : "",
        d.notice ? h("p", { class: "muted small" }, d.notice) : "",
        h("div", { class: "answer-tip" }, h("strong", null, "Make it yours"),
          h("p", { class: "muted" }, "Read it out loud once. Add what you learned, or one detail only you would know. Keep it true.")),
        h("div", { class: "row" }, copy),
        h("details", { class: "small" }, h("summary", null, "How each sentence was checked"),
          h("ol", { class: "draft-sentences" }, d.sentences.map(s => h("li", { class: s.status },
            s.status === "unsupported" ? h("strong", null, "UNSUPPORTED: ") : "", s.text,
            s.reasons.length ? h("ul", null, s.reasons.map(r => h("li", null, r))) : "",
            s.fact_ids.length ? h("div", { class: "muted" }, "From your CV: " +
              s.fact_ids.map(id => factText[id] ? `${id} “${factText[id]}”` : id).join(" · ")) : "")))));
    }
  },
});
