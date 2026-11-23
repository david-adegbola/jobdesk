"""Explainable job matching and blocker detection.

Match: each role's keywords come from its public job.md (Role, Job type) and its CVs (Skills rows
and tags). Score = (matched keywords + 3 x those also in the job title) / min(keywords, 10) for a title, or
/ min(keywords, 25) once the full ad is read (a long ad would otherwise give every role 100), capped at 100.
Ties go to the role that matches the title, then to the one with more matched words. Matching allows
Finnish case endings and compounds (word_matches). The matched words are shown, so every score can be checked by eye.

Blockers: things an ad asks for that the administrator doesn't have, from the "Not held" and
"NOT confirmed" lists in CV-RULES.md (via facts.json), plus some the ads often ask for, such as a C
licence and fluent Finnish.

Public CV links (employer_link, pdf_links) come from the owner profile (owner.py); without one they
are empty.
"""

import re

import owner
from config import ROLES_DIR
# The word helpers live in core/text.py (shared with the Flask app); re-exported here so
# match.tokens, match.stem, match.word_matches and the word lists keep working everywhere.
from core.text import (BOILERPLATE, COMPOUND_MIN, STOP_STEMS, STOPWORDS, WORD,  # noqa: F401
                       stem, tokens, word_matches)

# Skills-section labels whose rows are not job skills
SKIP_LABELS = re.compile(r"kielet|languages|sijainti|location|puhelin|phone|sähköposti|email|links|"
                         r"availability|saatavuus|\d{4}", re.I)

# label -> (facts key or None, regex). A blocker only counts if the fact says the administrator lacks it.
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
    ("electrical safety card", None, r"sähkötyöturvallisuu|sfs ?6002|electrical safety (?:card|training)"),
    ("first aid card", None, r"\bea ?1\b|ensiapukortti|ensiapukoulutus|first aid"),
    ("1+ years' experience", None,
     r"at least (?:one|two|three|\d+) years?\b|\b\d+\+? years?(?:'|’)? (?:of )?(?:relevant |similar |work )?experience|"
     r"(?:one|two|three) years? of (?:relevant |similar |work )?experience|"
     r"vähintään (?:vuoden|\d+ vuoden|kahden|kolmen)|(?:usean|useamman) vuoden (?:työ)?kokemus"),
    ("vocational qualification", None,
     r"vocational (?:education|qualification|degree)|technical/vocational|ammatillinen (?:tutkinto|koulutus)|"
     r"alan (?:ammatillinen|perus)tutkinto|alalle soveltuva koulutus"),
    ("brush saw experience", None, r"raivaussah|brush ?saw|clearing saw"),
    ("chainsaw", None, r"moottorisah|chain ?saw"),
    ("forest machine operator qualification", None, r"metsäkoneenkuljettaj|forest machine operator"),
    ("forestry degree", None,
     r"metsä\w* \w*tutkin|metsätalousinsinöö|metsänhoitaj|metsätieteiden|forestry degree|degree in forestry|"
     r"(?:bsc|msc|bachelor|master)\W+(?:\w+\W+)?forestry"),
]


FULL_AD_WORDS = 60   # fewer words than this = a title or short listing, so the smaller cap is used
TITLE_WEIGHT = 3   # a skill word that matches the job title is the strongest sign of the right CV


LEARN_LABELS = re.compile(r"haluan oppia|want to learn", re.I)


def _learn_words(tex):
    """Words from the "want to learn" rows: they help find the closest CV, but they aren't facts."""
    words = set()
    for label, value in re.findall(r"\\cvline(?:\[[^\]]*\])?\{([^}]*)\}\{([^}]*)\}", tex):
        if LEARN_LABELS.search(label):
            words |= set(tokens(re.sub(r"\\[a-z]+", " ", value)))
    return words


def _tex_keywords(tex, facts_only=False):
    words = []
    for label, value in re.findall(r"\\cvline(?:\[[^\]]*\])?\{([^}]*)\}\{([^}]*)\}", tex):
        if facts_only and LEARN_LABELS.search(label):
            continue
        if not SKIP_LABELS.search(label) and "\\href" not in value:
            words += tokens(re.sub(r"\\[a-z]+", " ", value))
    for tags in re.findall(r"\\sotagrow\{([^}]*)\}", tex):
        words += tokens(tags.replace("-", " ").replace(",", " "))
    return words


# Each role's language, from the "- **Language:** ..." line in its job.md (cv repo, CV-RULES.md section 1).
# Same rules as the cv repo's site/language.py; read as data here, never run.
LANGUAGE_ORDER = {"fi-first": ["fi", "en"], "en-first": ["en", "fi"], "en-only": ["en"]}
LANGUAGE_DEFAULT = "fi-first"
LANGUAGE_FIELD = re.compile(r"^\W*language\W*:\W*([a-z]+-[a-z]+)", re.I | re.M)
COMBINED_LABEL = {"fi-first": "FI + EN", "en-first": "EN + FI", "en-only": "EN (to send)"}


def language_of(job_md_text):
    m = LANGUAGE_FIELD.search(job_md_text)
    value = m.group(1).lower() if m else LANGUAGE_DEFAULT
    return value if value in LANGUAGE_ORDER else LANGUAGE_DEFAULT


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
        learn, facts = set(), set(words)
        for tex in sorted(d.glob("cv-*.tex")):
            words += _tex_keywords(tex.read_text(encoding="utf-8"))
            learn |= _learn_words(tex.read_text(encoding="utf-8"))
            facts |= set(_tex_keywords(tex.read_text(encoding="utf-8"), facts_only=True))
        keywords = {}
        for w in words:
            if len(w) > 2 and w not in STOPWORDS and not w.isdigit() and stem(w) not in STOP_STEMS:
                keywords.setdefault(stem(w), w)
        language = language_of(md)
        # the languages the cv repo builds for this role, main version first
        langs = [lang for lang in LANGUAGE_ORDER[language] if (d / f"cv-{lang}.tex").exists()]
        footers = {}
        for lang in langs:
            m = re.search(r"\\cvrole\{([^}]*)\}", (d / f"cv-{lang}.tex").read_text(encoding="utf-8"))
            if m:
                footers[lang] = m.group(1).strip()
        roles.append({"slug": d.name, "title": title, "keywords": keywords, "language": language, "langs": langs,
                      "footers": footers, "learn": learn - facts})   # words only on the want-to-learn rows
    return roles


def match(text, roles, title=""):
    """Score every role against an ad; best first. Each result lists the matched words.
    A skill word that also matches a word in the job title counts 1 + TITLE_WEIGHT times."""
    words = {w for w in tokens(text) if w not in STOPWORDS}
    title_words = {w for w in tokens(title) if w not in STOPWORDS}
    cap = 10 if len(words) < FULL_AD_WORDS else 25
    results = []
    for r in roles:
        hit, in_title = [], 0
        for kw in sorted(set(r["keywords"].values())):
            found = [w for w in words if word_matches(w, kw)]
            if found:
                hit.append(kw)
                in_title += any(w in title_words for w in found)
        base = max(1, min(len(r["keywords"]), cap))
        results.append({"slug": r["slug"], "score": min(100, round(100 * (len(hit) + TITLE_WEIGHT * in_title) / base)), "words": hit,
                        "in_title": in_title})
    results.sort(key=lambda x: (-x["score"], -x["in_title"], -len(x["words"]), x["slug"]))
    return results


def blockers(text, facts):
    lacking = {x.lower() for x in facts.get("not_held", []) + facts.get("not_confirmed", [])}
    t = (text or "").lower()
    found = []
    for label, fact, pattern in BLOCKERS:
        if fact and fact.lower() not in lacking:
            continue          # the fact changed (they have it now), so it's no longer a blocker
        if re.search(pattern, t):
            found.append(label)
    return found


def _public_base():
    return owner.get("public_cv_base").rstrip("/")


def employer_link(slug):
    """The public page for one role's CV, or '' when no owner profile sets public_cv_base."""
    base = _public_base()
    return f"{base}/r/{slug}/" if base else ""


def pdf_links(role):
    """The file to send first (combined, main language first; for en-only the English CV), then each language.
    Empty when no owner profile sets public_cv_base."""
    if not _public_base():
        return {}
    base = f"{_public_base()}/{owner.get('pdf_prefix')}{role['slug']}"
    links = {}
    if role["langs"] == LANGUAGE_ORDER[role["language"]]:      # every file the setting needs exists
        links["combined"] = f"{base}.pdf"
    links.update({lang: f"{base}-{lang}.pdf" for lang in role["langs"]})
    return links
