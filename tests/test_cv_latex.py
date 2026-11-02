import unittest

import cv_latex


class CvLatexTests(unittest.TestCase):
    def test_example_cv_has_fictional_content_and_template_sections(self):
        cv = cv_latex.example_cv()

        self.assertEqual(cv["language"], "en")
        self.assertEqual(cv["content"]["full_name"], "Alex Example")
        self.assertTrue(cv["content"]["email"].endswith(".test"))
        self.assertGreater(len(cv["content"]["experience"].splitlines()), 5)
        self.assertIn("2024: Forest inventory project", cv["content"]["projects"])
        tex, _ = cv_latex.render_tex(cv, r"\fancyfoot[L]{David Adegbola}")
        self.assertIn(r"\section{\cvt{summary}}", tex)
        self.assertIn(r"\section{\cvt{education}}", tex)
        self.assertIn(r"\section{\cvt{skills}}", tex)
        self.assertIn(r"\section{\cvt{experience}}", tex)
        self.assertIn(r"\section{\cvt{volunteering}}", tex)
        self.assertIn(r"\section{\cvt{references}}", tex)

    def test_user_text_is_escaped_before_inserting_into_latex_template(self):
        cv = {
            "title": "Forest analyst",
            "language": "en",
            "content": {
                "full_name": "A&B_#1",
                "email": "alex+forestry@example.org",
                "target_role": r"Researcher \input{secrets}",
                "summary": "100% ready & skilled\nContinued sentence.\n\nSecond paragraph.",
                "education": "2024--present: MSc, Forestry",
                "experience": (
                    "2025: Forest researcher — University of Eastern Finland\n"
                    "Collected field data.\n"
                    "Tags: forestry,field-work"
                ),
                "projects": "2024: Field project — Example University\nMapped forest plots.",
                "skills": "GIS: QGIS\nRemote sensing",
                "certifications": "Occupational safety card",
                "languages": "Finnish (basic); English (fluent)",
                "hobbies": "Photography\nHiking",
                "links": "GitHub: https://github.com/alex-forest",
            },
        }
        style = r"\fancyfoot[L]{David Adegbola}"

        tex, customized_style = cv_latex.render_tex(cv, style)

        self.assertIn(r"A\&B\_\#1", tex)
        self.assertIn(r"Researcher \textbackslash{}input\{secrets\}", tex)
        self.assertIn(r"100\% ready \& skilled", tex)
        self.assertIn(r"\section{\cvt{summary}}", tex)
        self.assertIn(r"\begin{tabular}{p{0.9\textwidth}}", tex)
        self.assertIn(
            "100\\% ready \\& skilled Continued sentence.\\\\\\\\\n\nSecond paragraph.",
            tex,
        )
        self.assertIn(r"\cvline{2024--present:}{MSc, Forestry}", tex)
        self.assertIn(
            r"\begin{cventry}{2025}{\job{Forest researcher}{University of Eastern Finland}}",
            tex,
        )
        self.assertIn(r"Collected field data.\par \sotagrow{forestry,field-work}", tex)
        self.assertIn(r"\cvline{GIS:}{QGIS}", tex)
        self.assertIn(r"\cvline[0cm]{}{Remote sensing}", tex)
        self.assertIn(r"\href{mailto:alex+forestry@example.org}{alex+forestry@example.org}", tex)
        self.assertIn(r"\cvline{\cvt{cards}:}{Occupational safety card}", tex)
        self.assertIn(
            r"\cvline{\cvt{languages}:}{Finnish (basic); English (fluent)}",
            tex,
        )
        self.assertIn(
            r"\href{https://github.com/alex-forest}{GitHub}",
            tex,
        )
        self.assertIn(r"\section{\cvt{references}}", tex)
        self.assertIn(r"\cvt{refsavailable}", tex)
        self.assertIn(r"\section{\cvt{hobbies}}", tex)
        self.assertIn("Photography\\par Hiking", tex)
        self.assertLess(tex.index(r"\section{\cvt{summary}}"),
                        tex.index(r"\section{\cvt{education}}"))
        self.assertLess(tex.index(r"\section{\cvt{education}}"),
                        tex.index(r"\section{\cvt{skills}}"))
        self.assertLess(tex.index(r"\section{\cvt{skills}}"),
                        tex.index(r"\section{\cvt{experience}}"))
        self.assertLess(tex.index(r"\section{\cvt{experience}}"),
                        tex.index(r"\section{\cvt{volunteering}}"))
        self.assertLess(tex.index(r"\section{\cvt{volunteering}}"),
                        tex.index(r"\section{\cvt{hobbies}}"))
        self.assertLess(tex.index(r"\section{\cvt{hobbies}}"),
                        tex.index(r"\section{\cvt{references}}"))
        self.assertIn(r"\setlength{\cvlabelw}{3.9cm}", tex)
        self.assertIn(r"\titlespacing{\section}{0pt}{0.55em}{2pt}", tex)
        self.assertIn(r"\newcommand{\woodeskCVFooterName}{A\&B\_\#1}", tex)
        self.assertIn(r"\fancyfoot[L]{\woodeskCVFooterName}", customized_style)
        self.assertEqual(style, r"\fancyfoot[L]{David Adegbola}")

    def test_unsafe_email_is_rendered_as_text_without_a_mailto_link(self):
        cv = {
            "title": "Forest analyst",
            "language": "en",
            "content": {
                "full_name": "Alex Forest",
                "email": r"alex}\input{bad}@example.org",
            },
        }

        tex, _ = cv_latex.render_tex(cv, r"\fancyfoot[L]{David Adegbola}")

        self.assertNotIn(r"\href{mailto:", tex)
        self.assertIn(r"alex\}\textbackslash{}input\{bad\}@example.org", tex)

    def test_flattened_experience_entries_keep_their_own_dates_and_details(self):
        cv = {
            "title": "Forest analyst",
            "language": "en",
            "content": {
                "full_name": "Alex Forest",
                "experience": (
                    "Aug 2025--Oct 2025 — Forest Assistant — Example Forestry Oy\n"
                    "Collected field data.\n"
                    "Jun 2024--Aug 2024 — Research Intern — University of Eastern Finland\n"
                    "Supported forest measurements."
                ),
            },
        }

        tex, _ = cv_latex.render_tex(cv, r"\fancyfoot[L]{David Adegbola}")

        self.assertIn(
            r"\begin{cventry}{Aug 2025--Oct 2025}"
            r"{\job{Forest Assistant}{Example Forestry Oy}}"
            "\nCollected field data.\\end{cventry}",
            tex,
        )
        self.assertIn(
            r"\begin{cventry}{Jun 2024--Aug 2024}"
            r"{\job{Research Intern}{University of Eastern Finland}}"
            "\nSupported forest measurements.\\end{cventry}",
            tex,
        )

    def test_one_line_experience_description_colon_does_not_consume_the_date(self):
        cv = {
            "title": "Forest analyst",
            "language": "en",
            "content": {
                "full_name": "Alex Forest",
                "experience": (
                    "Nov 2024--Aug 2026 — Audio-Visual Volunteer, Vaasa City Church, "
                    "Vaasa: sound and video every weekend."
                ),
            },
        }

        tex, _ = cv_latex.render_tex(cv, r"\fancyfoot[L]{David Adegbola}")

        self.assertIn(
            r"\begin{cventry}{Nov 2024--Aug 2026}"
            r"{\textbf{Audio-Visual Volunteer}, Vaasa City Church, Vaasa: "
            r"sound and video every weekend.}"
            r"\end{cventry}",
            tex,
        )

    def test_finnish_cv_uses_shared_finnish_labels(self):
        cv = {
            "title": "Metsäalan CV",
            "language": "fi",
            "content": {"full_name": "Metsä Opiskelija", "skills": "Paikkatieto"},
        }

        tex, _ = cv_latex.render_tex(cv, r"\fancyfoot[L]{David Adegbola}")

        self.assertIn(r"\cvlang{fi}", tex)
        self.assertIn(r"\section{\cvt{skills}}", tex)

    def test_pdf_filename_is_safe_and_has_one_extension(self):
        self.assertEqual(cv_latex.safe_filename("Ä CV / #1"), "CV-1.pdf")


if __name__ == "__main__":
    unittest.main()
