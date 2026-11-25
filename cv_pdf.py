"""Members' CVs as PDFs, in the default JobDesk layout (cv-templates/default/jobdesk-cv.sty).

render_tex(cv)            the LaTeX for a CV: every value the member wrote is escaped, so no input can run LaTeX
build(cv, user_id)        the PDF bytes, from the cache when the CV hasn't changed, otherwise compiled
remove_cached(user_id, cv_id=None)   delete stored PDFs (one CV's, or all of a member's)
download_name(cv)         "Firstname_Lastname_CV.pdf"

Compiling (compile_pdf) is locked down: pdflatex with shell escape off, kpathsea set to read and write only
inside its own temporary folder (openin_any=p, openout_any=p), limits on memory, CPU time, file size and open
files, a wall-clock timeout that kills the whole process group, and one compile at a time (the server is small).
The temporary folder is removed afterwards. Sections the member left empty are left out, headings come in
English or Finnish, and the PDF keeps real, copyable text (Unicode maps for every glyph).
"""

import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import unicodedata
from pathlib import Path

import config
from cv_latex import _experience_blocks, _paragraphs, _rows  # the CV text format JobDesk already uses

TEMPLATE_DIR = Path(__file__).resolve().parent / "cv-templates" / "default"
STYLE_FILE = TEMPLATE_DIR / "jobdesk-cv.sty"
MAX_FIELD = 15_000          # characters in one section
MAX_TOTAL = 60_000          # characters in the whole CV
MAX_ROWS = 300              # lines in one section
COMPILE_SECONDS = 30
MEMORY_BYTES = 768 * 1024 * 1024
CPU_SECONDS = 25
OUTPUT_BYTES = 20 * 1024 * 1024
_compile_lock = threading.Semaphore(1)

HEADINGS = {
    "en": {"summary": "Summary", "education": "Education", "skills": "Skills", "languages": "Languages",
           "experience": "Work experience", "projects": "Projects", "certifications": "Certifications and cards",
           "hobbies": "Interests", "location": "Location", "phone": "Phone", "email": "Email", "links": "Links"},
    "fi": {"summary": "Profiili", "education": "Koulutus", "skills": "Taidot", "languages": "Kielitaito",
           "experience": "Työkokemus", "projects": "Projektit", "certifications": "Pätevyydet ja kortit",
           "hobbies": "Harrastukset", "location": "Paikkakunta", "phone": "Puhelin", "email": "Sähköposti",
           "links": "Linkit"},
}
SECTION_ORDER = ("summary", "education", "skills", "languages", "experience", "projects", "certifications", "hobbies")
TEXT_FIELDS = ("full_name", "target_role", "location", "phone", "email", "links") + SECTION_ORDER


class PdfBuildError(Exception):
    """The CV could not be compiled."""


# ---------------------------------------------------------------- escaping

_SPECIAL = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#", "^": r"\textasciicircum{}",
    "_": r"\_", "%": r"\%", "~": r"\textasciitilde{}", '"': r"\textquotedbl{}", "|": r"\textbar{}",
    "<": r"\textless{}", ">": r"\textgreater{}", "[": "{[}", "]": "{]}",
}


def _printable(character):
    """Characters the CV font can print: Latin (with ä, ö, å and the rest of Latin-1 and Latin Extended-A),
    dashes, quotes, the euro sign and the bullet. Anything else would stop LaTeX, so it becomes "?"."""
    code = ord(character)
    return (0x20 <= code <= 0x7E or 0xA0 <= code <= 0x17F or 0x2010 <= code <= 0x2026 or code in (0x20AC, 0x2022)
            or character in "\n\t")


def tex(value):
    """Plain text from a member, made safe to put into LaTeX: every special character is written out, so
    nothing a member types can be a command (\\input, \\write18, catcode changes ...)."""
    text = unicodedata.normalize("NFC", str(value or ""))
    out = []
    for character in text:
        if character in "\t":
            out.append(" ")
        elif not _printable(character):
            out.append("?")
        else:
            out.append(_SPECIAL.get(character, character))
    return "".join(out)


def _url(value):
    """A web address for \\href, or None when it isn't a plain http(s) address."""
    value = (value or "").strip()
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?@!$&'()*+,;=%-]+", value):
        return None
    return re.sub(r"([%#\\])", lambda m: "%" + format(ord(m.group(1)), "02X"), value)


EMAIL = re.compile(r"[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
DATED = re.compile(r"^(?P<label>[^:]*\d[^:]*):\s+(?P<text>.+)$")          # "2024–2026: BSc ..." (label has a digit)
LABELLED = re.compile(r"^(?P<label>[^:]{1,40}):\s+(?P<text>.+)$")          # "Programming: Python, SQL"


# ---------------------------------------------------------------- sections

def _check_size(content):
    total = 0
    for field in TEXT_FIELDS:
        value = content.get(field, "")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError("Every CV field must be text.")
        if len(value) > MAX_FIELD:
            raise ValueError(f"One section is longer than {MAX_FIELD:,} characters; shorten it.")
        if len(value.splitlines()) > MAX_ROWS:
            raise ValueError(f"One section has more than {MAX_ROWS} lines; shorten it.")
        total += len(value)
    if total > MAX_TOTAL:
        raise ValueError(f"The CV is longer than {MAX_TOTAL:,} characters; shorten it.")


def _rows_block(lines, labelled):
    rows = []
    for line in lines:
        m = (DATED if labelled == "dated" else LABELLED).match(line)
        if m:
            rows.append(rf"\cvrow{{{tex(m['label'].strip())}}}{{{tex(m['text'].strip())}}}")
        else:
            rows.append(rf"\cvrow{{}}{{{tex(line)}}}")
    return [r"\begin{cvrows}", *rows, r"\end{cvrows}"] if rows else []


def _languages(value):
    """'English (fluent); Finnish (B1)' or one per line, 'Finnish: B1' -> rows of language and level."""
    items = [part.strip() for line in _rows(value) for part in line.split(";") if part.strip()]
    rows = []
    for item in items:
        m = re.match(r"^(?P<lang>[^(:]+?)\s*(?:\((?P<a>[^)]*)\)|:\s*(?P<b>.+))$", item)
        if m:
            rows.append(rf"\cvrow{{{tex(m['lang'])}}}{{{tex((m['a'] or m['b'] or '').strip())}}}")
        else:
            rows.append(rf"\cvrow{{}}{{{tex(item)}}}")
    return [r"\begin{cvrows}", *rows, r"\end{cvrows}"] if rows else []


NOW_WORDS = {"present", "now", "today", "nyt", "nykyään", "nykyhetki", "jatkuu", "ongoing"}


def _is_date(part):
    part = part.strip().casefold()
    return bool(re.search(r"\d", part)) or part in NOW_WORDS


def _entry_heading(heading):
    """'May 2025 — present — Analyst — Esimerkki Oy', 'May 2025--Aug 2025 — Analyst — Esimerkki Oy',
    '2024: Volunteer — Food Bank' or 'Analyst | Esimerkki' -> (dates, role, employer)."""
    date = ""
    m = re.match(r"^(?P<date>[^:—–|]*\d[^:—–|]*):\s+(?P<rest>.+)$", heading)
    if m:
        date, heading = m["date"].strip(), m["rest"].strip()
    parts = [p.strip() for p in re.split(r" — | – | \| ", heading) if p.strip()]
    dates = []
    while parts and len(dates) < 2 and len(parts) > 1 and _is_date(parts[0]):
        dates.append(parts.pop(0))
    if dates:
        date = " – ".join(dates)
    role = parts[0] if parts else heading
    employer = " — ".join(parts[1:])
    return date, role, employer


def _entries(value):
    """Experience and projects: 'dates — role — employer' then lines of detail, and 'Tags: a, b'."""
    out = [r"\begin{cvrows}"]
    for lines in _experience_blocks(value):
        date, role, employer = _entry_heading(lines[0])
        title = rf"\cvjob{{{tex(role)}}}{{{tex(employer)}}}"
        details, tags = [], []
        for line in lines[1:]:
            label, colon, rest = line.partition(":")
            if colon and label.strip().casefold() in ("tags", "tagit"):
                tags += [t.strip() for t in rest.split(",") if t.strip()]
            else:
                details.append(tex(line))
        body = title + "".join(r"\par " + d for d in details)
        if tags:
            body += r"\cvtags{" + "".join(rf"\cvtag{{{tex(t)}}}" for t in tags) + "}"
        out.append(rf"\cvrow{{{tex(date)}}}{{{body}}}\cventrygap")
    out.append(r"\end{cvrows}")
    return out if len(out) > 2 else []


def _paragraph_block(value):
    paragraphs = _paragraphs(value)
    return [r"\par\medskip ".join(tex(p) for p in paragraphs) + r"\par"] if paragraphs else []


def render_tex(cv):
    content = cv.get("content") or {}
    language = cv.get("language")
    if language not in HEADINGS:
        raise ValueError("Choose Finnish or English before building this CV.")
    _check_size(content)
    name = (content.get("full_name") or "").strip()
    if not name:
        raise ValueError("Add your name before building this CV.")
    words = HEADINGS[language]
    role = (content.get("target_role") or "").strip()
    lines = [r"\documentclass[11pt,a4paper]{article}",
             rf"\usepackage[{language}]{{jobdesk-cv}}",
             rf"\hypersetup{{pdftitle={{{tex(name)} CV}},pdfauthor={{{tex(name)}}}}}",
             r"\begin{document}", rf"\cvname{{{tex(name)}}}{{{tex(role)}}}"]

    contact = []
    for field in ("location", "phone"):
        value = (content.get(field) or "").strip()
        if value:
            contact.append(rf"\cvrow{{{words[field]}}}{{{tex(value)}}}")
    email = (content.get("email") or "").strip()
    if email:
        shown = tex(email)
        contact.append(rf"\cvrow{{{words['email']}}}{{" + (rf"\href{{mailto:{email}}}{{{shown}}}" if EMAIL.fullmatch(email) else shown) + "}")
    links = []
    for link in _rows(content.get("links") or ""):
        label, sep, address = link.partition(": ")
        url = _url(address if sep else link)
        text = tex(label.strip() if sep else link)
        links.append(rf"\href{{{url}}}{{{text}}}" if url else tex(link))
    if links:                                       # one row, as in the CV repository's layout
        contact.append(rf"\cvrow{{{words['links']}}}{{" + r" \,---\, ".join(links) + "}")
    if contact:
        lines += [r"\begin{cvrows}", *contact, r"\end{cvrows}"]

    builders = {
        "summary": lambda v: _paragraph_block(v),
        "education": lambda v: _rows_block(_rows(v), "dated"),
        "skills": lambda v: _rows_block(_rows(v), "labelled"),
        "languages": _languages,
        "experience": _entries,
        "projects": _entries,
        "certifications": lambda v: _rows_block([p.strip() for line in _rows(v) for p in line.split(";") if p.strip()], "dated"),
        "hobbies": lambda v: _paragraph_block(v),
    }
    for section in SECTION_ORDER:
        value = content.get(section) or ""
        body = builders[section](value) if value.strip() else []
        if body:                                   # an empty section gets no heading
            lines += [rf"\cvsection{{{words[section]}}}", *body]
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- compiling

def _limits():
    """Runs in the child before pdflatex starts: its own process group, and hard resource limits."""
    import resource
    os.setsid()
    for limit, value in ((resource.RLIMIT_AS, MEMORY_BYTES), (resource.RLIMIT_CPU, CPU_SECONDS),
                         (resource.RLIMIT_FSIZE, OUTPUT_BYTES), (resource.RLIMIT_NOFILE, 256),
                         (resource.RLIMIT_CORE, 0)):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass


def compile_pdf(tex_source, pdflatex=None):
    executable = pdflatex or shutil.which("pdflatex")
    if not executable:
        raise FileNotFoundError("pdflatex is not installed.")
    with _compile_lock, tempfile.TemporaryDirectory(prefix="jobdesk-cv-") as directory:
        workdir = Path(directory)
        (workdir / "cv.tex").write_text(tex_source, encoding="utf-8")
        shutil.copyfile(STYLE_FILE, workdir / "jobdesk-cv.sty")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(workdir), "TEXMFOUTPUT": str(workdir),
               "TEXMFVAR": str(workdir / "texmf-var"), "openin_any": "p", "openout_any": "p", "shell_escape": "f",
               "LANG": "C.UTF-8"}
        for _ in range(2):          # twice: the page count in the footer comes from the first run
            try:
                process = subprocess.Popen(
                    [executable, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "cv.tex"],
                    cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    preexec_fn=_limits)
            except OSError as error:
                raise PdfBuildError("The LaTeX compiler could not be started.") from error
            try:
                process.communicate(timeout=COMPILE_SECONDS)
            except subprocess.TimeoutExpired as error:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise PdfBuildError("Building the CV took too long. Shorten it and try again.") from error
            if process.returncode:
                raise PdfBuildError("The CV could not be built. Check for very long words or unusual characters.")
        pdf = (workdir / "cv.pdf").read_bytes() if (workdir / "cv.pdf").exists() else b""
        if not pdf.startswith(b"%PDF-"):
            raise PdfBuildError("LaTeX finished without a PDF.")
        return pdf


# ---------------------------------------------------------------- cache

def _cache_dir(user_id):
    import db               # the PDFs live next to the database (and follow it in tests)
    return Path(db.DATA_DIR) / "cv-pdfs" / str(int(user_id))


def cache_key(tex_source):
    style = STYLE_FILE.read_bytes()
    return hashlib.sha256(tex_source.encode("utf-8") + b"\0" + style).hexdigest()[:24]


def build(cv, user_id, pdflatex=None):
    """The CV's PDF, compiled only when the CV (or the layout) changed since the last time."""
    source = render_tex(cv)
    folder = _cache_dir(user_id)
    path = folder / f"{int(cv['id'])}-{cache_key(source)}.pdf"
    if path.exists():
        return path.read_bytes()
    pdf = compile_pdf(source, pdflatex)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    for old in folder.glob(f"{int(cv['id'])}-*.pdf"):
        old.unlink(missing_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(pdf)
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return pdf


def cached_files(user_id):
    folder = _cache_dir(user_id)
    return sorted(folder.glob("*.pdf")) if folder.exists() else []


def remove_cached(user_id, cv_id=None):
    folder = _cache_dir(user_id)
    if not folder.exists():
        return 0
    removed = 0
    for path in folder.glob(f"{int(cv_id)}-*.pdf" if cv_id is not None else "*"):
        path.unlink(missing_ok=True)
        removed += 1
    if cv_id is None:
        shutil.rmtree(folder, ignore_errors=True)
    return removed


def download_name(cv):
    """'Aino Mäkelä' -> 'Aino_Makela_CV.pdf' (letters only, so every system and ATS accepts it)."""
    name = (cv.get("content") or {}).get("full_name") or "CV"
    ascii_name = unicodedata.normalize("NFKD", name.replace("ß", "ss")).encode("ascii", "ignore").decode()
    parts = re.findall(r"[A-Za-z0-9]+", ascii_name)[:4]
    return ("_".join(parts) or "My") + "_CV.pdf"
