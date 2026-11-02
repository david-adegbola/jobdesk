import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv_import
import db


class CvImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)
        self.data_patch = patch.object(db, "DATA_DIR", data_dir)
        self.db_patch = patch.object(db, "DB_FILE", data_dir / "jobdesk.db")
        self.data_patch.start()
        self.db_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(self.db_patch.stop)
        db.init()

    def test_parse_cv_preserves_profile_sections_and_contact_details(self):
        source = r"""
        \cvrole{Forest analyst}
        \begin{document}
        \begin{cvheader}
        {\Huge \textsc{Alex Forest}}
        \cvline[2.4cm]{\cvt{location}:}{Joensuu, Finland}
        \cvline[2.4cm]{\cvt{email}:}{\href{mailto:alex@example.test}{alex@example.test}}
        \cvline[2.4cm]{Availability:}{Weekends}
        \end{cvheader}
        \section{\cvt{summary}}
        \begin{tabular}{p{0.9\textwidth}}
        Forest data specialist.
        \end{tabular}
        \section{Education}
        \cvline{2024--present:}{MSc, Forestry}
        \section{Work Experience}
        \begin{cventry}{2025}{\job{Forest assistant}{Example Oy}}
        Collected field data.
        \end{cventry}
        \end{document}
        """

        cv = cv_import.parse_cv(source, Path("cv-en.tex"))

        self.assertEqual(cv["title"], "Forest analyst (English)")
        self.assertEqual(cv["content"]["full_name"], "Alex Forest")
        self.assertEqual(cv["content"]["location"], "Joensuu, Finland")
        self.assertEqual(cv["content"]["email"], "alex@example.test")
        self.assertIn("Availability: Weekends", cv["content"]["summary"])
        self.assertIn("Forest data specialist.", cv["content"]["summary"])
        self.assertIn("MSc, Forestry", cv["content"]["education"])
        self.assertIn("Forest assistant — Example Oy", cv["content"]["experience"])
        self.assertIn("Collected field data.", cv["content"]["experience"])

    def test_repository_import_is_idempotent_and_admin_only(self):
        repo = Path(self.temp_dir.name) / "cv-repo"
        role_dir = repo / "roles" / "forest-role"
        role_dir.mkdir(parents=True)
        (role_dir / "cv-en.tex").write_text(
            r"\cvrole{Forest analyst}\begin{document}"
            r"{\Huge \textsc{Alex Forest}}\section{Summary}Forestry work."
            r"\end{document}",
            encoding="utf-8",
        )

        self.assertEqual(cv_import.import_admin_cv_repo(repo), 1)
        self.assertEqual(cv_import.import_admin_cv_repo(repo), 0)
        cvs = db.list_cvs(1)
        self.assertEqual(len(cvs), 1)
        self.assertEqual(cvs[0]["content"]["full_name"], "Alex Forest")

        with db.connect() as conn:
            conn.execute("INSERT INTO users (id, name) VALUES (2, 'Member')")
            conn.execute("UPDATE users SET is_admin=0 WHERE id=1")
        with self.assertRaises(PermissionError):
            db.import_cv_for_admin("roles/other/cv-en.tex", "Other CV", "en", {})


if __name__ == "__main__":
    unittest.main()
