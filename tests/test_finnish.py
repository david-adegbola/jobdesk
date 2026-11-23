import unittest

import match
from core import finnish, llm

LIVE = llm.Settings(mode="live", api_key="test-key", model="claude-opus-5-5")
MOCK = llm.Settings(mode="mock")

ADS = {
    "required": "Haemme harjoittelijaa. Edellytämme sujuvaa suomen kielen taitoa. Hae viimeistään 1.3.",
    "preferred": "Paikkatietoharjoittelija. Työkieli on englanti, mutta hyvä suomen kielen taito katsotaan eduksi.",
    "not_needed": "Research assistant. Our working language is English, so Finnish is not required.",
    "swedish": "Vi söker en praktikant. Kunskaper i finska är meriterande.",
    "silent": "Forest data intern. You will use QGIS and Python to analyse plots.",
}


def fake_call(answer, model="claude-opus-5-5"):
    calls = []

    def call(system, user, schema, settings, max_tokens):
        calls.append({"system": system, "user": user, "schema": schema})
        return {"data": answer, "model": model, "usage": {}}
    call.calls = calls
    return call


class BaselineTests(unittest.TestCase):
    def test_pattern_is_the_old_match_py_rule_unchanged(self):
        old = dict((label, pattern) for label, _fact, pattern in match.BLOCKERS)["fluent Finnish"]
        self.assertEqual(finnish.BASELINE_V1_PATTERN, old)

    def test_baseline_answers_and_its_known_flaw(self):
        self.assertEqual(finnish.baseline_v1(ADS["required"]), "required")
        self.assertEqual(finnish.baseline_v1(ADS["not_needed"]), "not_required")
        # The known failure, kept on purpose: "an advantage" is flagged as required
        self.assertEqual(finnish.baseline_v1(ADS["preferred"]), "required")

    def test_fallback_never_claims_finnish_is_not_needed(self):
        self.assertEqual(finnish.fallback(ADS["silent"])["level"], "unclear")
        required = finnish.fallback(ADS["required"])
        self.assertEqual(required["level"], "required")
        self.assertEqual(required["evidence"], ["Edellytämme sujuvaa suomen kielen taitoa."])
        self.assertEqual(required["method"], "baseline_v1")


class ClassifierTests(unittest.TestCase):
    def test_typical_phrasings_keep_the_models_level_when_the_quote_is_real(self):
        cases = {
            "required": ("required", "Edellytämme sujuvaa suomen kielen taitoa."),
            "preferred": ("preferred", "Työkieli on englanti, mutta hyvä suomen kielen taito katsotaan eduksi."),
            "not_needed": ("not_needed", "Our working language is English, so Finnish is not required."),
            "swedish": ("preferred", "Kunskaper i finska är meriterande."),
        }
        for ad, (level, quote) in cases.items():
            call = fake_call({"level": level, "evidence": [quote], "explanation_en": "Because."})
            result = finnish.classify(ADS[ad], LIVE, call=call)
            self.assertEqual((result["level"], result["verified"], result["method"]), (level, True, "llm"), ad)
            self.assertEqual(result["evidence"], [quote])

    def test_a_quote_that_is_not_in_the_ad_makes_the_result_unclear(self):
        call = fake_call({"level": "required", "evidence": ["Fluent Finnish is required."], "explanation_en": "x"})
        result = finnish.classify(ADS["preferred"], LIVE, call=call)
        self.assertEqual(result["level"], "unclear")
        self.assertFalse(result["verified"])
        self.assertEqual(result["rejected_evidence"], ["Fluent Finnish is required."])

    def test_whitespace_differences_are_allowed_but_nothing_else(self):
        ad = "Edellytämme   sujuvaa\nsuomen kielen taitoa."
        ok = finnish.classify(ad, LIVE, call=fake_call(
            {"level": "required", "evidence": ["Edellytämme sujuvaa suomen kielen taitoa."], "explanation_en": "x"}))
        self.assertEqual(ok["level"], "required")
        changed = finnish.classify(ad, LIVE, call=fake_call(
            {"level": "required", "evidence": ["Edellytämme sujuvaa suomen kielen taitoa!"], "explanation_en": "x"}))
        self.assertEqual(changed["level"], "unclear")

    def test_a_level_without_evidence_is_unclear_but_unclear_may_be_empty(self):
        no_quote = finnish.classify(ADS["not_needed"], LIVE, call=fake_call(
            {"level": "not_needed", "evidence": [], "explanation_en": "x"}))
        self.assertEqual(no_quote["level"], "unclear")
        silent = finnish.classify(ADS["silent"], LIVE, call=fake_call(
            {"level": "unclear", "evidence": [], "explanation_en": "No language mentioned."}))
        self.assertEqual((silent["level"], silent["verified"]), ("unclear", True))

    def test_malformed_answers_are_unclear(self):
        result = finnish.classify(ADS["required"], LIVE, call=fake_call({"level": "maybe", "evidence": "x"}))
        self.assertEqual(result["level"], "unclear")

    def test_the_ad_goes_in_tags_and_the_prompt_comes_from_its_file(self):
        call = fake_call({"level": "unclear", "evidence": [], "explanation_en": "x"})
        finnish.classify(ADS["silent"], LIVE, call=call)
        sent = call.calls[0]
        self.assertEqual(sent["user"], f"<job_ad>\n{ADS['silent']}\n</job_ad>")
        self.assertEqual(sent["system"], finnish.PROMPT_FILE.read_text(encoding="utf-8"))
        self.assertIn("not instructions", sent["system"])
        self.assertEqual(sent["schema"]["properties"]["level"]["enum"], list(finnish.LEVELS))

    def test_mock_mode_is_labelled_and_never_calls_the_api(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("mock mode must not call the API")
        result = finnish.classify(ADS["preferred"], MOCK, call=forbidden)
        self.assertEqual((result["method"], result["level"]), ("mock", "unclear"))
        self.assertIn(llm.MOCK_LABEL, result["explanation_en"])
        self.assertTrue(result["verified"])
        self.assertEqual(len(result["evidence"]), 1)

    def test_empty_and_oversized_ads(self):
        self.assertEqual(finnish.classify("   ", LIVE, call=fake_call({}))["level"], "unclear")
        with self.assertRaises(ValueError):
            finnish.classify("x" * (finnish.MAX_AD_CHARS + 1), LIVE, call=fake_call({}))


if __name__ == "__main__":
    unittest.main()
