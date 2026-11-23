import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import evaluate, finnish

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "eval" / "ads.jsonl"

ROWS = [
    {"id": "1", "ad_text_excerpt": "a", "label": "required"},
    {"id": "2", "ad_text_excerpt": "b", "label": "preferred"},
    {"id": "3", "ad_text_excerpt": "c", "label": "not_needed"},
    {"id": "4", "ad_text_excerpt": "d", "label": "unclear"},
]


class MetricsTests(unittest.TestCase):
    def test_scores_confusion_precision_recall(self):
        result = evaluate.scores(["required", "required", "not_required"],
                                 ["required", "not_required", "not_required"], evaluate.COLLAPSED)
        self.assertEqual((result["correct"], result["total"]), (2, 3))
        self.assertEqual(result["matrix"]["required"], {"required": 1, "not_required": 1})
        self.assertEqual(result["per_class"]["required"]["precision"], 1.0)
        self.assertEqual(result["per_class"]["required"]["recall"], 0.5)
        self.assertEqual(result["per_class"]["not_required"]["precision"], 0.5)

    def test_collapsed_table_excludes_unclear_labels_and_counts_llm_unclear_as_wrong(self):
        baseline = {"1": "required", "2": "required", "3": "not_required", "4": "not_required"}
        llm = {"1": "required", "2": "preferred", "3": "unclear", "4": "unclear"}
        summary = evaluate.evaluate(ROWS, baseline, llm)
        self.assertEqual(summary["excluded_unclear"], 1)
        self.assertEqual(summary["baseline_collapsed"]["correct"], 2)          # misses "preferred"
        self.assertEqual(summary["llm_collapsed"]["correct"], 2)               # "unclear" on row 3 is wrong
        self.assertIn("unclear", summary["llm_collapsed"]["columns"])
        self.assertEqual(summary["llm_four_levels"]["correct"], 3)

    def test_report_lists_every_disagreement_and_flags_mock_mode(self):
        baseline = {"1": "required", "2": "required", "3": "not_required", "4": "not_required"}
        llm_results = {i: {"level": lvl, "evidence": [], "rejected_evidence": []}
                       for i, lvl in {"1": "required", "2": "preferred", "3": "unclear", "4": "unclear"}.items()}
        summary = evaluate.evaluate(ROWS, baseline, {i: r["level"] for i, r in llm_results.items()})
        text = evaluate.report_markdown(summary, ROWS, baseline, llm_results,
                                        {"date": "2026-11-24", "mode": "mock", "model": "", "prompt_version": "v1"})
        self.assertIn("Mock mode", text)
        self.assertIn("### 2", text)       # baseline wrong
        self.assertIn("### 3", text)       # LLM wrong
        self.assertNotIn("### 1", text)    # both right
        self.assertNotIn("### 4", text)


class DatasetTests(unittest.TestCase):
    def test_every_row_is_valid_and_its_evidence_is_a_real_quote(self):
        rows, problems = evaluate.load_dataset(DATASET)
        self.assertEqual(problems, [])
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        for row in rows:
            if row.get("evidence"):
                quotes = row["evidence"].split(" / ")
                found, missing = finnish.verify_evidence(row["ad_text_excerpt"], quotes)
                self.assertEqual(missing, [], row["id"])
            else:
                self.assertEqual(row["label"], "unclear", f"{row['id']}: only 'unclear' may have no evidence")

    def test_the_known_baseline_failure_is_in_the_examples(self):
        rows = {r["id"]: r for r in evaluate.load_dataset(DATASET)[0]}
        self.assertEqual(finnish.baseline_v1(rows["example-preferred-fi"]["ad_text_excerpt"]), "required")


class ScriptTests(unittest.TestCase):
    def test_script_writes_a_report_in_mock_mode(self):
        import scripts.eval_finnish as script
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report.md"
            with patch.dict("os.environ", {"JOBDESK_LLM_MODE": "mock"}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(script.main(["--data", str(DATASET), "--out", str(out)]), 0)
            text = out.read_text(encoding="utf-8")
        self.assertIn("# Finnish requirement classifier: evaluation", text)
        self.assertIn("baseline_v1", text)

    def test_bad_lines_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ads.jsonl"
            path.write_text("not json\n" + json.dumps({"id": "x", "ad_text_excerpt": "y", "label": "maybe"}) + "\n",
                            encoding="utf-8")
            rows, problems = evaluate.load_dataset(path)
        self.assertEqual(rows, [])
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
