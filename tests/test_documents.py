import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv_latex  # noqa: E402
from core import documents, llm  # noqa: E402

JOB = {"title": "Data analyst trainee", "company": "Example Oy", "location": "Tampere, Finland",
       "ad_text": "We are looking for a trainee. Experience with Python and SQL is required. "
                  "Driving licence (B) required. Start in January."}
CV = {"full_name": "Alex Example", "email": "alex@example.test", "phone": "+358 40 000 0000", "location": "Helsinki",
      "links": "https://github.com/alex", "summary": "Old summary.",
      "skills": "Tools: Git\nProgramming: Excel, Python, SQL",
      "experience": "2025: Research assistant, University; analysed survey data with Python",
      "education": "BSc Computer Science (ongoing)"}
PROFILE = {"available_from": "January 2027", "permit": "student permit, 30 h a week"}
LIVE = llm.Settings(mode="live", api_key="test-key")
DAY = date(2026, 11, 24)


class MockModeTests(unittest.TestCase):
    def test_mock_documents_follow_the_layout_and_never_call_the_api(self):
        r = documents.prepare(JOB, CV, PROFILE, {"name": "Miisa Virtanen", "title": "HR partner"}, "en", "basic",
                              llm.Settings(), call=lambda *a, **k: self.fail("mock mode must not call the API"), today=DAY)
        letter, email = r["letter"], r["email"]
        self.assertEqual(r["method"], "mock")
        self.assertEqual(letter["date"], "24 November 2026")
        self.assertEqual(letter["subject"], "Application: Data analyst trainee, Example Oy Tampere")
        self.assertEqual(letter["greeting"], "Hi Miisa,")
        self.assertEqual(letter["recipient"], "Miisa Virtanen, HR partner\nExample Oy")
        self.assertTrue(letter["paragraphs"][0].startswith("I'm applying for the Data analyst trainee position at Example Oy."))
        self.assertEqual(letter["paragraphs"][-1], "My Finnish is still basic, and I'm actively studying it. "
                                                   "My CV is attached, and I'm happy to tell you more by phone or in an interview.")
        self.assertIn("Available from: January 2027", " ".join(letter["paragraphs"]))
        self.assertEqual(letter["closing"], "Kind regards")
        self.assertEqual(email["subject"], letter["subject"])
        self.assertTrue(email["body"].startswith("Hi Miisa,\n\nI just applied for the Data analyst trainee position at Example Oy."))
        self.assertTrue(email["body"].endswith("Kind regards\nAlex Example\n+358 40 000 0000\nalex@example.test"))
        self.assertEqual(r["checks"]["ad_blockers"], ["B licence"])
        self.assertEqual(r["checks"]["unsupported"], 0)
        # The tailored CV: skills the ad mentions first, nothing added or removed; title is the job
        self.assertEqual(r["cv_content"]["skills"], "Programming: Python, SQL, Excel\nTools: Git")
        self.assertEqual(r["cv_content"]["target_role"], "Data analyst trainee")
        self.assertEqual(r["cv_content"]["links"], CV["links"])

    def test_finnish_documents_and_no_named_contact(self):
        r = documents.prepare({**JOB, "company": ""}, CV, {}, {}, "fi", "fluent", llm.Settings(), today=DAY)
        self.assertEqual(r["letter"]["date"], "24.11.2026")
        self.assertEqual(r["letter"]["greeting"], "Hei,")
        self.assertEqual(r["letter"]["closing"], "Ystävällisin terveisin")
        self.assertTrue(r["letter"]["paragraphs"][0].startswith("Haen tehtävää Data analyst trainee."))
        self.assertEqual(r["letter"]["paragraphs"][-1], "CV:ni on liitteenä, ja kerron mielelläni lisää puhelimessa tai haastattelussa.")
        self.assertIn("Hain juuri tehtävää Data analyst trainee. CV ja hakemus", r["email"]["body"])

    def test_unusable_input(self):
        for job, cv, language in ((JOB, CV, "sv"), ({"title": "x", "ad_text": ""}, CV, "en"),
                                  (JOB, {**CV, "full_name": ""}, "en"), (JOB, {"full_name": "A B"}, "en")):
            with self.assertRaises(ValueError):
                documents.prepare(job, cv, {}, {}, language, "none", llm.Settings())


class AiModeTests(unittest.TestCase):
    def test_contact_details_stay_out_and_every_sentence_is_checked(self):
        sent = {}

        def call(system, user, schema, settings, max_tokens=0):
            sent["user"] = user
            S = lambda text, *ids: {"text": text, "fact_ids": list(ids)}
            return {"data": {
                "cv_summary": [[S("I analysed survey data with Python as a research assistant.", "exp-1")],
                               [S("I have a driving licence.", "skill-1")]],
                "letter": {"why": [S("I use Python and SQL, which this job needs.", "skill-2")],
                           "experience": [S("At the university I worked on 40 survey projects.", "exp-1"),
                                          S("I analysed survey data with Python.", "exp-1")],
                           "learning": [],
                           "practical": [S("I can start in January 2027.", "prof-1")]}}, "model": "test-model"}

        r = documents.prepare(JOB, CV, PROFILE, {}, "en", "basic", LIVE, call=call, today=DAY)
        for private in ("Alex Example", "alex@example.test", "+358 40 000 0000", "github.com/alex", "Helsinki"):
            self.assertNotIn(private, sent["user"])
        self.assertIn("prof-1: Available from: January 2027", sent["user"])
        self.assertIn("B licence", sent["user"])
        statuses = {s["text"]: s["status"] for p in r["checks"]["letter_sentences"] for s in p}
        self.assertEqual(statuses["At the university I worked on 40 survey projects."], "unsupported")   # invented number
        self.assertEqual(statuses["I can start in January 2027."], "supported")
        summary = {s["text"]: s["status"] for p in r["checks"]["summary_sentences"] for s in p}
        self.assertEqual(summary["I have a driving licence."], "unsupported")                           # a blocker claimed
        self.assertEqual(r["checks"]["unsupported"], 2)
        self.assertIn("I have a driving licence.", r["cv_content"]["summary"])    # kept, marked, for the person to fix
        self.assertEqual(r["method"], "llm")

    def test_style_warnings(self):
        self.assertEqual(documents.style_warnings(["I am passionate about data — and I leverage Python.",
                                                   "Plain sentence."]), ["passionate", "em dash", "leverage"])


class LetterLatexTests(unittest.TestCase):
    STYLE = "% footer: Template Owner\n"

    def letter(self):
        return documents.prepare(JOB, {**CV, "full_name": "Alex O'Neil & Co"}, PROFILE, {"address": "Katu 1\n00100 Helsinki"},
                                 "en", "basic", llm.Settings(), today=DAY)["letter"]

    def test_the_letter_escapes_text_and_replaces_the_template_owner(self):
        with patch.object(cv_latex.config, "CV_TEMPLATE_OWNER", "Template Owner"):
            tex, style = cv_latex.render_letter_tex({**self.letter(), "paragraphs": ["50% done & $5 #1"]}, self.STYLE)
        self.assertIn(r"\usepackage{cv-style}", tex)
        self.assertIn(r"\letterhead{Alex O'Neil \& Co}{Data analyst trainee}{Helsinki\\+358 40 000 0000\\"
                      r"\href{mailto:alex@example.test}{alex@example.test}}", tex)
        self.assertIn(r"Katu 1\\00100 Helsinki\par", tex)
        self.assertIn(r"\textbf{Application: Data analyst trainee, Example Oy Tampere}\par", tex)
        self.assertIn(r"50\% done \& \$5 \#1", tex)
        self.assertNotIn("Template Owner", style)
        self.assertIn(r"\jobdeskCVFooterName", style)

    def test_no_letter_pdf_without_the_template_owner_setting(self):
        with patch.object(cv_latex.config, "CV_TEMPLATE_OWNER", ""):
            with self.assertRaises(cv_latex.PdfBuildError):
                cv_latex.render_letter_tex(self.letter(), self.STYLE)

    def test_download_names(self):
        self.assertEqual(cv_latex.download_name("Aino Mäkelä", "Cover Letter", "Data analyst / trainee", "FI"),
                         "Aino-Makela-Cover-Letter-Data-analyst-trainee-FI.pdf")


if __name__ == "__main__":
    unittest.main()
