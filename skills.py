"""What to study: the skills that the job ads ask for, compared with the member's own CVs.

Jobs are grouped into role types by title (Finnish and English). For each role type, every skill in
SKILLS is looked for in the ads (title + saved ad text) and in the member's CVs. Skills that the ads
ask for but no CV mentions are the ones to study next. This is transparent keyword matching, not an
AI judgement: each skill shows how many ads mention it, and the patterns are listed below.

A CV draft for a role type starts from the member's closest CV. Skills still to learn go on a
"Want to learn" row (the same convention as the original role CVs), never as skills already held.
"""

import re

import match
import scraper
from core import fields as core_fields

# Skills and role types come from the field profiles (fields/*.json, loaded by scraper.PROFILES).
# Each skill: id, English and Finnish label, group, a regex matched in Finnish and English ad text,
# and a study hint. Role types are matched against job titles, first match wins.
# SKILLS and ROLE_TYPES are the forestry ones, kept for callers that don't pass profiles.
SKILLS = scraper.FORESTRY["skills"]
ROLE_TYPES = scraper.FORESTRY["role_types"]
OTHER = {"id": "other", "en": "Other forestry roles", "fi": "Muut metsäalan tehtävät"}
INTERNSHIP = re.compile(r"harjoittel|kesätyö|kesäty|intern|trainee|summer job|summer employee|kesä 20", re.I)

MIN_JOBS = 2          # a skill must appear in at least this many of a role type's ads to be suggested
STUDY_LIMIT = 8       # suggestions shown per role type


def role_type(job, role_types=None):
    """The role type for one job: personal (administrator-only) jobs keep their category."""
    if job.get("personal"):
        category = job.get("category") or "Other"
        return {"id": "personal-" + re.sub(r"\W+", "-", category.lower()), "en": category, "fi": category}
    title = job.get("title") or ""
    return next((rt for rt in (role_types or ROLE_TYPES) if rt["regex"].search(title)), OTHER)


def skills_in(text, skills=None):
    """Ids of the skills mentioned in a text."""
    return {skill["id"] for skill in (skills or SKILLS) if skill["regex"].search(text or "")}


LEARN_ROW = re.compile(r"^\s*(?:haluan oppia|want to learn)\s*:.*$", re.I | re.M)


def cv_text(cv):
    """A CV's text without its "Want to learn" rows: wanting a skill is not having it."""
    content = cv.get("content") or {}
    return LEARN_ROW.sub(" ", " ".join([cv.get("title") or ""] + [str(v) for v in content.values()]))


def _title_stems(text):
    return {match.stem(w) for w in match.tokens(text) if len(w) > 3 and w not in match.STOPWORDS}


def analyse(jobs, cvs, profiles=None):
    """Role types with the skills their ads ask for, split into have / study next.
    profiles: the member's field profiles (default: forestry). Their skills are merged (first
    profile wins on a shared id) and their role types tried in order."""
    profiles = profiles or [scraper.FORESTRY]
    skills = core_fields.merged_skills(profiles)
    role_types = core_fields.role_types(profiles)
    have_any = set()
    cv_skills = {}
    for cv in cvs:
        cv_skills[cv["id"]] = skills_in(cv_text(cv), skills)
        have_any |= cv_skills[cv["id"]]
    by_id = {skill["id"]: skill for skill in skills}
    groups = {}
    for job in jobs:
        rt = role_type(job, role_types)
        group = groups.setdefault(rt["id"], {"id": rt["id"], "label": rt["en"], "label_fi": rt["fi"],
                                             "personal": rt["id"].startswith("personal-"),
                                             "jobs": 0, "with_ad_text": 0, "internships": 0,
                                             "counts": {}, "examples": [], "title_words": {}})
        group["jobs"] += 1
        group["with_ad_text"] += bool(job.get("ad_text"))
        group["internships"] += bool(INTERNSHIP.search(job.get("title") or ""))
        for word in _title_stems(job.get("title")):
            group["title_words"][word] = group["title_words"].get(word, 0) + 1
        if len(group["examples"]) < 3:
            group["examples"].append({"id": job.get("id"), "title": job.get("title"), "url": job.get("url") or ""})
        for skill_id in skills_in(" ".join([job.get("title") or "", job.get("ad_text") or ""]), skills):
            group["counts"][skill_id] = group["counts"].get(skill_id, 0) + 1

    result = []
    for group in groups.values():
        asked = sorted(group.pop("counts").items(), key=lambda item: (-item[1], by_id[item[0]]["en"]))

        def row(skill_id, n):
            skill = by_id[skill_id]
            return {"id": skill_id, "label": skill["en"], "label_fi": skill["fi"], "group": skill["group"],
                    "hint": skill["hint"], "jobs": n, "percent": round(100 * n / group["jobs"])}

        group["study"] = [row(s, n) for s, n in asked if s not in have_any and n >= MIN_JOBS][:STUDY_LIMIT]
        group["have"] = [row(s, n) for s, n in asked if s in have_any]
        title_words = group.pop("title_words")
        wanted = {s for s, _ in asked}

        def closeness(cv):
            """Shared skills, then words shared by the CV's title/target role and the job titles,
            then (for field roles) a CV aimed at one of the member's fields. Highest wins."""
            content = cv.get("content") or {}
            heading = f"{cv.get('title') or ''} {content.get('target_role') or ''}"
            return (len(cv_skills[cv["id"]] & wanted),
                    sum(title_words.get(word, 0) for word in _title_stems(heading)),
                    not group["personal"] and any(core_fields.is_relevant({"title": heading}, p)
                                                  for p in profiles),
                    -cv["id"])
        best = max(cvs, key=closeness, default=None)
        group["closest_cv"] = {"id": best["id"], "title": best["title"]} if best else None
        result.append(group)
    result.sort(key=lambda g: (g["personal"], -g["jobs"], g["label"]))
    return {"role_types": result, "cv_count": len(cvs), "total_jobs": len(jobs),
            "jobs_with_ad_text": sum(1 for job in jobs if job.get("ad_text"))}


def draft_cv(role, cvs, study, language=None):
    """An unsaved CV for a role type: the closest CV's content, the role as target, and the skills
    still to learn on a "Want to learn" row. study is the role type's study list from analyse()."""
    base = role.get("closest_cv") and next((cv for cv in cvs if cv["id"] == role["closest_cv"]["id"]), None)
    language = language or (base["language"] if base else "en")
    if base and base["language"] != language:     # use the same CV's version in that language, if any
        other = (base.get("versions") or {}).get(language)
        base = next((cv for cv in cvs if cv["id"] == other), base)
    content = dict(base["content"]) if base else {}
    label = role["label_fi"] if language == "fi" else role["label"]
    content["target_role"] = label
    learn = ", ".join(s["label_fi"] if language == "fi" else s["label"] for s in study)
    if learn:
        row = f"{'Haluan oppia' if language == 'fi' else 'Want to learn'}: {learn}"
        lines = [line for line in (content.get("skills") or "").splitlines() if not LEARN_ROW.match(line)]
        content["skills"] = "\n".join(lines + [row]).strip()
    return {"title": f"{label} CV", "language": language, "content": content,
            "based_on": base["title"] if base else ""}
