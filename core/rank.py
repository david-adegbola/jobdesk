"""A ranked shortlist: which ads fit a student's skills, and which are realistic given their Finnish.

rank(ads, skills, finnish_results, student_finnish) -> list, best first. For each ad:

1. Skill match. Each skill in the student's list (e.g. "QGIS", "remote sensing", "Python") counts
   as matched when every significant word of it matches a word in the ad, using the same
   Finnish-aware rule as the rest of JobDesk (core.text.word_matches: case endings, compounds).
   skill_score = 100 * matched skills / all skills. A skill that also appears in the title adds
   to a tie-break, not the score.
2. Finnish tier, from the classifier result for that ad:
       not_needed -> 0, preferred -> 1, unclear -> 2, required -> 3.
   Required ads are sorted last, not hidden. A student who says they are fluent in Finnish gets
   tier 0 for every ad: the level is still shown, but doesn't change their order.
3. Sort by (tier, -skill_score, -skills in title, ad id).

Every result carries "reasons": short sentences saying why it is where it is, including the
quoted Finnish evidence, so the order can always be checked by reading.
"""

from core.text import STOPWORDS, tokens, word_matches

TIERS = {"not_needed": 0, "preferred": 1, "unclear": 2, "required": 3}
FINNISH_LEVELS = ("none", "basic", "intermediate", "fluent")
LEVEL_TEXT = {
    "required": "Finnish is required",
    "preferred": "Finnish is an advantage, not a requirement",
    "not_needed": "Finnish is not needed",
    "unclear": "The ad doesn't say clearly whether Finnish is needed",
}


def _skill_words(skill):
    return [w for w in tokens(skill) if w not in STOPWORDS]


def _part_found(part, words):
    # One- and two-letter skills ("R", "C") must match a whole word, or "r" would match "rooli"
    if len(part) <= 2:
        return part in words
    return any(word_matches(w, part) for w in words)


def skill_matches(text, skills):
    """The skills (as the student wrote them) whose every significant word matches a word in text."""
    words = set(tokens(text))
    matched = []
    for skill in skills:
        parts = _skill_words(skill)
        if parts and all(_part_found(part, words) for part in parts):
            matched.append(skill)
    return matched


def rank(ads, skills, finnish_results, student_finnish="none"):
    """ads: [{"id", "title", "url", "ad_text"}]; skills: list of strings;
    finnish_results: {ad id: result from core.finnish.classify or .fallback};
    student_finnish: one of FINNISH_LEVELS."""
    if student_finnish not in FINNISH_LEVELS:
        raise ValueError(f"student_finnish must be one of {', '.join(FINNISH_LEVELS)}.")
    skills = [s.strip() for s in skills if s and s.strip()]
    fluent = student_finnish == "fluent"
    rows = []
    for ad in ads:
        text = f"{ad.get('title') or ''}\n{ad.get('ad_text') or ''}"
        matched = skill_matches(text, skills)
        in_title = skill_matches(ad.get("title") or "", matched)
        score = round(100 * len(matched) / len(skills)) if skills else 0
        result = finnish_results.get(ad["id"]) or {"level": "unclear", "evidence": [], "method": "none"}
        level = result.get("level", "unclear")
        tier = 0 if fluent else TIERS.get(level, TIERS["unclear"])
        reasons = []
        if skills:
            reasons.append(f"Matches {len(matched)} of your {len(skills)} skills"
                           + (f": {', '.join(matched)}." if matched else "."))
        finnish_line = LEVEL_TEXT.get(level, LEVEL_TEXT["unclear"])
        if result.get("evidence"):
            finnish_line += f' – the ad says: "{result["evidence"][0]}"'
        reasons.append(finnish_line + ("" if finnish_line.endswith(".") else "."))
        if fluent and level == "required":
            reasons.append("You said you are fluent in Finnish, so this doesn't lower the ad.")
        rows.append({"id": ad["id"], "title": ad.get("title") or "", "url": ad.get("url") or "",
                     "skill_score": score, "matched_skills": matched, "skills_in_title": len(in_title),
                     "finnish": result, "tier": tier, "reasons": reasons})
    rows.sort(key=lambda r: (r["tier"], -r["skill_score"], -r["skills_in_title"], r["id"]))
    return rows
