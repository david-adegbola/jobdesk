"""Import the administrator's existing role CVs as editable account CVs."""

import re
from pathlib import Path

import config
import db


CONTENT_FIELDS = (
    "target_role", "full_name", "email", "phone", "location", "summary", "education",
    "experience", "skills", "projects", "hobbies", "certifications", "languages", "links",
)


def _argument(text, position):
    while position < len(text) and text[position].isspace():
        position += 1
    if position >= len(text) or text[position] != "{":
        return "", position
    depth = 1
    start = position + 1
    position += 1
    while position < len(text) and depth:
        if text[position] == "\\":
            position += 2
            continue
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
        position += 1
    if depth:
        raise ValueError("Unclosed LaTeX argument in CV source.")
    return text[start:position - 1], position


def _macro_arguments(text, command, count):
    pattern = re.compile(rf"\\{re.escape(command)}\b")
    for match in pattern.finditer(text):
        position = match.end()
        while position < len(text) and text[position].isspace():
            position += 1
        if position < len(text) and text[position] == "[":
            end_optional = text.find("]", position + 1)
            if end_optional < 0:
                raise ValueError(f"Unclosed optional argument for \\{command}.")
            position = end_optional + 1
        args = []
        for _ in range(count):
            value, position = _argument(text, position)
            args.append(value)
        if all(args):
            yield match.start(), position, args


def _replace_macro(text, command, count, render):
    matches = list(_macro_arguments(text, command, count))
    for start, end, args in reversed(matches):
        text = text[:start] + render(args) + text[end:]
    return text


def _without_comments(text):
    return "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in text.splitlines())


def _plain_text(text):
    text = _without_comments(text)
    entries = re.compile(r"\\begin\{cventry\}(.*?)\\end\{cventry\}", re.S)

    def render_entry(match):
        body = match.group(1)
        start = 0
        date_text, start = _argument(body, start)
        heading, start = _argument(body, start)
        details = body[start:]
        return f"\n{date_text} — {heading}\n{details}\n"

    text = entries.sub(render_entry, text)
    text = _replace_macro(
        text, "cvline", 2,
        lambda args: f"\n{_plain_text(args[0]).strip().rstrip(':')}: {_plain_text(args[1]).strip()}\n",
    )
    text = _replace_macro(
        text, "href", 2,
        lambda args: _plain_text(args[1]).strip()
        + (f" ({_plain_text(args[0]).strip()})" if args[0].startswith(("http:", "https:")) else ""),
    )
    text = _replace_macro(text, "job", 2, lambda args: f"{_plain_text(args[0])} — {_plain_text(args[1])}")
    text = _replace_macro(text, "sotagrow", 1, lambda args: f"\nTags: {args[0]}\n")
    text = re.sub(
        r"\\begin\{tabular\}\s*\{(?:[^{}]|\{[^{}]*\})*\}",
        "\n",
        text,
    )
    for command in ("textbf", "textit", "textsc", "emph", "cvt"):
        text = _replace_macro(text, command, 1, lambda args: _plain_text(args[0]))
    text = re.sub(r"\\(?:begin|end)\{[^}]+\}", "\n", text)
    text = re.sub(r"\\\\(?:\[[^\]]*\])?", "\n", text)
    text = re.sub(r"\\par\b", "\n", text)
    text = re.sub(r"\\(?:fa[A-Za-z]+|small|large|Large|Huge|centering|bigskip|medskip|hrule|noindent)\b", "", text)
    text = re.sub(r"\\[A-Za-z@]+\*?", "", text)
    text = re.sub(r"\\([%&_#$])", r"\1", text)
    text = text.replace("~", " ")
    text = re.sub(r"[{}]", "", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _extract_sections(text):
    matches = list(re.finditer(r"\\section(?=\s*\{)", text))
    sections = []
    for index, match in enumerate(matches):
        title, end = _argument(text, match.end())
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((_plain_text(title).strip().lower(), text[end:stop]))
    return sections, text[:matches[0].start()] if matches else text


def parse_cv(source, path):
    role_match = next(_macro_arguments(source, "cvrole", 1), None)
    if not role_match:
        raise ValueError(f"{path}: CV role title is missing.")
    role = _plain_text(role_match[2][0]).strip()
    language = "fi" if path.stem.endswith("-fi") else "en"
    content = {field: "" for field in CONTENT_FIELDS}
    content["target_role"] = role
    sections, header = _extract_sections(_without_comments(source))

    name = re.search(r"\\Huge\s*\\textsc\{([^}]+)\}", header)
    if name:
        content["full_name"] = _plain_text(name.group(1))

    for _, _, args in _macro_arguments(header, "cvline", 2):
        label = _plain_text(args[0]).strip().lower().rstrip(":")
        value = _plain_text(args[1])
        target = {
            "location": "location", "sijainti": "location",
            "phone": "phone", "puhelin": "phone",
            "email": "email", "sähköposti": "email",
            "links": "links", "linkit": "links",
        }.get(label)
        if target:
            content[target] = "\n".join(filter(None, (content[target], value)))
        elif label and value:
            content["summary"] = "\n".join(filter(
                None, (content["summary"], f"{label.capitalize()}: {value}"),
            ))

    section_fields = {
        "summary": "summary", "profile": "summary", "profiili": "summary",
        "education": "education", "koulutus": "education",
        "experience": "experience", "work experience": "experience", "työkokemus": "experience",
        "skills": "skills", "osaaminen": "skills",
        "projects": "projects", "research": "projects", "projects and research": "projects",
        "certifications": "certifications", "certificates": "certifications", "sertifikaatit": "certifications",
        "languages": "languages", "language skills": "languages", "kielitaito": "languages",
        "links": "links", "hobbies": "hobbies", "interests": "hobbies",
    }
    for heading, body in sections:
        field = section_fields.get(heading)
        if field:
            value = _plain_text(body)
            if value:
                content[field] = "\n".join(filter(None, (content[field], value)))

    return {
        "title": f"{role} ({'Suomi' if language == 'fi' else 'English'})",
        "language": language,
        "content": content,
    }


def import_admin_cv_repo(repo=None):
    root = Path(repo or config.CV_REPO).resolve()
    roles = root / "roles"
    if not roles.is_dir():
        return 0
    imported = 0
    for tex_file in sorted(roles.glob("*/cv-*.tex")):
        if tex_file.stem not in {"cv-fi", "cv-en"}:
            continue
        resolved = tex_file.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"CV source resolves outside the repository: {tex_file}")
        source_key = resolved.relative_to(root).as_posix()
        cv = parse_cv(resolved.read_text(encoding="utf-8"), resolved)
        if db.import_cv_for_admin(source_key, cv["title"], cv["language"], cv["content"]):
            imported += 1
    return imported
