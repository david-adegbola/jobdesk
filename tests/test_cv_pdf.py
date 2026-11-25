import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv_pdf
import db
import test_server     # the module, not the class: a test class imported here would run its tests twice

HAS_TEX = bool(shutil.which("pdflatex"))
HAS_PDFTOTEXT = bool(shutil.which("pdftotext"))
ATTACKS = [r"\input{/etc/passwd}", r"\immediate\write18{touch /tmp/jobdesk-pwned}", r"\catcode`\@=11",
           r"\def\x{\x}\x", r"\csname input\endcsname{/etc/hostname}", "^^5cinput{/etc/passwd}", r"\openin1=/etc/passwd",
           "$$ & # % ~ _ { } [ ] | < > \" \\"]


def cv(content, language="en", cv_id=1):
    return {"id": cv_id, "title": "Test", "language": language, "content": {"full_name": "Aino Mäkelä", **content}}


def pdf_text(pdf):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "cv.pdf"
        path.write_bytes(pdf)
        return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True).stdout


class EscapingTests(unittest.TestCase):
    def test_no_input_can_become_a_command(self):
        for attack in ATTACKS:
            out = cv_pdf.tex(attack)
            # every backslash in the output starts one of our own text commands
            self.assertEqual(set(re.findall(r"\\([A-Za-z]+)", out)) - {"textbackslash", "textasciicircum",
                             "textasciitilde", "textquotedbl", "textbar", "textless", "textgreater"}, set(), attack)
            for brace in re.findall(r"(?<!\\)[{}]", out.replace("{}", "").replace("{[}", "").replace("{]}", "")):
                self.fail(f"unescaped brace in {out!r}")

    def test_characters_the_font_cannot_print_become_question_marks(self):
        self.assertEqual(cv_pdf.tex("Zoë Ångström €5 🚀 中文"), "Zoë Ångström €5 ? ??")
        self.assertEqual(cv_pdf.tex("a\u0000b‮c"), "a?b?c")

    def test_links_only_for_plain_web_addresses_and_email(self):
        tex = cv_pdf.render_tex(cv({"links": "Site: javascript:alert(1)\nGitHub: https://github.com/example",
                                    "email": "not an email"}))
        self.assertIn(r"\href{https://github.com/example}{GitHub}", tex)
        self.assertNotIn("javascript:alert", tex.replace(r"javascript:alert(1)", ""))   # shown only as text
        self.assertNotIn("mailto:", tex)


class LayoutTests(unittest.TestCase):
    def test_empty_sections_get_no_heading_and_headings_follow_the_language(self):
        tex = cv_pdf.render_tex(cv({"summary": "Hei.", "skills": "  ", "projects": ""}, "fi"))
        self.assertIn(r"\cvsection{Profiili}", tex)
        self.assertNotIn("Taidot", tex)
        self.assertNotIn("Projektit", tex)
        self.assertIn(r"\usepackage[fi]{jobdesk-cv}", tex)
        english = cv_pdf.render_tex(cv({"experience": "2024 — Myyjä — Kauppa Oy\nKassatyö."}))
        self.assertIn(r"\cvsection{Work experience}", english)

    def test_entry_headings_dates_and_languages(self):
        cases = {
            "May 2025 — present — Analyst — Esimerkki Oy": ("May 2025 – present", "Analyst", "Esimerkki Oy"),
            "May 2025--Aug 2025 — Analyst — Esimerkki Oy": ("May 2025--Aug 2025", "Analyst", "Esimerkki Oy"),
            "2024: Volunteer — Food Bank": ("2024", "Volunteer", "Food Bank"),
            "Kesä 2025 — Myyjä — Kauppa Oy": ("Kesä 2025", "Myyjä", "Kauppa Oy"),
            "Analyst | Esimerkki": ("", "Analyst", "Esimerkki"),
            "Freelance work": ("", "Freelance work", ""),
        }
        for heading, expected in cases.items():
            self.assertEqual(cv_pdf._entry_heading(heading), expected, heading)
        tex = cv_pdf.render_tex(cv({"languages": "Suomi (äidinkieli); English: C1\nSvenska"}))
        self.assertIn(r"\cvrow{Suomi}{äidinkieli}", tex)
        self.assertIn(r"\cvrow{English}{C1}", tex)
        self.assertIn(r"\cvrow{}{Svenska}", tex)

    def test_size_limits_and_required_name(self):
        with self.assertRaisesRegex(ValueError, "longer than"):
            cv_pdf.render_tex(cv({"summary": "x" * (cv_pdf.MAX_FIELD + 1)}))
        with self.assertRaisesRegex(ValueError, "lines"):
            cv_pdf.render_tex(cv({"skills": "a\n" * (cv_pdf.MAX_ROWS + 1)}))
        with self.assertRaisesRegex(ValueError, "whole CV|longer than"):
            cv_pdf.render_tex(cv({f: "y" * 9000 for f in ("summary", "education", "skills", "experience",
                                                             "projects", "hobbies", "languages")}))
        with self.assertRaisesRegex(ValueError, "name"):
            cv_pdf.render_tex({"id": 1, "language": "en", "content": {"summary": "x"}})
        with self.assertRaisesRegex(ValueError, "text"):
            cv_pdf.render_tex(cv({"summary": ["not", "text"]}))

    def test_download_names(self):
        self.assertEqual(cv_pdf.download_name(cv({})), "Aino_Makela_CV.pdf")
        self.assertEqual(cv_pdf.download_name(cv({"full_name": "Zoë Ångström-O'Neill"})), "Zoe_Angstrom_O_Neill_CV.pdf")
        self.assertEqual(cv_pdf.download_name(cv({"full_name": "中文"})), "My_CV.pdf")


class CacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for p in (patch.object(db, "DATA_DIR", Path(temp.name)), patch.object(db, "DB_FILE", Path(temp.name) / "jobdesk.db")):
            p.start()
            self.addCleanup(p.stop)
        self.compiles = 0

        def fake_compile(source, pdflatex=None):
            self.compiles += 1
            return b"%PDF-1.5 fake " + str(self.compiles).encode()
        compile_patch = patch.object(cv_pdf, "compile_pdf", side_effect=fake_compile)
        compile_patch.start()
        self.addCleanup(compile_patch.stop)

    def test_built_once_until_the_cv_changes_and_deleted_with_it(self):
        first = cv_pdf.build(cv({"summary": "A"}), user_id=7)
        self.assertEqual(cv_pdf.build(cv({"summary": "A"}), user_id=7), first)
        self.assertEqual(self.compiles, 1)
        cv_pdf.build(cv({"summary": "B"}), user_id=7)
        self.assertEqual(self.compiles, 2)
        self.assertEqual(len(cv_pdf.cached_files(7)), 1)              # the old version is replaced
        path = cv_pdf.cached_files(7)[0]
        self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(path.parent.stat().st_mode & 0o777), "0o700")
        cv_pdf.build(cv({"summary": "C"}, cv_id=2), user_id=7)
        self.assertEqual(cv_pdf.remove_cached(7, 1), 1)
        self.assertEqual([p.name.split("-")[0] for p in cv_pdf.cached_files(7)], ["2"])
        cv_pdf.remove_cached(7)
        self.assertEqual(cv_pdf.cached_files(7), [])


class ServerTests(unittest.TestCase):
    setUp_server = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request

    def setUp(self):
        self.setUp_server()
        for p in (patch.object(cv_pdf, "compile_pdf", return_value=b"%PDF-1.5 test"),):
            p.start()
            self.addCleanup(p.stop)

    def test_preview_download_export_and_deletion(self):
        cv_id = db.save_cv(1, "Main", "fi", {"full_name": "Aino Mäkelä", "summary": "Hei."})
        status, body, headers = self.request("GET", f"/api/cvs/{cv_id}/formatted.pdf", include_headers=True)
        self.assertEqual((status, body), (200, b"%PDF-1.5 test"))
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="Aino_Makela_CV.pdf"')
        self.assertIn("no-store", headers["Cache-Control"])
        status, _, headers = self.request("GET", f"/api/cvs/{cv_id}/formatted.pdf?download=1", include_headers=True)
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="Aino_Makela_CV.pdf"')
        status, export = self.request("GET", "/api/account/export")
        self.assertEqual([(p["cv_id"], p["pdf_base64"][:8]) for p in export["cv_pdfs"]], [(cv_id, "JVBERi0x")])
        self.assertEqual(self.request("POST", f"/api/cvs/{cv_id}/delete", {})[0], 200)
        self.assertEqual(cv_pdf.cached_files(1), [])
        status, error = self.request("GET", f"/api/cvs/{db.save_cv(1, 'No name', 'en', {'summary': 'x'})}/formatted.pdf")
        self.assertEqual((status, "name" in error["error"]), (400, True))


LETTER = {"language": "fi", "name": "Aino Mäkelä", "job_title": "Myyjä", "location": "Jyväskylä", "phone": "040 000 0000",
          "email": "aino@example.test", "date": "25.11.2026", "recipient": "Esimerkki Oy\nRekrytointi",
          "subject": "Hakemus: Myyjä, Esimerkki Oy", "greeting": "Hei Maija,",
          "paragraphs": ["Haen myyjän paikkaa.", r"Kokeilu: \input{/etc/passwd} & 100% $x$"], "closing": "Ystävällisin terveisin"}


class LetterTests(unittest.TestCase):
    def test_letters_are_escaped_and_need_a_name(self):
        tex = cv_pdf.render_letter_tex(LETTER)
        self.assertIn(r"\cvletterhead{Aino Mäkelä}{Myyjä}", tex)
        self.assertIn(r"Esimerkki Oy\\Rekrytointi", tex)
        self.assertNotIn(r"\input{", tex)
        self.assertIn(r"\textbackslash{}input\{/etc/passwd\} \& 100\% \$x\$", tex)
        with self.assertRaisesRegex(ValueError, "name"):
            cv_pdf.render_letter_tex({**LETTER, "name": " "})
        with self.assertRaisesRegex(ValueError, "longer than"):
            cv_pdf.render_letter_tex({**LETTER, "paragraphs": ["x" * (cv_pdf.MAX_TOTAL + 1)]})
        with self.assertRaisesRegex(ValueError, "text"):
            cv_pdf.render_letter_tex({**LETTER, "subject": 5})


@unittest.skipUnless(HAS_TEX, "pdflatex is not installed (run in the TeX container)")
class CompileTests(unittest.TestCase):
    def test_a_letter_compiles_with_real_text(self):
        pdf = cv_pdf.build_letter(LETTER)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        if HAS_PDFTOTEXT:
            text = pdf_text(pdf)
            for words in ("Aino Mäkelä", "Hakemus: Myyjä, Esimerkki Oy", "Ystävällisin terveisin", "/etc/passwd"):
                self.assertIn(words, text)
            self.assertNotIn("root:", text)

    def test_attacks_print_as_text_and_the_pdf_has_real_text(self):
        pdf = cv_pdf.compile_pdf(cv_pdf.render_tex(cv({"skills": "\n".join(f"Try: {a}" for a in ATTACKS),
                                                        "summary": "Effort, office, fluent Finnish. Mäkelä €5."}, "fi")))
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertFalse(Path("/tmp/jobdesk-pwned").exists())
        if HAS_PDFTOTEXT:
            text = pdf_text(pdf)
            self.assertIn("/etc/passwd", text)                 # the attack, printed
            self.assertNotIn("root:", text)                    # not the file's contents
            for word in ("Effort", "office", "fluent", "Mäkelä", "€5", "Profiili"):
                self.assertIn(word, text)

    def test_the_compiler_itself_refuses_files_and_shell_even_without_escaping(self):
        # Defence in depth: LaTeX written by hand (never possible from member input) still can't read
        # /etc/passwd or run a shell command
        raw = (r"\documentclass{article}\begin{document}\immediate\write18{touch /tmp/jobdesk-pwned2}"
               r"\input{/etc/passwd}\end{document}")
        with self.assertRaises(cv_pdf.PdfBuildError):
            cv_pdf.compile_pdf(raw)
        self.assertFalse(Path("/tmp/jobdesk-pwned2").exists())

    def test_a_runaway_document_is_stopped(self):
        with patch.object(cv_pdf, "COMPILE_SECONDS", 3):
            with self.assertRaisesRegex(cv_pdf.PdfBuildError, "too long"):
                cv_pdf.compile_pdf(r"\documentclass{article}\begin{document}\def\x{\x}\x\end{document}")


if __name__ == "__main__":
    unittest.main()
