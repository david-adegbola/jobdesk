"""Application documents for one job: a tailored CV, a cover letter and a short application email.
Standard library only.

prepare(job, cv_content, profile, recipient, language, finnish_level, settings, call=None, use_ai=True, today=None)
    -> {"cv_content": tailored CV content, "letter": {...}, "email": {...}, "checks": {...},
        "method", "model", "prompt_version", "notice"}

The layout and content rules follow the CV repository's CV-RULES.md (sections 4-6 and 9), written here
generically so they work for any student:
  letter    header (name, job title, location, phone, email), date, recipient, bold subject
            "Application: <job>, <company> <city>", greeting by first name or "Hello,", then five short
            paragraphs: (1) what and why, (2) the most relevant experience, (3) what is new and how the person
            learns, (4) practical fit (start date, hours, place, cards, permit), (5) the honest Finnish line and
            "my CV is attached"; closing, name, phone, email.
  email     subject = the letter's subject; the same greeting; "I just applied for ..."; two or three of the
            letter's strongest sentences (nothing new); the Finnish line; an offer to talk; closing and contacts.
  CV        the CV with a summary written for this job (two paragraphs) and the skills the ad mentions first.

Grounding: every sentence the AI writes (or the mock copies) cites CV facts or practical details and is checked
by core.verify, exactly like "Draft an answer". Failing sentences are kept, marked, for the person to fix.
Fixed phrases (the opener, the Finnish line, the closing...) come from TEXT below and are not AI output.
Writing style: style_warnings() flags the "AI tells" CV-RULES.md section 5 lists (buzzwords, em dashes...).
"""

import re
from datetime import date
from pathlib import Path

from core import cv_facts, llm, verify
from core import fit as core_fit
from core.text import STOPWORDS, tokens, word_matches

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "application_documents.md"
PROMPT_VERSION = "application_documents-v1"
LANGUAGES = ("en", "fi")
FINNISH_LEVELS = ("none", "basic", "intermediate", "fluent")
PROFILE_FIELDS = {          # practical details the person states; they become facts prof-1, prof-2 ...
    "available_from": ("Available from", "Voin aloittaa"),
    "hours": ("Working hours", "Työajat"),
    "locations": ("Can work in", "Voin työskennellä"),
    "permit": ("Work permit", "Työlupa"),
    "licences": ("Licences and cards", "Ajokortit ja kortit"),
}
EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December")

TEXT = {
    "en": {
        "subject": "Application: {job}, {company_place}",
        "greeting": "Hi {first},", "greeting_none": "Hello,",
        "opener": "I'm applying for the {job} position at {company}.", "opener_nc": "I'm applying for the {job} position.",
        "finnish": {"none": "I don't speak Finnish yet, and I work in English.",
                    "basic": "My Finnish is still basic, and I'm actively studying it.",
                    "intermediate": "I speak Finnish at an intermediate level and keep improving it.",
                    "fluent": ""},
        "attached": "My CV is attached, and I'm happy to tell you more by phone or in an interview.",
        "closing": "Kind regards",
        "just_applied": "I just applied for the {job} position{at_company}. My CV and cover letter are attached here as well.",
        "at": " at {company}",
        "talk": "I'd be glad to talk more by phone or in an interview.",
    },
    "fi": {
        "subject": "Hakemus: {job}, {company_place}",
        "greeting": "Hei {first},", "greeting_none": "Hei,",
        "opener": "Haen tehtävää {job} ({company}).", "opener_nc": "Haen tehtävää {job}.",
        "finnish": {"none": "En vielä puhu suomea, ja työskentelen englanniksi.",
                    "basic": "Suomen kielen taitoni on vielä perustasolla, ja opiskelen sitä aktiivisesti.",
                    "intermediate": "Puhun suomea keskitasolla ja kehitän taitoani jatkuvasti.",
                    "fluent": ""},
        "attached": "CV:ni on liitteenä, ja kerron mielelläni lisää puhelimessa tai haastattelussa.",
        "closing": "Ystävällisin terveisin",
        "just_applied": "Hain juuri tehtävää {job}{at_company}. CV ja hakemus ovat liitteenä myös tässä.",
        "at": " ({company})",
        "talk": "Kerron mielelläni lisää puhelimessa tai haastattelussa.",
    },
}

# CV-RULES.md section 5: words and patterns that make writing look AI-generated
AI_TELLS = re.compile(
    r"\b(?:crucial|enhance[sd]?|showcas\w*|foster\w*|leverag\w*|passionate|dynamic|results-driven|"
    r"proven track record|growing sector|team collaboration|not only\b.*\bbut also|"
    r"the importance of|i learned a lot|delve|seamless\w*|tapestry|testament)\b|—", re.I)

SENTENCE = {"type": "object", "properties": {"text": {"type": "string"},
                                              "fact_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "fact_ids"], "additionalProperties": False}
SENTENCES = {"type": "array", "items": SENTENCE}
SCHEMA = {
    "type": "object",
    "properties": {
        "cv_summary": {"type": "array", "items": SENTENCES},          # two paragraphs
        "letter": {"type": "object", "properties": {
            "why": SENTENCES, "experience": SENTENCES, "learning": SENTENCES, "practical": SENTENCES},
            "required": ["why", "experience", "learning", "practical"], "additionalProperties": False},
    },
    "required": ["cv_summary", "letter"],
    "additionalProperties": False,
}
PARAGRAPHS = ("why", "experience", "learning", "practical")


def _squash(text):
    return " ".join(str(text or "").split())


def profile_facts(profile, language):
    """The practical details as facts the letter may cite (prof-1, prof-2 ...)."""
    out = []
    for key, labels in PROFILE_FIELDS.items():
        value = _squash((profile or {}).get(key))
        if value:
            out.append({"id": f"prof-{len(out) + 1}", "section": "practical",
                        "text": f"{labels[1 if language == 'fi' else 0]}: {value}"})
    return out


def format_date(day, language):
    return f"{day.day}.{day.month}.{day.year}" if language == "fi" else f"{day.day} {EN_MONTHS[day.month - 1]} {day.year}"


def _first_name(name):
    name = _squash(name)
    return name.split()[0] if name else ""


def _fill(template, **values):
    return template.format(**{k: _squash(v) if k != "at_company" else v for k, v in values.items()})


def _company_place(job):
    company, place = _squash(job.get("company")), _squash((job.get("location") or "").split(",")[0])
    return " ".join(x for x in (company, place) if x) or _squash(job.get("title"))


def tailor_skills(skills, ad_text):
    """Skill rows (and items within a row) that the ad mentions come first; nothing is added or removed."""
    ad_words = {w for w in tokens(ad_text) if len(w) > 2 and w not in STOPWORDS}

    def hits(text):
        return sum(1 for w in tokens(text) if any(word_matches(a, w) for a in ad_words))

    rows = []
    for row in [r for r in (skills or "").splitlines() if r.strip()]:
        label, sep, items = row.partition(":")
        if sep and "," in items:
            parts = [p.strip() for p in items.split(",") if p.strip()]
            parts.sort(key=lambda p: -min(hits(p), 1))
            row = f"{label}: {', '.join(parts)}"
        rows.append(row)
    rows.sort(key=lambda r: -min(hits(r), 1))
    return "\n".join(rows)


def style_warnings(texts):
    found = []
    for text in texts:
        for match in AI_TELLS.finditer(text or ""):
            word = "em dash" if match.group(0) == "—" else match.group(0).lower()
            if word not in found:
                found.append(word)
    return found


def user_message(job, ad_text, facts, learning, missing, language):
    return "\n".join([
        f"<job>\ntitle: {_squash(job.get('title'))}\ncompany: {_squash(job.get('company'))}\n"
        f"place: {_squash(job.get('location'))}\n</job>",
        f"<job_ad>\n{ad_text}\n</job_ad>",
        f"<facts>\n{cv_facts.as_text(facts)}\n</facts>",
        f"<not_held>\n{chr(10).join(learning) or '(none)'}\n</not_held>",
        f"<ad_asks_for_but_cv_lacks>\n{chr(10).join(missing) or '(none)'}\n</ad_asks_for_but_cv_lacks>",
        f"<language>{language}</language>",
    ])


def _mock(facts, ad_text):
    """Mock mode: CV facts copied as sentences, labelled, so the whole flow can be tried without AI."""
    words = [w for w in tokens(ad_text) if len(w) > 3 and w not in STOPWORDS]

    def score(f):
        return sum(1 for w in words if any(word_matches(fw, w) for fw in tokens(f["text"])))
    ranked = sorted([f for f in facts if f["section"] not in ("summary", "practical")], key=lambda f: (-score(f), f["id"]))
    say = lambda f: {"text": f"{llm.MOCK_LABEL} {f['text']}", "fact_ids": [f["id"]]}
    practical = [say(f) for f in facts if f["section"] == "practical"][:3]
    return {"cv_summary": [[say(f) for f in ranked[:2]], [say(f) for f in ranked[2:3]]],
            "letter": {"why": [say(f) for f in ranked[:1]], "experience": [say(f) for f in ranked[1:3]],
                       "learning": [], "practical": practical}}


def _sentences(value):
    return [s for s in (value if isinstance(value, list) else []) if isinstance(s, dict)]


def prepare(job, cv_content, profile=None, recipient=None, language="en", finnish_level="none",
            settings=None, call=None, use_ai=True, today=None):
    """Raises ValueError for unusable input and core.llm.LLMError when a live call fails."""
    if language not in LANGUAGES:
        raise ValueError("Choose English (en) or Finnish (fi).")
    finnish_level = finnish_level if finnish_level in FINNISH_LEVELS else "none"
    ad_text = f"{job.get('title') or ''}\n{job.get('ad_text') or ''}".strip()[:core_fit.MAX_AD_CHARS]
    if len(ad_text) < 40:
        raise ValueError("This job has too little text to write for. Add the ad's description first.")
    content = dict(cv_content or {})
    if not _squash(content.get("full_name")):
        raise ValueError("Add your name to the CV first: the letter is signed with it.")
    extracted = cv_facts.facts_from_cv(content)
    facts = extracted["facts"] + profile_facts(profile, language)
    if not extracted["facts"]:
        raise ValueError("This CV is empty. Add your experience and skills first.")
    learning = extracted["learning"]
    missing = core_fit.missing_requirements(ad_text, extracted["facts"])
    settings = settings or llm.settings_from_env()
    if settings.live and use_ai:
        reply = (call or llm.call_json)(PROMPT_FILE.read_text(encoding="utf-8"),
                                        user_message(job, ad_text, facts, learning, missing, language),
                                        SCHEMA, settings, max_tokens=6000)
        raw = reply["data"] if isinstance(reply.get("data"), dict) else {}
        method, model, notice = "llm", reply.get("model", settings.model), ""
    else:
        raw = _mock(facts, ad_text)
        method, model = "mock" if not settings.live else "copy", ""
        notice = (f"{llm.MOCK_LABEL} Mock mode copies facts from your CV; it doesn't write the text."
                  if not settings.live else
                  "Without AI, JobDesk copies facts from your CV into the letter. Rewrite them in your own words, "
                  "or turn on “AI with your CV” under Account.")
    check = lambda sentences: verify.verify(sentences, facts, learning, missing)

    # The tailored CV: a new summary (two paragraphs) and the ad's skills first
    summary = [check(_sentences(p)) for p in (raw.get("cv_summary") or [])[:2] if isinstance(p, list)]
    summary = [p for p in summary if p]
    tailored = {**content, "target_role": _squash(job.get("title")) or content.get("target_role", ""),
                "skills": tailor_skills(content.get("skills", ""), ad_text)}
    if summary:
        tailored["summary"] = "\n\n".join(" ".join(s["text"] for s in p) for p in summary)

    t = TEXT[language]
    job_title, company = _squash(job.get("title")), _squash(job.get("company"))
    recipient = recipient or {}
    first = _first_name(recipient.get("name"))
    greeting = _fill(t["greeting"], first=first) if first else t["greeting_none"]
    subject = _fill(t["subject"], job=job_title, company_place=_company_place(job))
    letter_raw = raw.get("letter") if isinstance(raw.get("letter"), dict) else {}
    checked = {key: check(_sentences(letter_raw.get(key))) for key in PARAGRAPHS}
    opener = {"text": _fill(t["opener"] if company else t["opener_nc"], job=job_title, company=company), "fact_ids": [],
              "status": "template", "reasons": []}
    closing_lines = [s for s in (t["finnish"][finnish_level], t["attached"]) if s]
    paragraphs = [[opener] + checked["why"], checked["experience"], checked["learning"], checked["practical"],
                  [{"text": s, "fact_ids": [], "status": "template", "reasons": []} for s in closing_lines]]
    paragraphs = [p for p in paragraphs if p]
    who = ", ".join(x for x in (_squash(recipient.get("name")), _squash(recipient.get("title"))) if x)
    recipient_lines = [who, company] + [_squash(line) for line in str(recipient.get("address") or "").splitlines()]
    letter = {
        "language": language, "name": _squash(content.get("full_name")), "job_title": job_title,
        "location": _squash(content.get("location")), "phone": _squash(content.get("phone")),
        "email": _squash(content.get("email")), "date": format_date(today or date.today(), language),
        "recipient": "\n".join(line for line in recipient_lines if line), "subject": subject, "greeting": greeting,
        "paragraphs": [" ".join(s["text"] for s in p) for p in paragraphs], "closing": t["closing"],
    }

    strongest = [s["text"] for s in checked["experience"] + checked["why"] if s["status"] == "supported"][:3]
    body = [greeting, "", _fill(t["just_applied"], job=job_title,
                                at_company=t["at"].format(company=company) if company else "")]
    if strongest:
        body += ["", " ".join(strongest)]
    body += ["", " ".join(x for x in (t["finnish"][finnish_level], t["talk"]) if x), "", t["closing"],
             letter["name"]] + [x for x in (letter["phone"], letter["email"]) if x]
    email = {"to": _squash(recipient.get("email")), "subject": subject, "body": "\n".join(body)}

    all_sentences = [s for p in paragraphs for s in p] + [s for p in summary for s in p]
    generated = [s for s in all_sentences if s["status"] != "template"]
    return {
        "cv_content": tailored, "letter": letter, "email": email,
        "checks": {"letter_sentences": paragraphs, "summary_sentences": summary,
                   "unsupported": sum(1 for s in generated if s["status"] == "unsupported"),
                   "style": style_warnings([s["text"] for s in generated]), "ad_blockers": missing},
        "method": method, "model": model, "prompt_version": PROMPT_VERSION, "notice": notice,
    }
