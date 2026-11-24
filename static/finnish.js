// Shared by the Jobs and Shortlist pages: how a Finnish level is shown, and the "Was this right?" buttons.
import { api, h } from "./core.js";

// The words carry the meaning; the colour only repeats it.
export const FINNISH = {
  required: ["Finnish required", "tag bad"],
  preferred: ["Finnish an advantage", "tag warn"],
  not_needed: ["Finnish not needed", "tag new"],
  unclear: ["Finnish unclear", "tag"],
};
export const METHOD = { llm: "AI; the quote was checked against the ad", baseline_v1: "keyword rule", mock: "mock output" };

// "Was this right?" Yes / No. On No, the student picks what the ad really says. Only the level shown,
// the vote, the correction and the quoted sentence are stored, for measuring accuracy in the pilot.
export function feedbackControls(fin, jobId) {
  const box = h("div", { class: "small feedback" });
  async function send(vote, correct) {
    try {
      await api("/api/finnish/feedback", { method: "POST", body: {
        level_shown: fin.level, vote, correct_level: correct || "", method: fin.method,
        evidence: (fin.evidence || [])[0] || "", job_id: jobId ?? null } });
      box.replaceChildren("Thanks, noted.");
    } catch (error) { box.replaceChildren(error.message); }
  }
  function askWhatItSays() {
    const choice = h("select", { "aria-label": "What does the ad really say about Finnish?" },
      h("option", { value: "" }, "What does the ad say?"),
      Object.entries(FINNISH).filter(([level]) => level !== fin.level).map(([level, [label]]) => h("option", { value: level }, label)));
    box.replaceChildren(choice, " ", h("button", { type: "button", class: "link small", onclick: () => send("wrong", choice.value) }, "Send"));
    choice.focus();
  }
  if (!METHOD[fin.method]) return box;        // nothing to judge (for example an empty ad)
  box.append("Was this right? ",
    h("button", { type: "button", class: "link small", onclick: () => send("right") }, "Yes"), " ",
    h("button", { type: "button", class: "link small", onclick: askWhatItSays }, "No"));
  return box;
}
