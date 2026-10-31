"""Builds the Claude Code prompt for a job, following the template in CV-RULES.md / David's workflow.

It never writes placeholders: questions() lists everything the ad raises that the facts don't answer,
and build() refuses to produce a prompt until every one of them is answered.
"""

import re
import unicodedata

import match

# Questions an ad can raise that the facts (facts.json) don't answer.
# (id, question, kind, regex that triggers it; None = always ask)
QUESTIONS = [
    ("start", "When can you start?", "text", None),
    ("area", "Where can you work? Can you travel or work away from Joensuu?", "text",
     r"matkust|travel|komennu|reissu|eri puolil|paikkakun|työmaille|majoitus"),
    ("shifts", "Can you work shifts, nights or weekends?", "yesno",
     r"vuorotyö|kaksivuor|kolmivuor|yötyö|viikonlop|shift|weekend"),
    ("b_licence", "Do you have a B driving licence?", "yesno",
     r"\bb-(?:ajo)?kort|(?<![c-])\bajokortti|driving licen[cs]e|ajokortillinen"),
    ("salary", "What is your salary expectation (with a one-line reason)?", "text",
     r"palkkatoive|palkkapyyn|salary expectation|salary request"),
    ("hobbies", "Which hobbies should the application mention?", "text", r"harrastu|harrastuks|hobbies|hobby"),
]
# Blockers David could list as "want to learn" in the CV
LEARNABLE = {"welding", "reading drawings", "hot-work card", "forklift card", "C licence", "welding certificate"}


LANGUAGE_NOTES = {
    "fi-first": "cv-fi.tex is the main version; combined PDF = Finnish, then English",
    "en-first": "cv-en.tex is the main version; combined PDF = English, then Finnish",
    "en-only": "only cv-en.tex, no cv-fi.tex; the combined PDF is the English CV",
}
EN_WORDS = set("the and you we our with for will are your experience work team skills".split())
FI_WORDS = set("ja on sekä olet meillä työ tehtävä haemme kokemus taitoa tarjoamme".split())


def ad_language(text):
    """en-first for ads written in English, otherwise fi-first (the default)."""
    words = match.tokens(text or "")
    return "en-first" if sum(w in EN_WORDS for w in words) > sum(w in FI_WORDS for w in words) else "fi-first"


def slugify(text):
    t = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40]


def _ad_keywords(text, role):
    """Words as written in the ad whose stem matches the role's keywords (Finnish forms kept)."""
    out = []
    for w in match.tokens(text):
        if match.stem(w) in role["keywords"] and w not in match.STOPWORDS and w not in out:
            out.append(w)
    return out[:14]


def _tags(slug):
    from pathlib import Path
    tex = Path(match.ROLES_DIR, slug, "cv-en.tex")
    m = re.search(r"\\sotagrow\{([^}]*)\}", tex.read_text(encoding="utf-8")) if tex.exists() else None
    return m.group(1).split(",") if m else []


def analyse(job, roles, facts):
    text = " ".join(job.get(k) or "" for k in ("title", "ad_text"))
    scores = match.match(text, roles)
    best = scores[0] if scores else None
    role = next((r for r in roles if best and r["slug"] == best["slug"]), None)
    blockers = match.blockers(text, facts)
    not_confirmed = {x.lower() for x in facts.get("not_confirmed", [])}
    questions = []
    for qid, q, kind, pattern in QUESTIONS:
        if qid == "b_licence" and "b driving licence" not in not_confirmed:
            continue
        if pattern is None or re.search(pattern, text.lower()):
            questions.append({"id": qid, "question": q, "kind": kind})
    base_title = re.split(r"[,/(–-]", job.get("title") or "")[0].strip()
    return {
        "job": {k: job.get(k) or "" for k in ("title", "company", "location", "url", "deadline",
                                             "contact_name", "contact_phone")},
        "closest": best["slug"] if best else "",
        "closest_score": best["score"] if best else 0,
        "closest_language": role["language"] if role else match.LANGUAGE_DEFAULT,
        "keywords": _ad_keywords(text, role) if role else [],
        "blockers": blockers,
        "tags": _tags(best["slug"]) if best else [],
        "questions": questions,
        "defaults": {"mode": "new", "language": ad_language(text), "slug": slugify(base_title) or "new-role",
                     "role_fi": base_title,
                     "role_en": role["title"].split("/")[0].strip() if role else ""},
        "has_ad_text": bool(job.get("ad_text")),
    }


def build(analysis, answers):
    """Returns (prompt, missing). missing lists unanswered questions/fields; prompt is None then."""
    a = {k: (v or "").strip() if isinstance(v, str) else v for k, v in (answers or {}).items()}
    missing = [q["question"] for q in analysis["questions"] if not a.get(q["id"])]
    mode = a.get("mode") or "new"
    # a new CV takes the chosen language; an existing CV keeps the setting in its job.md
    language = (a.get("language") or match.LANGUAGE_DEFAULT) if mode == "new" else analysis["closest_language"]
    if language not in match.LANGUAGE_ORDER:
        missing.append("Language (fi-first, en-first or en-only)")
    fields = [("slug", "Role folder name"), ("role_en", "English role title")]
    if language != "en-only":
        fields.insert(1, ("role_fi", "Finnish role title"))
    for key, label in fields:
        if mode == "new" and not a.get(key):
            missing.append(label)
    job = analysis["job"]
    company_words = [w for w in match.tokens(job["company"]) if len(w) > 3 and w not in ("oyj", "henkilöstöpalvelut")]
    slug = slugify(a.get("slug") or "")
    if mode == "new" and slug and any(w in slug for w in map(slugify, company_words)):
        missing.append("Role folder name must describe the job type, not the employer (CV-RULES.md)")
    if not job["title"]:
        missing.append("Job title")
    if missing:
        return None, missing

    licence = a.get("b_licence") == "yes"
    learn = [b for b in analysis["blockers"] if b in LEARNABLE and not (b == "B licence" and licence)]
    hard = [b for b in analysis["blockers"] if b not in LEARNABLE and not (b == "B licence" and licence)]
    target = ", ".join(x for x in (job["company"], job["title"], job["location"]) if x)
    contact = " ".join(x for x in (job["contact_name"], job["contact_phone"]) if x)
    extras = [x for x in (job["url"], f"contact {contact}" if contact else "",
                          f"deadline {job['deadline']}" if job["deadline"] else "") if x]
    closest = analysis["closest"]
    answers_lines = [f"- {q['question']} {'Yes' if a[q['id']] == 'yes' else 'No' if a[q['id']] == 'no' else a[q['id']]}"
                     for q in analysis["questions"]]
    cards = "occupational safety card" + ("; B driving licence (confirmed by me: correction for all CVs, "
                                          "update section 7 of CV-RULES.md)" if licence else "")
    lines = [
        "In my repo david-adegbola/cv, read CV-RULES.md in full first and follow it exactly.",
        "If anything below conflicts with CV-RULES.md or its facts, stop and ask me.",
        "",
    ]
    if mode == "new":
        lines += [
            "Task: new CV",
            f"Role folder: roles/{slug}/ (start from roles/{closest}/)",
            (f"Footer role text: \"{a['role_en']}\" (en)" if language == "en-only" else
             f"Footer role text: \"{a['role_fi']}\" (fi) / \"{a['role_en']}\" (en)"),
            f"Language (job.md): {language} ({LANGUAGE_NOTES[language]})",
        ]
    else:
        lines += [f"Task: no new CV. Use the existing roles/{closest}/ for this application."]
    lines += [
        f"Target job: {target}" + (f" ({'; '.join(extras)})" if extras else ""),
        "Ad keywords to use (from the ad, only where they match my facts): " + (", ".join(analysis["keywords"]) or "none found"),
        "Blockers in the ad (do NOT claim them): " + (", ".join(analysis["blockers"]) or "none"),
        "My answers to what the ad asks:",
        *answers_lines,
    ]
    if mode == "new":
        lines += [
            "Tailoring:",
            "- Summary angle: lead with the Axioma Servisas UAB job (certificate wording) and the kiitettävä rating; "
            "stress " + (", ".join(analysis["keywords"][:6]) or "the closest matching skills") + ".",
            f"- Experience order and wording: as in roles/{closest}/, tailored to this ad.",
            "- Skills / Taidot: the ad keywords above" + (f"; want to learn: {', '.join(learn)}" if learn else "") + ".",
            f"- Cards / Kortit: {cards}.",
            "- Tags under the Axioma job: " + (", ".join(analysis["tags"]) or "5–6 tags from the ad keywords") + ".",
        ]
        if hard:
            lines.append(f"- The ad also asks for {', '.join(hard)}. Say it honestly in my report; don't claim it.")
    emails = {"fi-first": "a Finnish email (max 120 words) and an English copy",
              "en-first": "an English email (max 120 words) and a Finnish copy",
              "en-only": "an English email (max 120 words)"}[language]
    lines += [
        f"Applications (applications/, never committed): {emails} for "
        f"{job['company'] or 'this employer'}, using my answers above and the same honesty rules as the CV.",
        f"Private details (company, contact, link, deadline) go in applications/job-details/"
        f"{slug if mode == 'new' else closest}.md, never in job.md.",
    ]
    if mode == "new":
        lines += [f"Commit message: \"Add CV: {a['role_en']} ({'EN' if language == 'en-only' else 'FI + EN'})\""]
    pdfs = ("the combined PDF (the English CV)" if language == "en-only"
            else "the combined PDF and both language links")
    lines += [
        f"Report: the employer link https://david-adegbola.github.io/cv/r/{slug if mode == 'new' else closest}/ first, "
        f"then {pdfs}, and any facts that differ from my other CVs.",
    ]
    return "\n".join(lines) + "\n", []
