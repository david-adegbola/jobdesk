"""A CV turned into numbered facts that a draft can cite, plus the things the person is still learning.

facts_from_cv(content) -> {"facts": [{"id", "section", "text"}], "learning": [str]}

  ids         sum-1 (summary paragraphs), edu-1, exp-1, proj-1, skill-1, cert-1, lang-1, hob-1
  experience  and projects: one fact per entry (its dated heading plus its detail lines);
              "Tags:" lines are left out.
  learning    items on "Want to learn: …" / "Haluan oppia: …" rows. They are NOT facts: a draft must
              never present them as skills the person has (core/verify.py checks this).

Never included (data minimisation: the model doesn't need them to answer a question):
full_name, email, phone, location, links, target_role.
"""

import re

LEARN_ROW = re.compile(r"^\s*(?:haluan oppia|want to learn)\s*:\s*(.*)$", re.I)
TAGS_ROW = re.compile(r"^\s*tags\s*:", re.I)
NEVER_SENT = ("full_name", "email", "phone", "location", "links", "target_role")


def _rows(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _paragraphs(value):
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", (value or "").strip()) if p.strip()]


def _is_dated_heading(line):
    """Same rule as cv_latex._experience_blocks: a separator with a digit before it
    ("2025: …", "May 2025--Aug 2025 — Title — Employer")."""
    return any(sep in line and re.search(r"\d", line.partition(sep)[0]) for sep in (": ", " — ", " – "))


def _entries(value):
    """Experience-style blocks: a new entry starts at a blank line or a dated heading."""
    entries, current, blank = [], [], False
    for raw in (value or "").splitlines():
        line = raw.strip()
        if not line:
            blank = True
            continue
        if TAGS_ROW.match(line):
            continue
        if current and (blank or _is_dated_heading(line)):
            entries.append(current)
            current = []
        current.append(line)
        blank = False
    if current:
        entries.append(current)
    return ["; ".join(entry) for entry in entries]


def facts_from_cv(content):
    content = content or {}
    facts, learning = [], []

    def add(prefix, section, texts):
        for number, text in enumerate(texts, start=1):
            facts.append({"id": f"{prefix}-{number}", "section": section, "text": text})

    add("sum", "summary", _paragraphs(content.get("summary")))
    add("edu", "education", _rows(content.get("education")))
    add("exp", "experience", _entries(content.get("experience")))
    add("proj", "projects", _entries(content.get("projects")))
    skill_rows = []
    for row in _rows(content.get("skills")):
        learn = LEARN_ROW.match(row)
        if learn:
            learning += [item.strip() for item in re.split(r"[,;]", learn.group(1)) if item.strip()]
        else:
            skill_rows.append(row)
    add("skill", "skills", skill_rows)
    add("cert", "certifications", _rows(content.get("certifications")))
    add("lang", "languages", [part.strip() for row in _rows(content.get("languages"))
                              for part in row.split(";") if part.strip()])
    add("hob", "hobbies", _rows(content.get("hobbies")))
    return {"facts": facts, "learning": learning}


def as_text(facts):
    """The facts as lines for the prompt: 'exp-1: ...'."""
    return "\n".join(f"{fact['id']}: {fact['text']}" for fact in facts)
