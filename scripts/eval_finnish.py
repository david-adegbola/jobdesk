#!/usr/bin/env python3
"""Run baseline_v1 and the LLM classifier on the hand-labelled ads and write a Markdown report.

    python3 scripts/eval_finnish.py                      # mock mode (default): free, fake LLM column
    JOBDESK_LLM_MODE=live ANTHROPIC_API_KEY=... python3 scripts/eval_finnish.py   # real results, costs money

Options: --data PATH (default data/eval/ads.jsonl), --out PATH (default reports/finnish-eval-<date>.md).
Live mode sends each ad excerpt (public job-ad text only, no personal data) to the Claude API.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from core import evaluate, finnish, llm  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", default=str(ROOT / "data" / "eval" / "ads.jsonl"))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    settings = llm.settings_from_env()
    rows, problems = evaluate.load_dataset(args.data)
    for problem in problems:
        print("Skipped:", problem, file=sys.stderr)
    if not rows:
        print("No usable rows in", args.data, file=sys.stderr)
        return 1

    baseline = {r["id"]: finnish.baseline_v1(r["ad_text_excerpt"]) for r in rows}
    results = {}
    for number, r in enumerate(rows, start=1):
        print(f"[{number}/{len(rows)}] {r['id']}", file=sys.stderr)
        try:
            results[r["id"]] = finnish.classify(r["ad_text_excerpt"], settings)
        except llm.LLMError as error:
            # Stop and write nothing: a report full of failed calls (e.g. a wrong key) would look like results
            print(f"Stopped: {r['id']}: {error} No report was written.", file=sys.stderr)
            return 1

    summary = evaluate.evaluate(rows, baseline, {i: res["level"] for i, res in results.items()})
    today = date.today().isoformat()
    text = evaluate.report_markdown(summary, rows, baseline, results, {
        "date": today, "mode": settings.mode, "model": settings.model if settings.live else "",
        "prompt_version": finnish.PROMPT_VERSION,
    })
    out = Path(args.out) if args.out else ROOT / "reports" / f"finnish-eval-{today}-{settings.mode}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
