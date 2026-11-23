"""Evaluating grounded drafting: how often drafts contain unsupported sentences, and how many of
those the verifier (core/verify.py) catches.

Two measurements, written to one Markdown report by scripts/eval_drafts.py:

1. Planted sentences (no LLM needed). data/eval/drafts.jsonl has invented CVs and questions, each
   with sentences whose truth is known ("supported" or "unsupported", with the reason). The verifier
   checks them, and we count:
     caught       unsupported sentences it flagged      (catch rate = caught / unsupported)
     missed       unsupported sentences it let through
     false alarms supported sentences it flagged
2. Real drafts. core.draft writes an answer for each case (mock or live). A machine can't know
   which drafted sentences are really true, so a person labels them once in
   data/eval/draft_labels.jsonl: {"case": id, "text": sentence, "supported": true|false}.
   With labels we report: unsupported sentences the model produced, how many the verifier caught,
   how many it missed, and false alarms. Unlabelled sentences are listed with a ready-made line to
   paste into the labels file.
"""

import json

from core import cv_facts, draft, verify


def load_jsonl(path, required=()):
    rows, problems = [], []
    try:
        handle = open(path, encoding="utf-8")
    except OSError:
        return [], []
    with handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                problems.append(f"line {number}: not valid JSON")
                continue
            missing = [key for key in required if key not in row]
            if missing:
                problems.append(f"line {number}: missing {', '.join(missing)}")
                continue
            rows.append(row)
    return rows, problems


def load_cases(path):
    return load_jsonl(path, ("id", "cv", "question", "ad_text", "word_limit", "language", "planted"))


def check_planted(cases):
    """Run the verifier on every planted sentence and compare with its known truth."""
    rows = []
    for case in cases:
        extracted = cv_facts.facts_from_cv(case["cv"])
        missing = draft.ad_blockers(case["ad_text"], extracted["facts"])
        checked = verify.verify(case["planted"], extracted["facts"], extracted["learning"], missing)
        for planted, result in zip(case["planted"], checked):
            rows.append({"case": case["id"], "text": planted["text"], "truth": planted["truth"],
                         "why": planted.get("why", ""), "flagged": result["status"] == "unsupported",
                         "reasons": result["reasons"]})
    unsupported = [r for r in rows if r["truth"] == "unsupported"]
    supported = [r for r in rows if r["truth"] == "supported"]
    return {"rows": rows, "unsupported": len(unsupported), "caught": sum(r["flagged"] for r in unsupported),
            "supported": len(supported), "false_alarms": sum(r["flagged"] for r in supported)}


def summarise_drafts(drafts, labels):
    """drafts: {case id: draft_answer result}; labels: {(case id, sentence text): bool supported}."""
    sentences, unlabelled = [], []
    for case_id, result in drafts.items():
        for sentence in result["sentences"]:
            label = labels.get((case_id, sentence["text"]))
            row = {"case": case_id, "text": sentence["text"], "flagged": sentence["status"] == "unsupported",
                   "reasons": sentence["reasons"], "supported": label}
            sentences.append(row)
            if label is None:
                unlabelled.append(row)
    labelled = [s for s in sentences if s["supported"] is not None]
    produced = [s for s in labelled if s["supported"] is False]
    return {"sentences": sentences, "total": len(sentences), "flagged": sum(s["flagged"] for s in sentences),
            "labelled": len(labelled), "produced_unsupported": len(produced),
            "caught": sum(s["flagged"] for s in produced),
            "false_alarms": sum(s["flagged"] for s in labelled if s["supported"] is True),
            "unlabelled": unlabelled}


def _pct(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "–"


def report_markdown(planted, drafted, run_info):
    lines = [
        "# Grounded drafting: evaluation", "",
        f"- Date: {run_info['date']}",
        f"- Drafting mode: {run_info['mode']}" + (f" (model {run_info['model']})" if run_info.get("model") else ""),
        f"- Prompt version: {draft.PROMPT_VERSION}", "",
        "## 1. Verifier on planted sentences", "",
        f"- Unsupported sentences: {planted['unsupported']}; caught **{planted['caught']}** "
        f"({_pct(planted['caught'], planted['unsupported'])}), missed {planted['unsupported'] - planted['caught']}.",
        f"- Supported sentences: {planted['supported']}; false alarms **{planted['false_alarms']}** "
        f"({_pct(planted['false_alarms'], planted['supported'])}).", "",
        "| case | sentence | truth | verifier | reasons / why |", "|---|---|---|---|---|",
    ]
    for r in planted["rows"]:
        outcome = ("caught" if r["flagged"] else "MISSED") if r["truth"] == "unsupported" else \
                  ("FALSE ALARM" if r["flagged"] else "ok")
        detail = "; ".join(r["reasons"]) or r["why"]
        lines.append(f"| {r['case']} | {r['text']} | {r['truth']} | {outcome} | {detail} |")
    lines += ["", "## 2. Drafted answers", ""]
    if run_info["mode"] == "mock":
        lines += ["> **Mock mode.** The drafts are copied CV facts, not model output, so this section only "
                  "shows the format. Run with JOBDESK_LLM_MODE=live for real results.", ""]
    lines += [
        f"- Sentences drafted: {drafted['total']}; flagged by the verifier: {drafted['flagged']}.",
        f"- Labelled by hand: {drafted['labelled']} of {drafted['total']}.",
    ]
    if drafted["labelled"]:
        lines += [
            f"- Unsupported sentences the model produced: **{drafted['produced_unsupported']}**; "
            f"caught by the verifier: **{drafted['caught']}**, missed: {drafted['produced_unsupported'] - drafted['caught']}.",
            f"- False alarms (true sentences flagged): {drafted['false_alarms']}.",
        ]
    lines += ["", "| case | sentence | verifier | your label |", "|---|---|---|---|"]
    for s in drafted["sentences"]:
        label = {True: "supported", False: "unsupported", None: "not labelled"}[s["supported"]]
        lines.append(f"| {s['case']} | {s['text']} | {'UNSUPPORTED' if s['flagged'] else 'ok'} | {label} |")
    if drafted["unlabelled"]:
        lines += ["", "### To label", "",
                  "Add one line per sentence to data/eval/draft_labels.jsonl, with true or false:", "", "```"]
        lines += [json.dumps({"case": s["case"], "text": s["text"], "supported": None}, ensure_ascii=False)
                  for s in drafted["unlabelled"]]
        lines += ["```"]
    return "\n".join(lines) + "\n"
