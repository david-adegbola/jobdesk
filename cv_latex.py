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


SECTION_KEYS = {
    "summary": "summary",
    "skills": "skills",
    "experience": "experience",
    "education": "education",
    "projects": "volunteering",
    "hobbies": "hobbies",
}
SECTION_ORDER = ("summary", "education", "skills", "experience", "projects", "hobbies")
EMAIL_LINK_PATTERN = re.compile(
    r"[A-Za-z0-9._+-]+@[A-Za-z0-9]"
    r"(?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
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


def example_cv():
    return {
        "title": "My Forestry CV",
        "language": "en",
        "content": {
            "full_name": "Alex Example",
            "email": "alex@example.test",
            "phone": "+358 00 000 0000",
            "location": "Joensuu, Finland",
            "target_role": "Forestry Research Assistant",
            "summary": (
                "I am a forestry student interested in forest measurement, field research and "
                "practical work outdoors. This sample profile shows how a short introduction "
                "can connect relevant studies with the kind of role being sought.\n\n"
                "I enjoy careful, hands-on work and working as part of a team. I am ready to "
                "learn new tools, follow safety instructions and contribute wherever my "
                "experience is useful."
            ),
            "education": (
                "2024--present: MSc, Forest Sciences, Example University\n"
                "2021--2024: BSc, Natural Resources, Example University\n"
                "2018--2021: Upper secondary education, Example College"
            ),
            "skills": (
                "Field work: Forest measurement, plot surveys and sample collection\n"
                "GIS: QGIS, map reading and basic spatial data handling\n"
                "Data: Careful recording, spreadsheet use and quality checks\n"
                "Safety: Following site instructions and using protective equipment\n"
                "Communication: Clear field notes and teamwork"
            ),
            "certifications": "Example safety training (replace with your own qualifications)",
            "languages": "English (fluent); Finnish (intermediate)",
            "experience": (
                "May 2025--Aug 2025 — Forest Research Assistant — Example Forestry Ltd\n"
                "Measured sample plots and recorded tree species, diameter and condition.\n"
                "Checked field equipment before and after each survey day.\n"
                "Entered observations and reviewed records for missing information.\n"
                "Worked with a small field team and followed site safety procedures.\n"
                "Tags: forest-measurement,field-research,gis\n\n"
                "Jun 2024--Aug 2024 — Summer Worker — Example Forest Services\n"
                "Helped prepare field sites and organize maps, equipment and supplies.\n"
                "Recorded work progress and reported issues to the supervisor.\n"
                "Completed outdoor tasks in changing weather conditions.\n\n"
                "May 2023--Aug 2023 — Forestry Intern — Example Woodland Cooperative\n"
                "Assisted with stand assessments across privately managed forest properties.\n"
                "Identified common tree species and noted signs of damage or disease.\n"
                "Helped mark treatment areas and prepared clear notes for the forester.\n"
                "Compared field observations with management plans and map records.\n"
                "Communicated respectfully with landowners during scheduled site visits.\n\n"
                "Jun 2022--Aug 2022 — Field Survey Volunteer — Example Nature Group\n"
                "Joined supervised surveys to record habitat features and forest structure.\n"
                "Used a shared checklist to keep observations consistent between sites.\n"
                "Photographed selected features and linked images to field note references.\n"
                "Checked collected forms for missing values before leaving each location.\n"
                "Summarized survey days and equipment needs for the volunteer coordinator."
            ),
            "projects": (
                "2024: Forest inventory project — Example University\n"
                "Collected sample data, checked measurements and summarized results for a course report.\n"
                "Compared plot-level results and described likely sources of measurement variation.\n"
                "Presented the findings with a map and concise recommendations for follow-up.\n\n"
                "2023: Habitat mapping project — Example University\n"
                "Prepared a simple GIS map from field observations and public spatial data.\n"
                "Reviewed coordinate accuracy and used a consistent legend for habitat classes.\n"
                "Documented the workflow so classmates could reproduce the final map.\n\n"
                "2022: Forest growth data exercise — Example University\n"
                "Organized repeated tree measurements into a consistent spreadsheet.\n"
                "Calculated simple changes in diameter and checked values against field notes.\n"
                "Created clear charts and explained limitations in the small sample.\n\n"
                "2021: Forest ecology field report — Example College\n"
                "Recorded plant communities and site conditions during supervised field visits.\n"
                "Compared observations across locations and connected findings to course material.\n"
                "Prepared a short report with a site sketch, species list and practical conclusions."
            ),
            "hobbies": "Hiking, nature photography and volunteering.",
            "links": "Portfolio: https://example.com",
        },
    }


def escape_latex(value):
    return "".join(LATEX_ESCAPES.get(character, character) for character in value)


def _rows(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def _paragraphs(value):
    paragraphs = []
    for block in re.split(r"\n\s*\n", value.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines:
            paragraphs.append(" ".join(lines))
    return paragraphs


def _render_cvline(line):
    label, separator, value = line.partition(":")
    if separator and label.strip():
        return rf"\cvline{{{escape_latex(label.strip())}:}}{{{escape_latex(value.strip())}}}"
    return rf"\cvline[0cm]{{}}{{{escape_latex(line)}}}"


def _experience_blocks(value):
    blocks = []
    current = []
    blank_line = False

    def finish():
        if current:
            blocks.append(current.copy())
            current.clear()

    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            blank_line = True
            continue
        is_dated_heading = any(
            separator in line
            and bool(re.search(r"\d", line.partition(separator)[0]))
            for separator in (": ", " — ", " – ")
        )
        if current and (blank_line or is_dated_heading):
            finish()
        current.append(line)
        blank_line = False
    finish()
    return blocks


def _render_experience(value):
    entries = []
    for lines in _experience_blocks(value):
        heading = lines[0]
        date_separator = re.search(r": | — | – ", heading)
        if date_separator and re.search(r"\d", heading[:date_separator.start()]):
            date = heading[:date_separator.start()]
            title = heading[date_separator.end():]
        else:
            date, title = "", heading

        title_part, job_separator, employer = title.partition(" — ")
        if not job_separator:
            title_part, job_separator, employer = title.partition(" | ")
        if job_separator and title_part.strip() and employer.strip():
            formatted_title = (
                rf"\job{{{escape_latex(title_part.strip())}}}"
                rf"{{{escape_latex(employer.strip())}}}"
            )
        else:
            formatted_title = rf"\textbf{{{escape_latex(title.strip())}}}"

        details = []
        tags = []
        for line in lines[1:]:
            label, tag_separator, tag_value = line.partition(":")
            if tag_separator and label.strip().casefold() == "tags":
                tags.extend(tag.strip() for tag in tag_value.split(",") if tag.strip())
            else:
                details.append(escape_latex(line))
        if tags:
            details.append(r"\sotagrow{" + ",".join(escape_latex(tag) for tag in tags) + "}")
        if not details:
            one_line_title, detail_separator, one_line_detail = title.partition(": ")
            label, employer_separator, employer = one_line_title.partition(", ")
            if detail_separator and employer_separator and label.strip() and employer.strip():
                formatted_title = (
                    rf"\textbf{{{escape_latex(label.strip())}}}, "
                    rf"{escape_latex(employer.strip())}: "
                    rf"{escape_latex(one_line_detail.strip())}"
                )

        entry = (
            rf"\begin{{cventry}}{{{escape_latex(date.strip())}}}{{{formatted_title}}}"
        )
        if details:
            entry += "\n" + r"\par ".join(details)
        entry += r"\end{cventry}"
        entries.append(entry)
    return entries


def _render_link(value):
    label, separator, url = value.partition(": ")
    if not separator:
        url = value.strip()
        label = url
    else:
        label = label.strip()
        url = url.strip()
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%+-]+", url):
        return escape_latex(value)
    safe_url = re.sub(r"([%#])", lambda match: "%" + format(ord(match.group(1)), "02X"), url)
    return rf"\href{{{safe_url}}}{{{escape_latex(label)}}}"


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
    for field, label in (("location", "location"), ("phone", "phone"), ("email", "email")):
        value = content.get(field, "")
        if isinstance(value, str) and value.strip():
            rendered_value = escape_latex(value.strip())
            if field == "email" and EMAIL_LINK_PATTERN.fullmatch(value.strip()):
                address = value.strip()
                rendered_value = rf"\href{{mailto:{address}}}{{{rendered_value}}}"
            header.append(
                rf"\cvline[2.4cm]{{\cvt{{{label}}}:}}{{{rendered_value}}}"
            )
    links = content.get("links", "")
    if isinstance(links, str):
        for link in _rows(links):
            header.append(
                rf"\cvline[2.4cm]{{\cvt{{links}}:}}{{{_render_link(link)}}}"
            )
    header.append(r"\end{cvheader}")

    sections = []
    for field in SECTION_ORDER:
        value = content.get(field, "")
        if not isinstance(value, str):
            continue
        if field == "skills":
            skill_rows = _rows(value)
            extra_rows = []
            for extra_field, label in (
                ("certifications", "cards"),
                ("languages", "languages"),
            ):
                extra_value = content.get(extra_field, "")
                if isinstance(extra_value, str):
                    rows = _rows(extra_value)
                    if rows:
                        extra_rows.append((label, "; ".join(rows)))
            if not skill_rows and not extra_rows:
                continue
            sections.append(r"\section{\cvt{skills}}")
            sections.extend(_render_cvline(row) for row in skill_rows)
            sections.extend(
                rf"\cvline{{\cvt{{{label}}}:}}{{{escape_latex(row)}}}"
                for label, row in extra_rows
            )
            continue
        if not value.strip():
            continue
        section_key = SECTION_KEYS[field]
        sections.append(rf"\section{{\cvt{{{section_key}}}}}")
        if field == "summary":
            paragraphs = _paragraphs(value)
            sections.extend((
                r"\begin{tabular}{p{0.9\textwidth}}",
                (r"\\\\" + "\n\n").join(
                    escape_latex(paragraph) for paragraph in paragraphs
                ),
                r"\end{tabular}",
            ))
        elif field == "experience":
            sections.extend(_render_experience(value))
        elif field == "projects":
            sections.extend(_render_experience(value))
        elif field == "hobbies":
            sections.append(r"\par ".join(escape_latex(row) for row in _rows(value)))
        else:
            sections.extend(_render_cvline(row) for row in _rows(value))

    sections.extend((
        r"\section{\cvt{references}}",
        r"\cvt{refsavailable}",
    ))

    source = "\n".join((
        r"\documentclass[a4paper,11pt]{article}",
        r"\usepackage{cv-style}",
        r"\cvlang{fi}" if language == "fi" else "",
        r"\cvrole{" + escape_latex(role.strip()) + "}",
        rf"\newcommand{{\jobdeskCVFooterName}}{{{escape_latex(name.strip())}}}",
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
    # Fail closed: without the configured name, or when the template doesn't contain it, no PDF is
    # built, so the template owner's name can never end up on someone else's CV.
    template_owner = config.CV_TEMPLATE_OWNER
    if not template_owner:
        raise PdfBuildError(
            "Member CV PDFs are switched off on this server: JOBDESK_CV_TEMPLATE_OWNER is not set.")
    if template_owner not in style_source:
        raise PdfBuildError("The shared CV template is missing its expected footer name.")
    style = style_source.replace(template_owner, r"\jobdeskCVFooterName")
    return source, style


def _style_source(repo=None):
    root = Path(repo or config.CV_REPO).resolve()
    try:
        return (root / "shared" / "cv-style.sty").read_text(encoding="utf-8")
    except OSError as error:
        raise FileNotFoundError("The shared CV LaTeX template is unavailable.") from error


def _compile(tex, style, pdflatex=None, what="CV"):
    """Run pdflatex twice (page counts come from the previous run) in a temporary folder; the PDF bytes."""
    executable = pdflatex or shutil.which("pdflatex")
    if not executable:
        raise FileNotFoundError("pdflatex is not installed.")
    with tempfile.TemporaryDirectory(prefix="jobdesk-cv-") as directory:
        workdir = Path(directory)
        tex_path = workdir / "jobdesk-cv.tex"
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
                raise PdfBuildError(f"{what} compilation timed out. Shorten it and try again.") from error
            except FileNotFoundError as error:
                raise FileNotFoundError("pdflatex is not installed.") from error
            except OSError as error:
                raise PdfBuildError("The LaTeX compiler could not be started.") from error
            if result.returncode:
                raise PdfBuildError(
                    f"{what} compilation failed. The server may be missing a required LaTeX package."
                )
        pdf_path = workdir / "jobdesk-cv.pdf"
        try:
            pdf = pdf_path.read_bytes()
        except OSError as error:
            raise PdfBuildError("LaTeX completed without producing a PDF.") from error
        if not pdf.startswith(b"%PDF-"):
            raise PdfBuildError("LaTeX produced an invalid PDF.")
        return pdf


def build_pdf(cv, repo=None, pdflatex=None):
    style_source = _style_source(repo)
    if not (pdflatex or shutil.which("pdflatex")):
        raise FileNotFoundError("pdflatex is not installed.")
    tex, style = render_tex(cv, style_source)
    return _compile(tex, style, pdflatex)


# Cover letters. The layout follows the CV repository's shared/cover-letter.sty (CV-RULES.md section 9): name and
# job title left, location, phone and email right, a rule; date; recipient; bold subject; greeting; paragraphs;
# closing, space to sign, name and contacts. That file has its owner's name and contacts written in, so it can't be
# loaded for anyone else: the same layout is defined here with the member's own details. Same font and colours as
# the CVs, because cv-style.sty is loaded first.
LETTER_MACROS = r"""
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.8em}
\AtBeginDocument{\frenchspacing}
\newcommand{\letterhead}[3]{%
  \noindent
  \begin{minipage}[c]{0.55\textwidth}
    {\Huge\bfseries #1}\\[0.4em]
    {\Large #2}
  \end{minipage}\hfill
  \begin{minipage}[c]{0.4\textwidth}\raggedleft
    #3
  \end{minipage}
  \par\vspace{1em}\hrule\vspace{1.5em}}
"""


LINE_BREAK = "\\\\"        # LaTeX's \\ (new line)


def _lines(value):
    return LINE_BREAK.join(escape_latex(line) for line in _rows(value))


def render_letter_tex(letter, style_source):
    language = letter.get("language")
    if language not in {"en", "fi"}:
        raise ValueError("Choose Finnish or English for this letter.")
    name = (letter.get("name") or "").strip()
    if not name:
        raise ValueError("Add your name before building this letter.")
    email = (letter.get("email") or "").strip()
    rendered_email = escape_latex(email)
    if EMAIL_LINK_PATTERN.fullmatch(email):
        rendered_email = rf"\href{{mailto:{email}}}{{{rendered_email}}}"
    contacts = LINE_BREAK.join(x for x in (escape_latex(letter.get("location") or ""), escape_latex(letter.get("phone") or ""),
                                      rendered_email) if x)
    signature = LINE_BREAK.join(x for x in (escape_latex(name), escape_latex(letter.get("phone") or ""), rendered_email) if x)
    paragraphs = [escape_latex(p.strip()) for p in letter.get("paragraphs") or [] if isinstance(p, str) and p.strip()]
    source = "\n".join((
        r"\documentclass[a4paper,11pt]{article}",
        r"\usepackage{cv-style}",
        r"\cvlang{fi}" if language == "fi" else "",
        rf"\newcommand{{\jobdeskCVFooterName}}{{{escape_latex(name)}}}",
        LETTER_MACROS,
        r"\begin{document}",
        rf"\letterhead{{{escape_latex(name)}}}{{{escape_latex(letter.get('job_title') or '')}}}{{{contacts}}}",
        escape_latex(letter.get("date") or "") + r"\par",
        (_lines(letter.get("recipient") or "") + r"\par") if _rows(letter.get("recipient") or "") else "",
        rf"\textbf{{{escape_latex(letter.get('subject') or '')}}}\par",
        escape_latex(letter.get("greeting") or ""),
        "",
        "\n\n".join(paragraphs),
        "",
        escape_latex(letter.get("closing") or "") + r"\\[2.2em]",
        signature + r"\par",
        r"\end{document}",
        "",
    ))
    template_owner = config.CV_TEMPLATE_OWNER
    if not template_owner:
        raise PdfBuildError(
            "Member PDFs are switched off on this server: JOBDESK_CV_TEMPLATE_OWNER is not set.")
    if template_owner not in style_source:
        raise PdfBuildError("The shared CV template is missing its expected footer name.")
    return source, style_source.replace(template_owner, r"\jobdeskCVFooterName")


def build_letter_pdf(letter, repo=None, pdflatex=None):
    style_source = _style_source(repo)
    if not (pdflatex or shutil.which("pdflatex")):
        raise FileNotFoundError("pdflatex is not installed.")
    tex, style = render_letter_tex(letter, style_source)
    return _compile(tex, style, pdflatex, what="Letter")


def download_name(*parts, extension="pdf"):
    """File names HR systems handle well (CV-RULES.md section 9): full name, document type, job title;
    ASCII, words joined by hyphens, no spaces. e.g. Alex-Example-Cover-Letter-Data-Analyst-Trainee.pdf"""
    import unicodedata
    text = unicodedata.normalize("NFKD", " ".join(p for p in parts if p)).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", text)
    return ("-".join(words)[:120] or "document") + "." + extension


def build_original_pdf(source, pdflatex=None):
    source_path = Path(source).resolve()
    if source_path.suffix.lower() != ".tex" or not source_path.is_file():
        raise FileNotFoundError("The original CV source is unavailable.")

    executable = pdflatex or shutil.which("pdflatex")
    if not executable:
        raise FileNotFoundError("pdflatex is not installed.")

    with tempfile.TemporaryDirectory(prefix="jobdesk-original-cv-") as directory:
        output_dir = Path(directory)
        environment = os.environ.copy()
        environment["HOME"] = str(output_dir)
        for _ in range(2):
            try:
                result = subprocess.run(
                    [
                        executable, "-no-shell-escape", "-interaction=nonstopmode",
                        "-halt-on-error", f"-output-directory={output_dir}", source_path.name,
                    ],
                    cwd=source_path.parent,
                    env=environment,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise PdfBuildError("CV compilation timed out. Try again.") from error
            except FileNotFoundError as error:
                raise FileNotFoundError("pdflatex is not installed.") from error
            except OSError as error:
                raise PdfBuildError("The LaTeX compiler could not be started.") from error
            if result.returncode:
                raise PdfBuildError(
                    "The original CV could not be compiled. The server may be missing a required LaTeX package."
                )

        pdf_path = output_dir / source_path.with_suffix(".pdf").name
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
