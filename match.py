"""Explainable job matching and blocker detection.

Match: each role's keywords come from its public job.md (Role, Job type) and its CVs (Skills rows
and tags). Score = matched keywords / min(keywords, 10), capped at 100. The matched words are shown,
so every score can be checked by eye.

Blockers: things an ad asks for that David doesn't have, from the "Not held" and "NOT confirmed"
lists in CV-RULES.md (via facts.json), plus two the ads often ask for: C licence and fluent Finnish.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROLES_DIR = REPO / "roles"
PUBLIC_BASE = "https://david-adegbola.github.io/cv"

WORD = re.compile(r"[a-zåäö0-9][a-zåäö0-9-]*[a-zåäö0-9]|[a-zåäö]", re.I)
STOPWORDS = set("""
ja tai sekä on ole olen olet ovat oli myös kanssa joka jotka jossa että kun mutta niin kuin
the and or of to in for on with at by an a as is are be from this that your our you we
työ työt työn töitä työssä työhön tehtävä tehtäviin tehtävät haemme etsimme hae oy ab ltd
cv master role job type sent unchanged similar jobs including want learn opettelen haluan oppia
basic perustaidot tietotekniikan tietotekniikka computer skills it
worker workers henkilöstö henkilöstöpalvelut staff
""".split())
# Skills-section labels whose rows are not job skills
SKIP_LABELS = re.compile(r"kielet|languages|sijainti|location|puhelin|phone|sähköposti|email|links|"
                         r"availability|saatavuus|\d{4}", re.I)

# label -> (facts key or None, regex). A blocker only counts if the fact says David lacks it.
BLOCKERS = [
    ("welding", "welding", r"hitsa|welding|welder"),
    ("welding certificate", "welding certificates", r"hitsauspätevyy|hitsaussertifik|welding certif"),
    ("hot-work card", "hot-work card", r"tulityö|hot[- ]work"),
    ("forklift card", "forklift card", r"trukki|trukin|forklift"),
    ("reading drawings", "reading drawings", r"piirustu|drawings|blueprint"),
    ("B licence", "B driving licence",
     r"\bb-(?:ajo)?kort|(?<![c-])\bajokortti|driving licen[cs]e|driver'?s licen[cs]e|ajokortillinen"),
    ("C licence", None, r"\bc-(?:ajo)?kort|\bce-(?:ajo)?kort|c-kortillinen|\bc licen[cs]e"),
    ("fluent Finnish", None,
     r"sujuva\w* suome|hyvä\w* suomen kiel|erinomai\w* suomen kiel|fluent finnish|native finnish|"
     r"suomen kielen taito on (?:edellytys|välttämätön)"),
    ("electrician qualification", None, r"sähköasentaja|sähköpätevyy|sähköalan tutkin"),
]


def tokens(text):
    return [w.lower() for w in WORD.findall(text or "")]


def stem(word):
    """Crude stem so Finnish inflections still match: first 6 letters of long words."""
    return word[:6] if len(word) > 6 else word


def _tex_keywords(tex):
    words = []
    for label, value in re.findall(r"\\cvline(?:\[[^\]]*\])?\{([^}]*)\}\{([^}]*)\}", tex):
        if not SKIP_LABELS.search(label) and "\\href" not in value:
            words += tokens(re.sub(r"\\[a-z]+", " ", value))
    for tags in re.findall(r"\\sotagrow\{([^}]*)\}", tex):
        words += tokens(tags.replace("-", " ").replace(",", " "))
    return words


def load_roles():
    """Every roles/<slug>/ with its title and keyword list."""
    roles = []
    for d in sorted(ROLES_DIR.iterdir()):
        job_md = d / "job.md"
        if not job_md.exists():
            continue
        md = job_md.read_text(encoding="utf-8")
        title = (re.search(r"^# (.+)$", md, re.M) or [None, d.name])[1].strip()
        words = []
        for field in ("Role", "Job type"):
            m = re.search(rf"^- \*\*{field}:\*\* (.+)$", md, re.M)
            if m:
                words += tokens(m.group(1))
        for tex in sorted(d.glob("cv-*.tex")):
            words += _tex_keywords(tex.read_text(encoding="utf-8"))
        keywords = {}
        for w in words:
            if len(w) > 2 and w not in STOPWORDS and not w.isdigit():
                keywords.setdefault(stem(w), w)
        langs = sorted(p.stem[3:] for p in d.glob("cv-*.tex"))
        roles.append({"slug": d.name, "title": title, "keywords": keywords, "langs": langs})
    return roles


def match(text, roles):
    """Score every role against an ad; best first. Each result lists the matched words."""
    ad = {stem(w) for w in tokens(text) if w not in STOPWORDS}
    results = []
    for r in roles:
        hit = sorted({r["keywords"][s] for s in r["keywords"] if s in ad})
        base = max(1, min(len(r["keywords"]), 10))
        results.append({"slug": r["slug"], "score": min(100, round(100 * len(hit) / base)), "words": hit})
    results.sort(key=lambda x: (-x["score"], x["slug"]))
    return results


def blockers(text, facts):
    lacking = {x.lower() for x in facts.get("not_held", []) + facts.get("not_confirmed", [])}
    t = (text or "").lower()
    found = []
    for label, fact, pattern in BLOCKERS:
        if fact and fact.lower() not in lacking:
            continue          # David has it now (fact changed), so it's no longer a blocker
        if re.search(pattern, t):
            found.append(label)
    return found


def employer_link(slug):
    return f"{PUBLIC_BASE}/r/{slug}/"


def pdf_links(role):
    base = f"{PUBLIC_BASE}/david-adegbola-{role['slug']}"
    links = {lang: f"{base}-{lang}.pdf" for lang in role["langs"]}
    if "fi" in role["langs"] and "en" in role["langs"]:
        links["combined"] = f"{base}.pdf"
    return links
