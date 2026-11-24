import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import fit, llm  # noqa: E402

AD = """Data analyst trainee
We are looking for a trainee to join our analytics team. You have studies in data science or computer science.
Experience with Python and SQL is required. Knowledge of Power BI is an advantage. Driving licence (B) required.
English is the working language."""
CV = {"full_name": "Alex Example", "email": "alex@example.test",
      "experience": "2025: Research assistant — University; analysed survey data with Python and pandas",
      "skills": "Python, SQL, Excel", "education": "BSc Computer Science, Metropolia (ongoing)",
      "languages": "English (fluent); Finnish (basic)"}
LIVE = llm.Settings(mode="live", api_key="test-key")


def reply(data):
    return lambda system, user, schema, settings, max_tokens=0: {"data": data, "model": "test-model"}


class RulesTests(unittest.TestCase):
    def test_rules_mode_finds_strengths_gaps_and_the_hard_requirement(self):
        result = fit.evaluate(AD, CV, llm.Settings(), call=lambda *a, **k: self.fail("mock mode must not call the API"))
        self.assertEqual(result["method"], "rules")
        self.assertIn(llm.MOCK_LABEL, result["notice"])
        self.assertIn(result["suitability"], fit.SUITABILITY)
        cited = {i for s in result["strengths"] for i in s["fact_ids"]}
        self.assertIn("skill-1", cited)
        self.assertTrue(all(s["ad_quote"] in " ".join(AD.split()) for s in result["strengths"]))
        gaps = [g["requirement"] for g in result["gaps"]]
        self.assertEqual(gaps[0], "B licence")
        self.assertIn("Knowledge of Power BI is an advantage.", gaps)
        self.assertEqual(len([g for g in result["gaps"] if g["ad_quote"] == "Driving licence (B) required."]), 1)
        self.assertNotEqual(result["suitability"], "strong")        # a missing hard requirement caps the rating
        self.assertTrue(result["recommendations"])

    def test_rules_never_rate_a_job_strong(self):
        ad = "Python developer trainee. Python and SQL are required. English is the working language."
        result = fit.evaluate(ad, {"skills": "Python, SQL", "languages": "English (fluent)"}, llm.Settings())
        self.assertEqual(result["suitability"], "possible")
        self.assertIn("python, sql", result["recommendations"][0])
        self.assertNotIn("in the ad and in your CV", result["recommendations"][0])

    def test_live_settings_without_permission_use_the_rules(self):
        result = fit.evaluate(AD, CV, LIVE, call=lambda *a, **k: self.fail("no opt-in: no API call"), use_ai=False)
        self.assertEqual(result["method"], "rules")
        self.assertNotIn(llm.MOCK_LABEL, result["notice"])

    def test_unusable_input(self):
        with self.assertRaises(ValueError):
            fit.evaluate("Too short", CV, llm.Settings())
        with self.assertRaises(ValueError):
            fit.evaluate(AD, {}, llm.Settings())
        weak = fit.evaluate("Forest machine operator. Experience with harvesters is required. " * 2,
                            {"skills": "Watercolour painting"}, llm.Settings())
        self.assertEqual((weak["suitability"], weak["strengths"]), ("weak", []))


class CheckTests(unittest.TestCase):
    def test_the_model_never_sees_contact_details_and_its_answer_is_checked(self):
        sent = {}

        def call(system, user, schema, settings, max_tokens=0):
            sent["user"] = user
            return {"data": {
                "suitability": "strong", "summary": "Good match.",
                "strengths": [
                    {"point": "Python and SQL from your skills.", "fact_ids": ["skill-1"],
                     "ad_quote": "Experience with  Python and SQL is required."},
                    {"point": "Invented fact.", "fact_ids": ["exp-9"], "ad_quote": ""},
                    {"point": "You have a driving licence.", "fact_ids": ["skill-1"], "ad_quote": ""},
                    {"point": "Research work.", "fact_ids": ["exp-1"], "ad_quote": "We love researchers."}],
                "gaps": [{"requirement": "Power BI", "ad_quote": "Knowledge of Power BI is an advantage.",
                          "advice": "Mention any dashboard work."}],
                "recommendations": ["Lead with the research assistant job."]}, "model": "test-model"}

        result = fit.evaluate(AD, CV, LIVE, call=call)
        for private in ("Alex Example", "alex@example.test"):
            self.assertNotIn(private, sent["user"])
        self.assertIn("B licence", sent["user"])
        self.assertEqual((result["method"], result["model"]), ("llm", "test-model"))
        self.assertEqual([s["point"] for s in result["strengths"]], ["Python and SQL from your skills.", "Research work."])
        self.assertEqual(result["strengths"][0]["ad_quote"], "Experience with Python and SQL is required.")
        self.assertEqual(result["strengths"][1]["ad_quote"], "")                # not in the ad: cleared
        self.assertEqual(result["checks"], {"dropped_strengths": 2, "cleared_quotes": 1})
        self.assertEqual(result["suitability"], "possible")                     # strong, capped by the missing licence
        self.assertEqual([g["requirement"] for g in result["gaps"]], ["B licence", "Power BI"])
        self.assertEqual(result["strengths"][0]["facts"], ["Python, SQL, Excel"])

    def test_a_malformed_answer_is_made_safe(self):
        result = fit.evaluate(AD, CV, LIVE, call=reply({"suitability": "excellent", "strengths": "lots",
                                                         "gaps": [None, {"requirement": ""}], "recommendations": [3]}))
        self.assertEqual(result["suitability"], "stretch")
        self.assertEqual(result["strengths"], [])
        self.assertTrue(result["recommendations"])


class CacheKeyTests(unittest.TestCase):
    def test_the_key_changes_only_when_the_ad_cv_or_method_does(self):
        key = fit.cache_key(AD, CV, "rules")
        self.assertEqual(key, fit.cache_key(AD, dict(reversed(list(CV.items()))), "rules"))
        self.assertNotEqual(key, fit.cache_key(AD + " More.", CV, "rules"))
        self.assertNotEqual(key, fit.cache_key(AD, {**CV, "skills": "Python"}, "rules"))
        self.assertNotEqual(key, fit.cache_key(AD, CV, "llm"))


if __name__ == "__main__":
    unittest.main()
