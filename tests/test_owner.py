import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import match
import owner
import prompt

PROFILE = {
    "name": "Alex Example",
    "cv_repo": "alex-example/cv",
    "public_cv_base": "https://alex-example.github.io/cv/",
    "pdf_prefix": "alex-example-",
    "summary_lead": "lead with the summer job",
    "tags_job": "the summer job",
}

ANALYSIS = {
    "job": {"title": "Forest trainee", "company": "", "location": "", "url": "", "deadline": "",
            "contact_name": "", "contact_phone": ""},
    "closest": "forestry-master", "closest_score": 50, "closest_language": "fi-first",
    "keywords": ["metsä"], "blockers": [], "tags": [], "questions": [],
}
ANSWERS = {"mode": "new", "language": "en-only", "slug": "forest-trainee", "role_en": "Forest trainee"}


class OwnerProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.file = Path(self.temp_dir.name) / "profile.json"
        patcher = patch.object(config, "OWNER_PROFILE_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_without_a_profile_owner_tools_are_off_and_links_are_empty(self):
        with self.assertRaises(owner.OwnerProfileMissing):
            owner.load()
        self.assertEqual(match.employer_link("forest-trainee"), "")
        self.assertEqual(match.pdf_links({"slug": "x", "langs": ["en"], "language": "en-only"}), {})
        with self.assertRaises(owner.OwnerProfileMissing):
            prompt.build(ANALYSIS, ANSWERS)

    def test_incomplete_profile_names_the_missing_fields(self):
        self.file.write_text(json.dumps({"name": "Alex"}), encoding="utf-8")
        with self.assertRaisesRegex(owner.OwnerProfileMissing, "cv_repo, public_cv_base"):
            owner.load()

    def test_prompt_uses_the_profile_and_contains_no_hard_coded_owner(self):
        self.file.write_text(json.dumps(PROFILE), encoding="utf-8")
        text, missing = prompt.build(ANALYSIS, ANSWERS)
        self.assertEqual(missing, [])
        self.assertIn("In my repo alex-example/cv,", text)
        self.assertIn("https://alex-example.github.io/cv/r/forest-trainee/", text)
        self.assertIn("Summary angle: lead with the summer job;", text)
        self.assertIn("Tags under the summer job:", text)
        for personal in ("david", "adegbola", "axioma"):
            self.assertNotIn(personal, text.lower())
        self.assertEqual(match.pdf_links({"slug": "x", "langs": ["en"], "language": "en-only"}),
                         {"combined": "https://alex-example.github.io/cv/alex-example-x.pdf",
                          "en": "https://alex-example.github.io/cv/alex-example-x-en.pdf"})


class NoPersonalDataInTrackedTemplatesTests(unittest.TestCase):
    def test_repo_prep_templates_are_generic(self):
        prep_dir = Path(config.APP) / "prep"
        for path in prep_dir.glob("*.yaml"):
            text = path.read_text(encoding="utf-8").lower()
            for personal in ("david", "adegbola", "axioma", "vamk", "kaukas"):
                self.assertNotIn(personal, text, path.name)


if __name__ == "__main__":
    unittest.main()
