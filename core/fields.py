"""Field profiles: what counts as a job in a field (forestry, IT, health ...), which skills its ads
ask for and which role types it has. Profiles are JSON files (fields/*.json), not code, so a new
field needs no programming.

A profile:
    id, order, label_en, label_fi, category      names; category is the job "Type" shown in the list
    search_terms     words for portals that search by keyword (Kuntarekry)
    jobly            {"slugs": Jobly category pages, "title_words": a job title must contain one}
    relevance        {"words", "core_words", "whole_words", "ignore_patterns"}
    skills           [{"id", "en", "fi", "group", "pattern", "hint"}]  pattern = regex, Finnish + English
    role_types       [{"id", "en", "fi", "pattern"}]                   matched against job titles

is_relevant(job, profile, kind, source_fields) decides whether a job belongs to a field. kind comes
from the source (sources.json):
    field_board   a board that lists only its own field's jobs: everything counts for those fields.
    broad_portal  a portal with every public-sector job (Valtiolle, Kuntarekry): words such as
                  "ilmasto" or "tietojärjestelmä" appear in police and school ads too, so the TITLE
                  must contain a field word, or the AD TEXT one of the stricter core_words.
    anything else the title, description, ad text or location must contain a field word.
Words are lower-case substrings ("metsänhoit" matches "metsänhoitaja"), except whole_words, which
must stand alone ("gis" must not match "logistiikka").
"""

import json
import re
from pathlib import Path

REQUIRED = ("id", "label_en", "label_fi", "category", "search_terms", "jobly", "relevance", "skills", "role_types")


class FieldError(ValueError):
    """A profile file is missing something or has an invalid pattern."""


def _compile(pattern, where):
    try:
        return re.compile(pattern, re.I)
    except re.error as error:
        raise FieldError(f"{where}: invalid pattern {pattern!r} ({error})") from error


def load_profile(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FieldError(f"{path.name}: can't read it ({error})") from error
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise FieldError(f"{path.name}: missing {', '.join(missing)}")
    relevance = data["relevance"]
    for key in ("words", "core_words"):
        if not relevance.get(key):
            raise FieldError(f"{path.name}: relevance.{key} is empty")
    relevance.setdefault("whole_words", [])
    relevance.setdefault("ignore_patterns", [])
    data.setdefault("order", 100)
    data["_ignore"] = [_compile(p, f"{path.name} ignore_patterns") for p in relevance["ignore_patterns"]]
    seen = set()
    for skill in data["skills"]:
        if skill["id"] in seen:
            raise FieldError(f"{path.name}: skill id {skill['id']!r} appears twice")
        seen.add(skill["id"])
        skill["regex"] = _compile(skill["pattern"], f"{path.name} skill {skill['id']}")
    for role in data["role_types"]:
        role["regex"] = _compile(role["pattern"], f"{path.name} role type {role['id']}")
    return data


def load_profiles(directory):
    """{id: profile}, in display order (the profiles' "order", then id)."""
    profiles = [load_profile(path) for path in sorted(Path(directory).glob("*.json"))]
    ids = [p["id"] for p in profiles]
    if len(ids) != len(set(ids)):
        raise FieldError("Two field profiles share an id.")
    return {p["id"]: p for p in sorted(profiles, key=lambda p: (p["order"], p["id"]))}


def has_word(text, word, whole_words=()):
    """Is the (lower-case) word in text? Whole words must stand alone."""
    t = (text or "").lower()
    if word in whole_words:
        return re.search(rf"\b{re.escape(word)}\b", t) is not None
    return word in t


def _any(text, words, whole_words):
    return any(has_word(text, word, whole_words) for word in words)


def is_relevant(job, profile, kind="general", source_fields=None):
    """Does this job belong to the profile's field? job: dict with title, description, ad_text, location.
    source_fields: the fields the job's source covers ("all" or a list), used for field boards."""
    relevance = profile["relevance"]
    whole = relevance["whole_words"]
    if kind == "field_board":
        return source_fields == "all" or profile["id"] in (source_fields or ())
    if kind == "broad_portal":
        ad = " ".join((job.get(field) or "") for field in ("description", "ad_text")).lower()
        for pattern in profile["_ignore"]:
            ad = pattern.sub(" ", ad)
        return _any(job.get("title") or "", relevance["words"], whole) or _any(ad, relevance["core_words"], whole)
    text = " ".join((job.get(field) or "") for field in ("title", "description", "ad_text", "location"))
    return _any(text, relevance["words"], whole)


def relevant_field_ids(job, profiles, kind="general", source_fields=None):
    """Ids of the given profiles this job belongs to, in profile order."""
    return [p["id"] for p in profiles if is_relevant(job, p, kind, source_fields)]


def merged_skills(profiles):
    """All skills of the given profiles; the first profile's version of a shared id wins."""
    skills, seen = [], set()
    for profile in profiles:
        for skill in profile["skills"]:
            if skill["id"] not in seen:
                seen.add(skill["id"])
                skills.append(skill)
    return skills


def role_types(profiles):
    return [role for profile in profiles for role in profile["role_types"]]


def summary(profile):
    """The public part of a profile, for the browser."""
    return {key: profile[key] for key in ("id", "label_en", "label_fi", "category")}
