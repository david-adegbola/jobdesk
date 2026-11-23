import ast
import unittest
from pathlib import Path

import core.language
import core.text
import language
import match
import scraper

CORE = Path(core.text.__file__).resolve().parent
# Everything in core/ must work in another app: standard library and core.* only
FORBIDDEN = {"server", "db", "config", "owner", "facts", "match", "scraper", "skills", "prompt", "prep",
             "news", "auth", "cv_latex", "cv_import", "ics", "language"}


class CorePackageTests(unittest.TestCase):
    def test_core_imports_nothing_from_jobdesk(self):
        for path in CORE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for name in names:
                    self.assertNotIn(name.split(".")[0], FORBIDDEN, f"{path.name} imports {name}")

    def test_old_import_paths_still_work(self):
        self.assertIs(match.tokens, core.text.tokens)
        self.assertIs(match.word_matches, core.text.word_matches)
        self.assertIs(match.STOPWORDS, core.text.STOPWORDS)
        self.assertIs(language.detect, core.language.detect)
        self.assertTrue(scraper.is_public_http_url("https://8.8.8.8/"))

    def test_scraper_sends_an_honest_user_agent(self):
        self.assertTrue(scraper.USER_AGENT.startswith("JobDesk/"))
        self.assertNotIn("Mozilla", scraper.USER_AGENT)


if __name__ == "__main__":
    unittest.main()
