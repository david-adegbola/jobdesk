"""Prep page: call script, likely interview questions, honest blocker answers and questions to ask.

No AI calls. Everything comes from the templates in prep/ (one file per job type, plus script.yaml
and blockers.yaml), filled in with the job's title and contact. Draft answers there use only the
facts in CV-RULES.md; answers David edits are saved per job type in the database (db.py) and
replace the drafts for every job of that type.

The templates are a small YAML subset, read here so JobDesk stays standard-library only:
top-level "key: value" lines and lists of "- key: value" items, one value per line, optionally quoted.
"""

import re
from pathlib import Path

PREP_DIR = Path(__file__).resolve().parent / "prep"
TYPES = ["industrial", "warehouse", "it", "trainee", "sales"]

# Which prep type a CV belongs to; for jobs without a CV, which type their Jobly category is
ROLE_TYPE = {"industrial-master": "industrial", "warehouse-master": "warehouse", "it-field-technician": "it",
             "trainee-master": "trainee", "forestry-master": "trainee", "salesperson": "sales"}
CATEGORY_TYPE = {"Industrial": "industrial", "Construction": "industrial", "Warehouse": "warehouse",
                 "IT-Data centre": "it", "Forestry": "trainee", "Sales": "sales"}

LINE = re.compile(r"^(\s*)(- )?([\w-]+):\s*(.*)$")


def _value(raw):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def load_yaml(path):
    data, items = {}, None
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            raise ValueError(f"{path.name} line {n}: expected 'key: value'")
        indent, dash, key, value = m.groups()
        if not indent and not dash:
            if value:
                data[key], items = _value(value), None
            else:
                items = data[key] = []
        elif items is None:
            raise ValueError(f"{path.name} line {n}: list item outside a list")
        elif dash:
            items.append({key: _value(value)})
        elif items:
            items[-1][key] = _value(value)
        else:
            raise ValueError(f"{path.name} line {n}: value before the first '- ' item")
    return data


def type_for(cv_role, category):
    return ROLE_TYPE.get(cv_role) or CATEGORY_TYPE.get(category) or "industrial"


def labels():
    return {t: load_yaml(PREP_DIR / f"{t}.yaml").get("label", t) for t in TYPES}


def question_ids(job_type):
    """Ids that may be saved for a type: its questions, plus blocker:<label> for every known blocker."""
    t = load_yaml(PREP_DIR / f"{job_type}.yaml")
    blocks = load_yaml(PREP_DIR / "blockers.yaml")["blockers"] + t.get("blockers", [])
    return {q["id"] for q in t["questions"]} | {"blocker:" + b["label"] for b in blocks}


def build(job, job_type, blocker_labels, saved):
    """The page content for one job. saved = {question id: {"a_fi", "a_en"}} for this type."""
    t = load_yaml(PREP_DIR / f"{job_type}.yaml")
    first_name = (job.get("contact_name") or "").split(" ")[0]
    fill = {"title": job.get("title") or "", "intro_fi": t["intro_fi"], "intro_en": t["intro_en"]}

    def line(text):
        text = text.replace(" {name}", f" {first_name}" if first_name else "")
        return text.format(**fill)

    script = [{"fi": line(x["fi"]), "en": line(x["en"])} for x in load_yaml(PREP_DIR / "script.yaml")["lines"]]

    questions = []
    for q in t["questions"]:
        s = saved.get(q["id"])
        questions.append({**q, "draft_fi": q["a_fi"], "draft_en": q["a_en"], "edited": bool(s),
                          "a_fi": s["a_fi"] if s else q["a_fi"], "a_en": s["a_en"] if s else q["a_en"]})

    drafts = {b["label"]: b for b in load_yaml(PREP_DIR / "blockers.yaml")["blockers"]}
    drafts.update({b["label"]: b for b in t.get("blockers", [])})       # the type's own wording wins
    blockers = []
    for label in blocker_labels:
        d = drafts.get(label, {"fi": f"Minulla ei ole tätä vielä ({label}), mutta haluan oppia.",
                               "en": f"I don't have this yet ({label}), but I want to learn."})
        s = saved.get("blocker:" + label)
        blockers.append({"id": "blocker:" + label, "label": label, "draft_fi": d["fi"], "draft_en": d["en"],
                         "edited": bool(s), "a_fi": s["a_fi"] if s else d["fi"], "a_en": s["a_en"] if s else d["en"]})

    return {"type": job_type, "type_label": t.get("label", job_type), "script": script,
            "questions": questions, "blockers": blockers, "ask": t.get("ask", [])}
