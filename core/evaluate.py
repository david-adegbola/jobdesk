"""Scoring the Finnish classifiers against hand labels, and writing the Markdown report.

Dataset: data/eval/ads.jsonl, one JSON object per line:
    {"id", "source_url", "language", "ad_text_excerpt", "label", "evidence"}
label is one of required / preferred / not_needed / unclear (see data/eval/GUIDE.md).

Two comparisons are reported:
  * Four levels: the LLM classifier against the labels. baseline_v1 can't take part, because it
    only says required / not_required.
  * Collapsed: preferred and not_needed become "not_required", so both classifiers can be compared
    on the question baseline_v1 answers. Ads hand-labelled "unclear" are left out of this table and
    counted, because "unclear" has no fair required / not_required equivalent. When the LLM says
    "unclear" on a kept ad, that is shown as its own column and counts as wrong.

Definitions:
  accuracy  = correct / all rows scored
  precision = of the ads the classifier put in a class, the share that really are in it
  recall    = of the ads really in a class, the share the classifier found
"""

import json

from core.finnish import LEVELS

COLLAPSED = ("required", "not_required")


def load_dataset(path):
    rows, problems = [], []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                problems.append(f"line {number}: not valid JSON")
                continue
            missing = [k for k in ("id", "ad_text_excerpt", "label") if not row.get(k)]
            if missing or row.get("label") not in LEVELS:
                problems.append(f"line {number}: missing {', '.join(missing) or 'a valid label'}")
                continue
            rows.append(row)
    return rows, problems


def collapse(label):
    if label == "required":
        return "required"
    if label in ("preferred", "not_needed", "not_required"):
        return "not_required"
    return "unclear"


def scores(gold, predicted, labels):
    """Accuracy, confusion matrix (gold -> predicted -> count) and per-class precision/recall."""
    pred_labels = list(labels) + sorted(set(predicted) - set(labels))
    matrix = {g: {p: 0 for p in pred_labels} for g in labels}
    for g, p in zip(gold, predicted):
        matrix[g][p] += 1
    total = len(gold)
    correct = sum(1 for g, p in zip(gold, predicted) if g == p)
    per_class = {}
    for label in labels:
        tp = matrix[label][label]
        predicted_as = sum(matrix[g][label] for g in labels)
        actual = sum(matrix[label].values())
        per_class[label] = {
            "precision": tp / predicted_as if predicted_as else None,
            "recall": tp / actual if actual else None,
            "support": actual,
        }
    return {"total": total, "correct": correct, "accuracy": correct / total if total else None,
            "matrix": matrix, "columns": pred_labels, "per_class": per_class}


def evaluate(rows, baseline_preds, llm_preds):
    """rows: dataset rows; *_preds: {id: predicted label}."""
    gold = [r["label"] for r in rows]
    four = scores(gold, [llm_preds[r["id"]] for r in rows], LEVELS)
    kept = [r for r in rows if r["label"] != "unclear"]
    gold_c = [collapse(r["label"]) for r in kept]
    baseline_c = scores(gold_c, [baseline_preds[r["id"]] for r in kept], COLLAPSED)
    llm_c = scores(gold_c, [collapse(llm_preds[r["id"]]) for r in kept], COLLAPSED)
    return {"rows": len(rows), "excluded_unclear": len(rows) - len(kept),
            "llm_four_levels": four, "baseline_collapsed": baseline_c, "llm_collapsed": llm_c}


def _pct(value):
    return "–" if value is None else f"{100 * value:.0f}%"


def _table(result, title):
    lines = [f"#### {title}", "",
             f"Accuracy: **{_pct(result['accuracy'])}** ({result['correct']} of {result['total']})", "",
             "Confusion matrix (rows = hand label, columns = prediction):", "",
             "| label \\ predicted | " + " | ".join(result["columns"]) + " |",
             "|---|" + "---|" * len(result["columns"])]
    for gold, row in result["matrix"].items():
        lines.append(f"| {gold} | " + " | ".join(str(row[c]) for c in result["columns"]) + " |")
    lines += ["", "| class | precision | recall | ads |", "|---|---|---|---|"]
    for label, s in result["per_class"].items():
        lines.append(f"| {label} | {_pct(s['precision'])} | {_pct(s['recall'])} | {s['support']} |")
    return lines + [""]


def report_markdown(summary, rows, baseline_preds, llm_results, run_info):
    """The full report. llm_results: {id: classify() result}; run_info: mode, model, date, prompt version."""
    lines = [
        "# Finnish requirement classifier: evaluation",
        "",
        f"- Date: {run_info['date']}",
        f"- LLM mode: {run_info['mode']}" + (f" (model {run_info['model']})" if run_info.get("model") else ""),
        f"- Prompt version: {run_info['prompt_version']}",
        f"- Ads: {summary['rows']}",
        "",
    ]
    if run_info["mode"] == "mock":
        lines += ["> **Mock mode.** The LLM column is fake output, so its numbers mean nothing. "
                  "Run with JOBDESK_LLM_MODE=live for real results.", ""]
    lines += ["## Four levels (LLM only)", ""] + _table(summary["llm_four_levels"], "LLM classifier")
    lines += ["## Collapsed: required vs not_required", "",
              f"Preferred and not_needed count as not_required. {summary['excluded_unclear']} ads hand-labelled "
              "\"unclear\" are left out of this comparison.", ""]
    lines += _table(summary["baseline_collapsed"], "baseline_v1 (old regex)")
    lines += _table(summary["llm_collapsed"], "LLM classifier")
    lines += ["## Disagreements", "",
              "Every ad where either classifier differs from the hand label.", ""]
    count = 0
    for r in rows:
        llm = llm_results[r["id"]]
        base_wrong = r["label"] != "unclear" and baseline_preds[r["id"]] != collapse(r["label"])
        llm_wrong = llm["level"] != r["label"]
        if not (base_wrong or llm_wrong):
            continue
        count += 1
        excerpt = " ".join(r["ad_text_excerpt"].split())
        lines += [
            f"### {r['id']}",
            "",
            f"- Hand label: **{r['label']}**" + (f" – evidence: \"{r['evidence']}\"" if r.get("evidence") else ""),
            f"- baseline_v1: {baseline_preds[r['id']]}" + (" ✗" if base_wrong else ""),
            f"- LLM: {llm['level']}" + (" ✗" if llm_wrong else "")
            + (f" – quoted: \"{' / '.join(llm['evidence'])}\"" if llm.get("evidence") else "")
            + (" – quote not found in the ad" if llm.get("rejected_evidence") else ""),
            f"- Excerpt: {excerpt[:600]}{'…' if len(excerpt) > 600 else ''}",
            "",
        ]
    if not count:
        lines += ["None.", ""]
    return "\n".join(lines)
