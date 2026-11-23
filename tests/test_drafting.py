import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import match
from core import blockers, cv_facts, draft, draft_eval, llm, verify

ROOT = Path(__file__).resolve().parent.parent

CV = {
    "full_name": "Alex Example", "email": "alex@example.test", "phone": "+358 00 000 0000",
    "location": "Joensuu", "links": "GitHub: https://github.com/alex", "target_role": "Forest trainee",
    "summary": "Forestry student interested in field research.\n\nI like careful outdoor work.",
    "education": "2024--present: BSc, Forest Sciences, Example University",
    "experience": ("May 2025--Aug 2025 — Field Assistant — Example Forest Research\n"
                   "Measured 40 sample plots with a relascope.\nTags: field-work,inventory\n"
                   "Jun 2024--Aug 2024 — Summer Worker — Example Parks\nPlanted seedlings."),
    "skills": "GIS: QGIS and map reading\nWant to learn: drones, remote sensing",
    "certifications": "Occupational safety card",
    "languages": "English (fluent); Finnish (basic)",
}
AD = "Summer trainee. Field measurements and drone mapping. A B driving licence is required."
LIVE = llm.Settings(mode="live", api_key="test-key")


def fake_call(sentences):
    calls = []

    def call(system, user, schema, settings, max_tokens):
        calls.append({"system": system, "user": user, "schema": schema})
        return {"data": {"sentences": sentences}, "model": "claude-opus-5-5", "usage": {}}
    call.calls = calls
    return call


class BlockerTests(unittest.TestCase):
    def test_patterns_are_the_same_as_match_py(self):
        self.assertEqual([(label, pattern) for label, _fact, pattern in match.BLOCKERS], blockers.BLOCKERS)

    def test_claims_versus_honest_mentions(self):
        self.assertTrue(blockers.claims("forklift card", "I have a forklift card."))
        self.assertFalse(blockers.claims("forklift card", "I don't have a forklift card yet, but I want to get one."))
        self.assertFalse(blockers.claims("forklift card", "Minulla ei ole vielä trukkikorttia."))
        self.assertEqual(blockers.in_ad(AD), ["B licence"])


class CvFactsTests(unittest.TestCase):
    def test_facts_ids_sections_and_what_is_left_out(self):
        result = cv_facts.facts_from_cv(CV)
        ids = [fact["id"] for fact in result["facts"]]
        self.assertEqual(ids, ["sum-1", "sum-2", "edu-1", "exp-1", "exp-2", "skill-1", "cert-1", "lang-1", "lang-2"])
        exp = {f["id"]: f["text"] for f in result["facts"]}
        self.assertEqual(exp["exp-1"], "May 2025--Aug 2025 — Field Assistant — Example Forest Research; "
                                       "Measured 40 sample plots with a relascope.")
        self.assertEqual(result["learning"], ["drones", "remote sensing"])
        everything = cv_facts.as_text(result["facts"])
        for private in ("Alex Example", "alex@example.test", "+358", "github.com", "Joensuu", "Forest trainee"):
            self.assertNotIn(private, everything)
        self.assertNotIn("Tags", everything)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        extracted = cv_facts.facts_from_cv(CV)
        self.facts, self.learning = extracted["facts"], extracted["learning"]

    def check(self, text, ids, blockers_=("B licence",)):
        return verify.verify([{"text": text, "fact_ids": ids}], self.facts, self.learning, blockers_)[0]

    def test_supported_sentence(self):
        result = self.check("I measured 40 sample plots as a field assistant in 2025.", ["exp-1"])
        self.assertEqual((result["status"], result["reasons"]), ("supported", []))

    def test_finnish_case_endings_still_count_as_shared_words(self):
        facts = [{"id": "exp-1", "section": "experience", "text": "Kesä 2025: metsänhoitotyöt, taimikonhoito"}]
        result = verify.verify([{"text": "Tein taimikonhoitoa kesällä 2025.", "fact_ids": ["exp-1"]}], facts)[0]
        self.assertEqual(result["status"], "supported")

    def test_each_rule(self):
        cases = {
            "doesn't cite": self.check("I am a hard-working team player.", []),
            "not in your CV": self.check("I measured sample plots.", ["exp-9"]),
            "key words": self.check("I managed a sawmill budget.", ["exp-1"]),
            "number": self.check("I measured 120 sample plots.", ["exp-1"]),
            "B licence": self.check("I hold a B driving licence.", ["cert-1"]),
            "want-to-learn": self.check("I map forests with drones and QGIS.", ["skill-1"]),
        }
        for expected, result in cases.items():
            self.assertEqual(result["status"], "unsupported", expected)
            self.assertTrue(any(expected in reason for reason in result["reasons"]), (expected, result["reasons"]))

    def test_honest_learning_and_blocker_sentences_are_not_claims(self):
        result = self.check("I read maps with QGIS and I am learning to use drones.", ["skill-1"])
        self.assertEqual(result["status"], "supported")

    def test_word_count(self):
        self.assertEqual(verify.word_count([{"text": "One two three."}, {"text": "Four five"}]), 5)


class DraftTests(unittest.TestCase):
    def test_live_draft_sends_facts_not_identity_and_marks_unsupported_sentences(self):
        call = fake_call([
            {"text": "As a field assistant at Example Forest Research I measured 40 sample plots.", "fact_ids": ["exp-1"]},
            {"text": "I also hold a B driving licence.", "fact_ids": ["cert-1"]},
        ])
        result = draft.draft_answer(AD, "Tell us about your work experience.", CV, 60, "en", LIVE, call=call)
        self.assertEqual([s["status"] for s in result["sentences"]], ["supported", "unsupported"])
        self.assertEqual((result["unsupported"], result["ad_blockers"], result["method"]), (1, ["B licence"], "llm"))
        self.assertEqual(result["word_count"], 20)
        self.assertFalse(result["over_limit"])
        sent = call.calls[0]
        self.assertIn("exp-1: May 2025--Aug 2025", sent["user"])
        self.assertIn("<not_held>\ndrones\nremote sensing\n</not_held>", sent["user"])
        self.assertIn("<ad_asks_for_but_cv_lacks>\nB licence\n</ad_asks_for_but_cv_lacks>", sent["user"])
        for private in ("Alex Example", "alex@example.test", "+358", "github.com"):
            self.assertNotIn(private, sent["user"])
        self.assertEqual(sent["system"], draft.PROMPT_FILE.read_text(encoding="utf-8"))

    def test_over_the_word_limit_is_reported(self):
        call = fake_call([{"text": "I measured 40 sample plots with a relascope at Example Forest Research.",
                           "fact_ids": ["exp-1"]}])
        result = draft.draft_answer(AD, "Experience?", CV, 10, "en", LIVE, call=call)
        self.assertTrue(result["over_limit"])

    def test_malformed_model_answers_give_an_empty_draft(self):
        result = draft.draft_answer(AD, "Experience?", CV, 50, "en", LIVE, call=lambda *a, **k: {"data": [], "model": "m"})
        self.assertEqual(result["sentences"], [])

    def test_mock_mode_is_labelled_grounded_and_never_calls_the_api(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("mock mode must not call the API")
        result = draft.draft_answer(AD, "Tell us about field measurements.", CV, 100, "en",
                                    llm.Settings(mode="mock"), call=forbidden)
        self.assertEqual(result["method"], "mock")
        self.assertIn(llm.MOCK_LABEL, result["notice"])
        self.assertTrue(result["sentences"])
        self.assertTrue(all(s["text"].startswith(llm.MOCK_LABEL) for s in result["sentences"]))
        self.assertTrue(all(s["status"] == "supported" for s in result["sentences"]))

    def test_input_validation(self):
        for args in (("", 100, "en"), ("Q?", 5, "en"), ("Q?", 100, "sv"), ("Q?" * 600, 100, "en")):
            with self.assertRaises(ValueError):
                draft.draft_answer(AD, args[0], CV, args[1], args[2], LIVE, call=fake_call([]))
        with self.assertRaises(ValueError):
            draft.draft_answer(AD, "Q?", {"full_name": "Only a name"}, 100, "en", LIVE, call=fake_call([]))


class DraftEvalTests(unittest.TestCase):
    def test_planted_sentences_measure_the_verifier_honestly(self):
        cases, problems = draft_eval.load_cases(ROOT / "data" / "eval" / "drafts.jsonl")
        self.assertEqual(problems, [])
        planted = draft_eval.check_planted(cases)
        self.assertEqual((planted["unsupported"], planted["caught"]), (9, 8))
        self.assertEqual((planted["supported"], planted["false_alarms"]), (7, 2))
        missed = [r["text"] for r in planted["rows"] if r["truth"] == "unsupported" and not r["flagged"]]
        self.assertEqual(missed, ["I led the field team at Example Forest Research."])

    def test_labels_turn_drafts_into_caught_and_missed_counts(self):
        drafts = {"c": {"sentences": [
            {"text": "A", "status": "unsupported", "reasons": ["x"]},
            {"text": "B", "status": "supported", "reasons": []},
            {"text": "C", "status": "unsupported", "reasons": ["y"]},
            {"text": "D", "status": "supported", "reasons": []}]}}
        summary = draft_eval.summarise_drafts(drafts, {("c", "A"): False, ("c", "B"): False, ("c", "C"): True})
        self.assertEqual((summary["produced_unsupported"], summary["caught"], summary["false_alarms"]), (2, 1, 1))
        self.assertEqual([s["text"] for s in summary["unlabelled"]], ["D"])

    def test_script_writes_a_report_in_mock_mode(self):
        import scripts.eval_drafts as script
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report.md"
            with patch.dict("os.environ", {"JOBDESK_LLM_MODE": "mock"}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(script.main(["--out", str(out), "--labels", str(Path(directory) / "none.jsonl")]), 0)
            text = out.read_text(encoding="utf-8")
        self.assertIn("caught **8**", text)
        self.assertIn("Mock mode", text)
        self.assertIn("### To label", text)


if __name__ == "__main__":
    unittest.main()
