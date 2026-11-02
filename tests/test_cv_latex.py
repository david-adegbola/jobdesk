import unittest

import cv_latex


class CvLatexTests(unittest.TestCase):
    def test_user_text_is_escaped_before_inserting_into_latex_template(self):
        cv = {
            "title": "Forest analyst",
            "language": "en",
            "content": {
                "full_name": "A&B_#1",
                "target_role": r"Researcher \input{secrets}",
                "summary": r"100% ready & skilled",
                "skills": "GIS\nRemote sensing",
            },
        }
        style = r"\fancyfoot[L]{David Adegbola}"

        tex, customized_style = cv_latex.render_tex(cv, style)

        self.assertIn(r"A\&B\_\#1", tex)
        self.assertIn(r"Researcher \textbackslash{}input\{secrets\}", tex)
        self.assertIn(r"100\% ready \& skilled", tex)
        self.assertIn(r"\section{Summary}", tex)
        self.assertIn(r"\cvline{}{Remote sensing}", tex)
        self.assertIn(r"\fancyfoot[L]{\cvname}", customized_style)
        self.assertEqual(style, r"\fancyfoot[L]{David Adegbola}")

    def test_finnish_cv_uses_shared_finnish_labels(self):
        cv = {
            "title": "Metsäalan CV",
            "language": "fi",
            "content": {"full_name": "Metsä Opiskelija", "skills": "Paikkatieto"},
        }

        tex, _ = cv_latex.render_tex(cv, r"\fancyfoot[L]{David Adegbola}")

        self.assertIn(r"\cvlang{fi}", tex)
        self.assertIn(r"\section{Taidot}", tex)

    def test_pdf_filename_is_safe_and_has_one_extension(self):
        self.assertEqual(cv_latex.safe_filename("Ä CV / #1"), "CV-1.pdf")


if __name__ == "__main__":
    unittest.main()
