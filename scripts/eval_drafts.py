#!/usr/bin/env python3
"""Evaluate grounded drafting: the verifier on planted sentences, and drafted answers for each case.

    python3 scripts/eval_drafts.py                       # mock mode (default): free
    JOBDESK_LLM_MODE=live ANTHROPIC_API_KEY=... python3 scripts/eval_drafts.py   # real drafts, costs money

Options: --cases (default data/eval/drafts.jsonl), --labels (default data/eval/draft_labels.jsonl),
--out (default reports/draft-eval-<date>-<mode>.md). Live mode sends the cases' invented CV facts,
questions and ads to the Claude API; no real person's CV is used.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from core import draft, draft_eval, llm  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", default=str(ROOT / "data" / "eval" / "drafts.jsonl"))
    parser.add_argument("--labels", default=str(ROOT / "data" / "eval" / "draft_labels.jsonl"))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    settings = llm.settings_from_env()
    cases, problems = draft_eval.load_cases(args.cases)
    label_rows, label_problems = draft_eval.load_jsonl(args.labels, ("case", "text", "supported"))
    for problem in problems + label_problems:
        print("Skipped:", problem, file=sys.stderr)
    if not cases:
        print("No usable cases in", args.cases, file=sys.stderr)
        return 1
    labels = {(r["case"], r["text"]): r["supported"] for r in label_rows if isinstance(r["supported"], bool)}

    planted = draft_eval.check_planted(cases)
    drafts = {}
    for number, case in enumerate(cases, start=1):
        print(f"[{number}/{len(cases)}] {case['id']}", file=sys.stderr)
        try:
            drafts[case["id"]] = draft.draft_answer(case["ad_text"], case["question"], case["cv"],
                                                    case["word_limit"], case["language"], settings)
        except (llm.LLMError, ValueError) as error:
            # Stop and write nothing: a partial report would look like a complete one
            print(f"Stopped: {case['id']}: {error} No report was written.", file=sys.stderr)
            return 1
    drafted = draft_eval.summarise_drafts(drafts, labels)
    today = date.today().isoformat()
    text = draft_eval.report_markdown(planted, drafted, {
        "date": today, "mode": settings.mode, "model": settings.model if settings.live else ""})
    out = Path(args.out) if args.out else ROOT / "reports" / f"draft-eval-{today}-{settings.mode}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Report: {out}")
    print(f"Planted: caught {planted['caught']} of {planted['unsupported']} unsupported, "
          f"{planted['false_alarms']} false alarms of {planted['supported']} supported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
