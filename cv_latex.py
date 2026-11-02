"""Build private CV PDFs using the shared CV repository LaTeX template."""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import config


class PdfBuildError(Exception):
    """A CV could not be compiled with the installed LaTeX toolchain."""


SECTION_LABELS = {
    "summary": ("Summary", "Yhteenveto"),
    "education": ("Education", "Koulutus"),
    "experience": ("Work Experience", "Työkokemus"),
    "skills": ("Skills", "Taidot"),
    "projects": ("Projects and Research", "Projektit ja tutkimus"),
    "certifications": ("Certificates", "Todistukset"),
    "languages": ("Languages", "Kielet"),
    "links": ("Links", "Linkit"),
}
SECTION_ORDER = (
    "summary", "education", "experience", "skills", "projects",
    "certifications", "languages", "links",
)
LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(value):
    return "".join(LATEX_ESCAPES.get(character, character) for character in value)


def _rows(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def render_tex(cv, style_source):
    content = cv.get("content") or {}
    language = cv.get("language")
    if language not in {"en", "fi"}:
        raise ValueError("Choose Finnish or English before building this CV.")

    name = content.get("full_name", "")
    role = content.get("target_role", "") or cv.get("title", "")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Add your name before building this CV.")
    if not isinstance(role, str):
        raise ValueError("The target role must be text.")

    header = [
        r"\begin{cvheader}",
        r"\par{\centering",
        rf"{{\Huge \textsc{{{escape_latex(name.strip())}}}}}\\[0.4em]",
        rf"{{\Large {escape_latex(role.strip())}}}",
        r"\bigskip\par}",
        r"\hrule",
        r"\vspace{0.5em}",
    ]
    for field, label in (
        ("location", "location"),
        ("phone", "phone"),
        ("email", "email"),
    ):
        value = content.get(field, "")
        if isinstance(value, str):
            for line in _rows(value):
                header.append(rf"\cvline[2.4cm]{{\cvt{{{label}}}:}}{{{escape_latex(line)}}}")
    header.append(r"\end{cvheader}")

    sections = []
    for field in SECTION_ORDER:
        value = content.get(field, "")
        if not isinstance(value, str):
            continue
        rows = _rows(value)
        if not rows:
            continue
        title = SECTION_LABELS[field][language == "fi"]
        sections.extend((rf"\section{{{escape_latex(title)}}}",))
        sections.extend(rf"\cvline{{}}{{{escape_latex(row)}}}" for row in rows)

    source = "\n".join((
        r"\documentclass[a4paper,11pt]{article}",
        r"\usepackage{cv-style}",
        r"\cvlang{fi}" if language == "fi" else "",
        rf"\cvrole{{{escape_latex(role.strip())}}}",
        rf"\newcommand{{\cvname}}{{{escape_latex(name.strip())}}}",
        r"\begin{document}",
        r"\small",
        r"\setlength{\cvlabelw}{3.9cm}",
        r"\titlespacing{\section}{0pt}{0.55em}{2pt}",
        *header,
        *sections,
        r"\end{document}",
        "",
    ))
    # The shared template's multi-page footer names its owner. Substitute a macro only in this
    # temporary copy so each member's PDF carries their own name and the repository stays untouched.
    if "David Adegbola" not in style_source:
        raise PdfBuildError("The shared CV template is missing its expected footer name.")
    style = style_source.replace("David Adegbola", r"\cvname")
    return source, style


def build_pdf(cv, repo=None, pdflatex=None):
    root = Path(repo or config.CV_REPO).resolve()
    style_path = root / "shared" / "cv-style.sty"
    try:
        style_source = style_path.read_text(encoding="utf-8")
    except OSError as error:
        raise FileNotFoundError("The shared CV LaTeX template is unavailable.") from error

    executable = pdflatex or shutil.which("pdflatex")
    if not executable:
        raise FileNotFoundError("pdflatex is not installed.")
    tex, style = render_tex(cv, style_source)

    with tempfile.TemporaryDirectory(prefix="woodesk-cv-") as directory:
        workdir = Path(directory)
        tex_path = workdir / "woodesk-cv.tex"
        tex_path.write_text(tex, encoding="utf-8")
        (workdir / "cv-style.sty").write_text(style, encoding="utf-8")
        environment = os.environ.copy()
        environment["HOME"] = str(workdir)
        for _ in range(2):
            try:
                result = subprocess.run(
                    [
                        executable, "-no-shell-escape", "-interaction=nonstopmode",
                        "-halt-on-error", tex_path.name,
                    ],
                    cwd=workdir,
                    env=environment,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise PdfBuildError("CV compilation timed out. Shorten the CV and try again.") from error
            except FileNotFoundError as error:
                raise FileNotFoundError("pdflatex is not installed.") from error
            except OSError as error:
                raise PdfBuildError("The LaTeX compiler could not be started.") from error
            if result.returncode:
                raise PdfBuildError(
                    "CV compilation failed. The server may be missing a required LaTeX package."
                )
        pdf_path = workdir / "woodesk-cv.pdf"
        try:
            pdf = pdf_path.read_bytes()
        except OSError as error:
            raise PdfBuildError("LaTeX completed without producing a PDF.") from error
        if not pdf.startswith(b"%PDF-"):
            raise PdfBuildError("LaTeX produced an invalid PDF.")
        return pdf


def safe_filename(value):
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return (name[:80] or "cv") + ".pdf"
